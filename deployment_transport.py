from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
from typing import Mapping

from deployment_center import CapabilityReport, DeploymentTarget

_PROBE_PREFIX = "CHECKUPAUTO_PROBE_V1"
_ALLOWED_KEYS = {
    "python",
    "node",
    "passenger",
    "systemd",
    "cron",
    "symlink",
    "writable_root",
    "free_disk_mb",
    "cloudlinux_selector",
    "managed_python",
}


@dataclass(frozen=True)
class SSHCredential:
    identity_file: str = ""
    password: str = ""

    def validate(self, auth_mode: str) -> "SSHCredential":
        if auth_mode == "key":
            path = Path(self.identity_file).expanduser()
            if not path.is_file():
                raise ValueError("clé SSH introuvable")
            return SSHCredential(identity_file=str(path), password="")
        if auth_mode == "password":
            if not self.password or "\n" in self.password or "\r" in self.password:
                raise ValueError("mot de passe SSH invalide")
            return SSHCredential(identity_file="", password=self.password)
        raise ValueError("mode d authentification SSH invalide")


def ssh_arguments(
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: SSHCredential,
) -> list[str]:
    cred = credential.validate(target.auth_mode)
    hosts = Path(known_hosts).expanduser()
    if not hosts.is_file():
        raise ValueError("fichier known_hosts absent")

    args = [
        "ssh",
        "-p",
        str(target.port),
        "-o",
        "ConnectTimeout=12",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={hosts}",
        "-o",
        "LogLevel=ERROR",
    ]
    if target.auth_mode == "key":
        args.extend([
            "-o",
            "BatchMode=yes",
            "-i",
            cred.identity_file,
        ])
    else:
        args.extend([
            "-o",
            "BatchMode=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
        ])
    args.append(f"{target.username}@{target.host}")
    return args


def remote_probe_script(target: DeploymentTarget) -> str:
    root = shlex.quote(target.root_path)
    return f"""set -eu
printf '{_PROBE_PREFIX}\\n'
root={root}
probe_parent="$root"
if [ ! -d "$probe_parent" ]; then
  probe_parent="$(dirname "$root")"
fi
python_value="$(python3 --version 2>&1 || true)"
node_value="$(node --version 2>&1 || true)"
cloudlinux=0
managed_python=""
if command -v cloudlinux-selector >/dev/null 2>&1; then
  cloudlinux=1
  selector_json="$(cloudlinux-selector get --json --interpreter python 2>/dev/null || true)"
  if [ -n "$selector_json" ]; then
    managed_python="$(printf '%s' "$selector_json" | python3 -c 'import json,re,sys
try:
 data=json.load(sys.stdin)
except Exception:
 raise SystemExit(0)
found=set()
def walk(value):
 if isinstance(value,dict):
  for key,item in value.items():
   walk(str(key)); walk(item)
 elif isinstance(value,(list,tuple)):
  for item in value: walk(item)
 elif isinstance(value,(str,int,float)):
  text=str(value).strip()
  if re.fullmatch(r"3\.(?:1[1-9]|[2-9][0-9])(?:\.\d+)?",text):
   found.add(text)
walk(data)
def version(text):
 return tuple(int(part) for part in text.split("."))
print(max(found,key=version) if found else "")' 2>/dev/null || true)"
  fi
fi
if [ "$cloudlinux" -eq 1 ] || command -v passenger-config >/dev/null 2>&1 || command -v passenger >/dev/null 2>&1; then passenger=1; else passenger=0; fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then systemd=1; else systemd=0; fi
if command -v crontab >/dev/null 2>&1; then cron=1; else cron=0; fi
if [ -d "$root" ]; then
  if [ -w "$root" ]; then writable=1; else writable=0; fi
else
  if [ -d "$probe_parent" ] && [ -w "$probe_parent" ]; then writable=1; else writable=0; fi
fi
symlink=0
tmp=""
if [ "$writable" -eq 1 ]; then
  tmp="$probe_parent/.checkupauto-probe-$$"
  if mkdir "$tmp" 2>/dev/null; then
    : > "$tmp/source"
    if ln -s source "$tmp/link" 2>/dev/null && [ -L "$tmp/link" ]; then symlink=1; fi
    rm -rf "$tmp"
  fi
fi
disk="$(df -Pm "$probe_parent" 2>/dev/null | awk 'NR==2 {{print $4}}' || true)"
case "$disk" in ''|*[!0-9]*) disk=0 ;; esac
printf 'python=%s\\n' "$python_value"
printf 'node=%s\\n' "$node_value"
printf 'passenger=%s\\n' "$passenger"
printf 'systemd=%s\\n' "$systemd"
printf 'cron=%s\\n' "$cron"
printf 'symlink=%s\\n' "$symlink"
printf 'writable_root=%s\\n' "$writable"
printf 'free_disk_mb=%s\\n' "$disk"
"""


