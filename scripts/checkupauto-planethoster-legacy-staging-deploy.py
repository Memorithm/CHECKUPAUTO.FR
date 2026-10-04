#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
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
_ACTIVATION_STEP_PREFIX = "CHECKUPAUTO_ACTIVATION_STEP="


def _activation_program(sha: str) -> str:
    if not _SHA.fullmatch(sha):
        raise ValueError("SHA invalide")
    return r'''from __future__ import annotations
import datetime
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

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
origin_ip = "185.221.181.53"


def fail(message):
    raise RuntimeError(message)


def under(path, parent):
    return path == parent or parent in path.parents


def origin_get(path, *, limit):
    if not str(path).startswith("/"):
        fail("invalid verification path")
    context = ssl.create_default_context()
    raw = socket.create_connection((origin_ip, 443), timeout=10)
    tls = context.wrap_socket(raw, server_hostname=domain)
    try:
        request_bytes = (
            "GET " + path + " HTTP/1.1\r\n"
            "Host: " + domain + "\r\n"
            "User-Agent: CheckupAuto-DeployVerify/1\r\n"
            "Accept: text/html,application/json\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        tls.sendall(request_bytes)
        response = http.client.HTTPResponse(tls)
        response.begin()
        body = response.read(limit + 1)
        if len(body) > limit:
            fail("verification response too large")
        return int(response.status), body
    finally:
        tls.close()


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
print("__ACTIVATION_STEP_PREFIX__preflight", flush=True)
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

print("__ACTIVATION_STEP_PREFIX__backup", flush=True)
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

print("__ACTIVATION_STEP_PREFIX__import", flush=True)
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
    print("__ACTIVATION_STEP_PREFIX__switch", flush=True)
    os.replace(incoming, current)
    switched = True
    print("__ACTIVATION_STEP_PREFIX__restart", flush=True)
    touch_restart()

    print("__ACTIVATION_STEP_PREFIX__http_verify", flush=True)
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
            status, _status_body = origin_get("/api/app/status", limit=200000)
            if status != 200:
                fail("app status invalid")
            for path, version in legal.items():
                status, raw_body = origin_get(path, limit=300000)
                if status != 200:
                    fail("legal page status invalid")
                body = raw_body.decode("utf-8", errors="strict")
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

    print("__ACTIVATION_STEP_PREFIX__compliance", flush=True)
    compliance_code = r"""
import json
import compliance_admin
summary=(compliance_admin.snapshot().get("summary") or {})
out={
    "phase2CoverageReady":bool(summary.get("phase2CoverageReady")),
    "readyForPublicContracting":bool(summary.get("readyForPublicContracting")),
    "phase2Blockers":[str(x) for x in summary.get("phase2Blockers") or []],
    "operationalBlockerTypes":[
        str(row.get("type") or "")
        for row in summary.get("operationalBlockers") or []
        if isinstance(row,dict)
    ],
}
print(json.dumps(out,sort_keys=True,separators=(",",":")))
"""
    compliance_probe = subprocess.run(
        [str(release / ".venv/bin/python"), "-c", compliance_code],
        cwd=release,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )
    if compliance_probe.returncode != 0:
        fail("compliance snapshot failed")
    try:
        summary = json.loads(compliance_probe.stdout.strip())
    except Exception:
        fail("compliance snapshot invalid")
    if set(summary) != {
        "phase2CoverageReady",
        "readyForPublicContracting",
        "phase2Blockers",
        "operationalBlockerTypes",
    }:
        fail("compliance snapshot schema invalid")

    print(__PREFIX__ + json.dumps({
        "ok": True,
        "state": "activated",
        "sha": SHA,
        "previousSha": previous_sha,
        "legalPages": observed,
        "phase2CoverageReady": bool(summary.get("phase2CoverageReady")),
        "readyForPublicContracting": bool(summary.get("readyForPublicContracting")),
        "phase2Blockers": list(summary.get("phase2Blockers") or []),
        "operationalBlockerTypes": list(summary.get("operationalBlockerTypes") or []),
    }, sort_keys=True, separators=(",", ":")))
except Exception:
    if switched:
        print("__ACTIVATION_STEP_PREFIX__rollback", flush=True)
        rollback = private / (".rollback-" + str(os.getpid()))
        try:
            rollback.unlink()
        except FileNotFoundError:
            pass
        os.symlink(previous, rollback)
        os.replace(rollback, current)
        touch_restart()
    raise
'''.replace("__SHA__", repr(sha)).replace("__PREFIX__", repr(_RESULT_PREFIX)).replace("__ACTIVATION_STEP_PREFIX__", _ACTIVATION_STEP_PREFIX)


