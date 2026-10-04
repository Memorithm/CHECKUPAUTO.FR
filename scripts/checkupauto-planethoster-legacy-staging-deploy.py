#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import deployment_center
import deployment_release
import deployment_transport
import deployment_update

TARGET = {
    "provider": "planethoster-n0c",
    "host": "nodels49-eu.n0c.com",
    "port": 5022,
    "username": "eqcrhuya",
    "domain": "test.checkupauto.fr",
    "rootPath": ".checkupauto-test",
    "webRootPath": "test.checkupauto.fr",
    "authMode": "key",
}
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RESULT_PREFIX = "CHECKUPAUTO_LEGACY_ADAPTER_DEPLOY="


def _activation_program(sha: str) -> str:
    if not _SHA.fullmatch(sha):
        raise ValueError("SHA invalide")
    return r'''from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib import request

SHA = __SHA__
home = Path.home().resolve()
private = (home / ".checkupauto-test").resolve()
releases = (private / "releases").resolve()
release = (releases / SHA).resolve()
current = private / "current"
shared = (private / "shared").resolve()
app = (home / "checkupauto-test-application").resolve()
restart = app / "tmp/restart.txt"
domain = "test.checkupauto.fr"


def fail(message):
    raise RuntimeError(message)


def under(path, parent):
    return path == parent or parent in path.parents


def marker(path):
    p = path / ".checkupauto-release.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        fail("release marker invalid")
    if data.get("sha") != path.name or data.get("verified") is not True:
        fail("release marker mismatch")
    return data


def touch_restart():
    if not app.is_dir() or not (app / "passenger_wsgi.py").is_file():
        fail("legacy Passenger adapter missing")
    restart.parent.mkdir(mode=0o700, exist_ok=True)
    restart.touch()
    os.chmod(restart, 0o600)


if not private.is_dir() or not releases.is_dir() or not shared.is_dir():
    fail("legacy staging layout missing")
if not release.is_dir() or not under(release, releases):
    fail("staged release missing")
marker(release)
if not (release / ".venv/bin/python").is_file():
    fail("staged Python missing")
if not (release / "passenger_wsgi.py").is_file():
    fail("staged Passenger entrypoint missing")
if not (release / "scripts/checkupauto-update-safety.py").is_file():
    fail("update safety helper missing")
if not current.is_symlink():
    fail("current symlink missing")
previous = current.resolve(strict=True)
if not under(previous, releases):
    fail("previous release outside managed root")
previous_sha = previous.name
marker(previous)
if previous_sha == SHA:
    print(__PREFIX__ + json.dumps({"ok": True, "state": "already_current", "sha": SHA, "previousSha": previous_sha}, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0)

env = os.environ.copy()
env.update({
    "CYBERCHECK_DATA_DIR": str(shared / "data"),
    "CYBERCHECK_PRIVATE_DIR": str(shared / "private"),
    "CYBERCHECK_SECURITY_DIR": str(shared / "security"),
    "CYBERCHECK_INTEGRITY_DIR": str(shared / "integrity"),
    "CYBERCHECK_SITE_CONFIG_PATH": str(shared / "data/site-config.json"),
    "CYBERCHECK_GSC_CREDENTIALS_PATH": str(shared / "private/gsc-service-account.json"),
    "CYBERCHECK_MOBILE_PUSH_ENABLED": "0",
    "CYBERCHECK_PAYMENT_REQUIRED": "1",
    "CYBERCHECK_PAYMENT_TEST_ENABLED": "1",
})

backup = subprocess.run(
    [
        str(release / ".venv/bin/python"),
        str(release / "scripts/checkupauto-update-safety.py"),
        "backup",
        "--private-root", str(private),
        "--from-sha", previous_sha,
        "--to-sha", SHA,
    ],
    cwd=release,
    env=env,
    text=True,
    capture_output=True,
    timeout=180,
    check=False,
)
if backup.returncode != 0:
    fail("pre-activation backup failed")

probe = subprocess.run(
    [str(release / ".venv/bin/python"), "-c", "import admin_server,compliance_admin; print('IMPORT_OK')"],
    cwd=release,
    env=env,
    text=True,
    capture_output=True,
    timeout=90,
    check=False,
)
if probe.returncode != 0 or "IMPORT_OK" not in probe.stdout:
    fail("staged application import failed")

incoming = private / (".current-" + str(os.getpid()))
try:
    incoming.unlink()
except FileNotFoundError:
    pass
os.symlink(release, incoming)

switched = False
try:
    os.replace(incoming, current)
    switched = True
    touch_restart()

    legal = {
        "/mentions-legales": "legacy-rdv-2026-10-04",
        "/confidentialite": "legacy-rdv-2026-10-04",
        "/cookies": "legacy-rdv-2026-10-04",
        "/cgv": "mercureweb-2022-legacy",
        "/retractation": "mercureweb-2022-legacy",
    }
    observed = {}
    last_error = "unavailable"
    for attempt in range(20):
        try:
            with request.urlopen("https://" + domain + "/api/app/status", timeout=10) as response:
                if response.status != 200:
                    fail("app status invalid")
                response.read(200000)
            for path, version in legal.items():
                with request.urlopen("https://" + domain + path, timeout=10) as response:
                    if response.status != 200:
                        fail("legal page status invalid")
                    body = response.read(300000).decode("utf-8", errors="strict")
                if "Document juridique non publi" in body:
                    fail("unpublished legal placeholder")
                if version not in body:
                    fail("legal version mismatch")
                observed[path] = 200
            break
        except Exception as exc:
            last_error = type(exc).__name__
            observed = {}
            time.sleep(3)
    if len(observed) != len(legal):
        fail("post-activation HTTP verification failed: " + last_error)

    sys.path.insert(0, str(release))
    import compliance_admin
    snapshot = compliance_admin.snapshot()
    summary = snapshot.get("summary") or {}

    print(__PREFIX__ + json.dumps({
        "ok": True,
        "state": "activated",
        "sha": SHA,
        "previousSha": previous_sha,
        "legalPages": observed,
        "phase2CoverageReady": bool(summary.get("phase2CoverageReady")),
        "readyForPublicContracting": bool(summary.get("readyForPublicContracting")),
        "phase2Blockers": list(summary.get("phase2Blockers") or []),
        "operationalBlockerTypes": [
            str(row.get("type") or "")
            for row in summary.get("operationalBlockers") or []
            if isinstance(row, dict)
        ],
    }, sort_keys=True, separators=(",", ":")))
except Exception:
    if switched:
        rollback = private / (".rollback-" + str(os.getpid()))
        try:
            rollback.unlink()
        except FileNotFoundError:
            pass
        os.symlink(previous, rollback)
        os.replace(rollback, current)
        touch_restart()
    raise
'''.replace("__SHA__", repr(sha)).replace("__PREFIX__", repr(_RESULT_PREFIX))