def _parse_bool(value: str) -> bool:
    return value.strip() == "1"


def parse_probe(
    output: str,
    *,
    passenger_wsgi_adapter: bool = False,
    shared_host_tick: bool = False,
) -> CapabilityReport:
    lines = str(output or "").splitlines()
    if not lines or lines[0].strip() != _PROBE_PREFIX:
        raise ValueError("réponse de diagnostic SSH invalide")
    values: dict[str, str] = {}
    for line in lines[1:]:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in _ALLOWED_KEYS:
            values[key] = value.strip()

    required = {"python", "passenger", "systemd", "cron", "symlink", "writable_root", "free_disk_mb"}
    if not required.issubset(values):
        raise ValueError("diagnostic SSH incomplet")
    try:
        free_disk = int(values["free_disk_mb"])
    except ValueError as exc:
        raise ValueError("espace disque distant invalide") from exc

    return CapabilityReport(
        python_version=values["python"],
        node_version=values.get("node", ""),
        passenger=_parse_bool(values["passenger"]),
        systemd=_parse_bool(values["systemd"]),
        cron=_parse_bool(values["cron"]),
        symlink=_parse_bool(values["symlink"]),
        writable_root=_parse_bool(values["writable_root"]),
        free_disk_mb=max(0, free_disk),
        passenger_wsgi_adapter=bool(passenger_wsgi_adapter),
        shared_host_tick=bool(shared_host_tick),
        cloudlinux_selector=_parse_bool(values.get("cloudlinux_selector", "0")),
        managed_python_version=values.get("managed_python", ""),
    )


def _run_password_ssh(
    args: list[str],
    remote_script: str,
    password: str,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    setsid = shutil.which("setsid")
    if not setsid:
        raise RuntimeError("setsid requis pour l authentification SSH par mot de passe")

    with tempfile.TemporaryDirectory(prefix="checkupauto-askpass-") as tmp:
        helper = Path(tmp) / "askpass.sh"
        helper.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$CHECKUPAUTO_SSH_PASSWORD\"\n",
            encoding="utf-8",
        )
        helper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        env = os.environ.copy()
        env.update({
            "DISPLAY": "checkupauto:0",
            "SSH_ASKPASS": str(helper),
            "SSH_ASKPASS_REQUIRE": "force",
            "CHECKUPAUTO_SSH_PASSWORD": password,
        })
        return subprocess.run(
            [setsid, "-w", *args, "sh", "-s"],
            input=remote_script,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )


def probe_target(
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: SSHCredential,
    *,
    passenger_wsgi_adapter: bool = False,
    shared_host_tick: bool = False,
    timeout: int = 30,
) -> CapabilityReport:
    cred = credential.validate(target.auth_mode)
    args = ssh_arguments(target, known_hosts, cred)
    script = remote_probe_script(target)

    if target.auth_mode == "password":
        result = _run_password_ssh(
            args,
            script,
            cred.password,
            timeout=timeout,
        )
    else:
        result = subprocess.run(
            [*args, "sh", "-s"],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    if result.returncode != 0:
        raise RuntimeError("connexion ou diagnostic SSH impossible")
    return parse_probe(
        result.stdout,
        passenger_wsgi_adapter=passenger_wsgi_adapter,
        shared_host_tick=shared_host_tick,
    )


def sanitized_connection(target: DeploymentTarget) -> Mapping[str, object]:
    return {
        "provider": target.provider,
        "host": target.host,
        "port": target.port,
        "username": target.username,
        "domain": target.domain,
        "rootPath": target.root_path,
        "authMode": target.auth_mode,
    }