def _qualify_n0c_legacy_runtime(target, known_hosts: str, credential, capabilities, *, timeout: int = 30):
    args = deployment_transport.ssh_arguments(target, known_hosts, credential)
    script = r'''set -eu
py=/opt/alt/python312/bin/python3
adapter="$HOME/checkupauto-test-application/passenger_wsgi.py"
test -x "$py"
test -f "$adapter"
"$py" --version
printf 'passenger_adapter=1\n'
'''
    result = subprocess.run(
        [*args, "sh", "-s"],
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("runtime N0C historique non vérifiable")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    python_line = next((line for line in lines if line.startswith("Python ")), "")
    adapter_ok = "passenger_adapter=1" in lines
    if not python_line or not adapter_ok:
        raise RuntimeError("runtime N0C historique incomplet")
    return replace(capabilities, python_version=python_line, passenger=True)


def _last_activation_step(output: str) -> str:
    allowed = {
        "preflight", "backup", "import", "switch", "restart",
        "http_verify", "compliance", "rollback",
    }
    last = ""
    for line in str(output or "").splitlines():
        if line.startswith(_ACTIVATION_STEP_PREFIX):
            candidate = line[len(_ACTIVATION_STEP_PREFIX):].strip()
            if candidate in allowed and candidate != "rollback":
                last = candidate
    return last or "unknown"


def _parse_result(stdout: str) -> dict:
    for line in str(stdout or "").splitlines():
        if line.startswith(_RESULT_PREFIX):
            payload = json.loads(line[len(_RESULT_PREFIX):])
            if isinstance(payload, dict) and payload.get("ok") is True:
                return payload
    raise RuntimeError("réponse activation legacy invalide")


def deploy(sha: str, key: str, known_hosts: str) -> dict:
    if not _SHA.fullmatch(sha):
        raise ValueError("SHA invalide")
    target = deployment_center.validate_target(TARGET)
    credential = deployment_transport.SSHCredential(identity_file=key)
    capabilities = deployment_transport.probe_target(
        target,
        known_hosts,
        credential,
        passenger_wsgi_adapter=(ROOT / "passenger_wsgi.py").is_file(),
        shared_host_tick=(ROOT / "scripts/checkupauto-shared-tick.py").is_file(),
        timeout=30,
    )
    if target.provider == "planethoster-n0c":
        capabilities = _qualify_n0c_legacy_runtime(
            target, known_hosts, credential, capabilities, timeout=30
        )
    readiness = deployment_center.assess(target, capabilities)
    if not readiness.get("ok"):
        raise RuntimeError("cible PlanetHoster non prête: " + ",".join(readiness.get("blockers") or []))

    state = deployment_update.update_status(
        target, known_hosts, credential, sha, ROOT, timeout=30
    )
    if state.get("state") == "up_to_date":
        return {"ok": True, "state": "already_current", "sha": sha}
    if state.get("state") != "update_available":
        raise RuntimeError("mise à jour refusée: " + str(state.get("state") or "unknown"))

    staged = deployment_release.stage_release(
        target, capabilities, known_hosts, credential, ROOT, sha, timeout=900
    )
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
        raise RuntimeError(
            "activation legacy échouée:" + _last_activation_step(result.stdout)
        )
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