def _parse_result(stdout: str) -> dict:
    for line in str(stdout or "").splitlines():
        if line.startswith(_RESULT_PREFIX):
            payload = json.loads(line[len(_RESULT_PREFIX):])
            if isinstance(payload, dict) and payload.get("ok") is True:
                return payload
    raise RuntimeError("réponse activation legacy invalide")


def _legacy_capability_probe(target, known_hosts: str, credential) -> dict:
    """Probe the already-running N0C/Passenger layout without assuming shell PATH."""
    args = deployment_transport.ssh_arguments(target, known_hosts, credential)
    script = r'''set -eu
root="$HOME/.checkupauto-test"
app="$HOME/checkupauto-test-application"
python=/opt/alt/python312/bin/python3
test -x "$python"
"$python" --version >/dev/null 2>&1
test -d "$root"
test -w "$root"
test -d "$root/releases"
test -d "$root/shared"
test -d "$app"
test -f "$app/passenger_wsgi.py"
test -d "$app/tmp"
test -w "$app/tmp"
probe="$root/.legacy-capability-$"
mkdir "$probe"
trap 'rm -rf "$probe"' EXIT HUP INT TERM
: > "$probe/source"
ln -s source "$probe/link"
test -L "$probe/link"
disk="$(df -Pm "$root" | awk 'NR==2 {print $4}')"
case "$disk" in ''|*[!0-9]*) exit 31 ;; esac
printf 'CHECKUPAUTO_LEGACY_CAPABILITY_V1\n'
printf 'python_path=%s\n' "$python"
printf 'passenger_adapter=1\n'
printf 'writable_root=1\n'
printf 'writable_restart=1\n'
printf 'symlink=1\n'
printf 'free_disk_mb=%s\n' "$disk"
'''
    result = subprocess.run(
        [*args, "sh", "-s"],
        input=script,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("diagnostic legacy PlanetHoster impossible")
    values = {}
    lines = result.stdout.splitlines()
    if not lines or lines[0].strip() != "CHECKUPAUTO_LEGACY_CAPABILITY_V1":
        raise RuntimeError("diagnostic legacy PlanetHoster invalide")
    for line in lines[1:]:
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    required = {
        "python_path",
        "passenger_adapter",
        "writable_root",
        "writable_restart",
        "symlink",
        "free_disk_mb",
    }
    if not required.issubset(values):
        raise RuntimeError("diagnostic legacy PlanetHoster incomplet")
    try:
        disk = int(values["free_disk_mb"])
    except ValueError as exc:
        raise RuntimeError("espace disque legacy invalide") from exc
    ok = (
        values["python_path"] == "/opt/alt/python312/bin/python3"
        and values["passenger_adapter"] == "1"
        and values["writable_root"] == "1"
        and values["writable_restart"] == "1"
        and values["symlink"] == "1"
        and disk >= 1024
    )
    if not ok:
        raise RuntimeError("cible PlanetHoster legacy non prête")
    return {
        "pythonPath": values["python_path"],
        "passengerAdapter": True,
        "writableRoot": True,
        "writableRestart": True,
        "symlink": True,
        "freeDiskMb": disk,
    }


def deploy(sha: str, key: str, known_hosts: str) -> dict:
    if not _SHA.fullmatch(sha):
        raise ValueError("SHA invalide")
    target = deployment_center.validate_target(TARGET)
    credential = deployment_transport.SSHCredential(identity_file=key)
    capabilities = _legacy_capability_probe(target, known_hosts, credential)

    state = deployment_update.update_status(
        target, known_hosts, credential, sha, ROOT, timeout=30
    )
    if state.get("state") == "up_to_date":
        return {"ok": True, "state": "already_current", "sha": sha}
    if state.get("state") != "update_available":
        raise RuntimeError("mise à jour refusée: " + str(state.get("state") or "unknown"))

    # stage_release calls the generic readiness gate, whose shell-PATH Passenger
    # assumptions do not describe this already-running N0C legacy adapter.
    # Build and stage the exact bundle using the verified legacy capability boundary.
    bundle = deployment_release.build_release_bundle(ROOT, sha)
    stage_script = deployment_release.remote_stage_script(target, bundle)
    args = deployment_transport.ssh_arguments(target, known_hosts, credential)
    staged_run = subprocess.run(
        [*args, "sh", "-s"],
        input=stage_script,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    if staged_run.returncode != 0:
        raise RuntimeError("staging distant de la release impossible")
    staged = deployment_release._parse_stage_output(staged_run.stdout, bundle)
    if staged.sha != sha:
        raise RuntimeError("release staged incohérente")

    args = deployment_transport.ssh_arguments(target, known_hosts, credential)
    result = subprocess.run(
        [*args, "/opt/alt/python312/bin/python3", "-"],
        input=_activation_program(sha),
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("activation legacy échouée")
    return _parse_result(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Déploiement atomique de test.checkupauto.fr en conservant l'adaptateur Passenger historique.")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--known-hosts", required=True)
    args = parser.parse_args()
    try:
        result = deploy(args.sha, args.identity_file, args.known_hosts)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
