#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from deployment_center import installation_plan, provider_profiles, validate_target
from deployment_executor import execute_deployment, execute_rollback
from deployment_transport import SSHCredential, probe_target
from deployment_vault import DeploymentVault


def _vault() -> DeploymentVault:
    root = os.environ.get(
        "CYBERCHECK_DEPLOYMENT_VAULT",
        "~/.config/checkupauto-deployer",
    )
    return DeploymentVault(Path(root).expanduser())


def _load_json(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("document JSON invalide")
    return payload


def _stored_target(record: dict):
    target = dict(record.get("target") or {})
    return validate_target({
        "provider": target.get("provider"),
        "host": target.get("host"),
        "port": target.get("port"),
        "username": target.get("username"),
        "domain": target.get("domain"),
        "rootPath": target.get("root_path") or target.get("rootPath"),
        "webRootPath": target.get("web_root_path") or target.get("webRootPath"),
        "authMode": target.get("auth_mode") or target.get("authMode"),
    })


def _stored_credential(record: dict, target) -> SSHCredential:
    raw = dict(record.get("credential") or {})
    if target.auth_mode == "key":
        return SSHCredential(identity_file=str(raw.get("identityFile") or ""))
    return SSHCredential(password=str(raw.get("password") or ""))


def _stored_context(name: str):
    record = _vault().load(name)
    target = _stored_target(record)
    credential = _stored_credential(record, target)
    return target, credential


def _adapter_available() -> bool:
    return (
        (ROOT / "passenger_wsgi.py").is_file()
        or (ROOT / "deploy" / "passenger_wsgi.py").is_file()
    )


def _shared_tick_available() -> bool:
    return (ROOT / "scripts" / "checkupauto-shared-tick.py").is_file()


def cmd_profiles(_args) -> int:
    print(json.dumps(provider_profiles(), ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args) -> int:
    target = validate_target(_load_json(args.target))
    print(json.dumps(target.public_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_save(args) -> int:
    target = validate_target(_load_json(args.target))
    vault = _vault()
    if target.auth_mode == "key":
        if not args.identity_file:
            raise ValueError("--identity-file requis pour authMode=key")
        vault.store(
            args.name,
            target,
            identity_file=args.identity_file,
        )
    else:
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("Mot de passe SSH: ")
        vault.store(args.name, target, password=password)
    print(json.dumps({
        "ok": True,
        "name": args.name,
        "target": target.public_dict(),
        "credentialStored": True,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_list(_args) -> int:
    print(json.dumps(_vault().summaries(), ensure_ascii=False, indent=2))
    return 0


def _probe(name: str, known_hosts: str):
    target, credential = _stored_context(name)
    capabilities = probe_target(
        target,
        known_hosts,
        credential,
        passenger_wsgi_adapter=_adapter_available(),
        shared_host_tick=_shared_tick_available(),
    )
    return target, capabilities


def cmd_probe(args) -> int:
    target, capabilities = _probe(args.name, args.known_hosts)
    print(json.dumps({
        "ok": True,
        "target": target.public_dict(),
        "capabilities": {
            "pythonVersion": capabilities.python_version,
            "nodeVersion": capabilities.node_version,
            "passenger": capabilities.passenger,
            "systemd": capabilities.systemd,
            "cron": capabilities.cron,
            "symlink": capabilities.symlink,
            "writableRoot": capabilities.writable_root,
            "writableWebRoot": capabilities.writable_web_root,
            "freeDiskMb": capabilities.free_disk_mb,
            "passengerWsgiAdapter": capabilities.passenger_wsgi_adapter,
            "sharedHostTick": capabilities.shared_host_tick,
        },
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_plan(args) -> int:
    target, capabilities = _probe(args.name, args.known_hosts)
    plan = installation_plan(target, args.sha, capabilities)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["assessment"]["ok"] else 3


def _result_payload(result) -> dict:
    payload = {
        "ok": True,
        "action": result.action,
        "sha": result.sha,
        "previousSha": result.previous_sha,
        "staged": result.staged,
        "readiness": {
            "state": result.readiness_state,
            "activationAllowed": result.activation_allowed,
            "blockerCount": result.blocker_count,
        },
    }
    if result.staged:
        payload["release"] = {
            "archiveSha256": result.archive_sha256,
            "fileCount": result.file_count,
        }
    return payload


def _cmd_deploy(args, action: str) -> int:
    target, credential = _stored_context(args.name)
    result = execute_deployment(
        action,
        target,
        args.known_hosts,
        credential,
        ROOT,
        args.sha,
    )
    print(json.dumps(_result_payload(result), ensure_ascii=False, indent=2))
    return 0


def cmd_install(args) -> int:
    return _cmd_deploy(args, "install")


def cmd_update(args) -> int:
    return _cmd_deploy(args, "update")


def cmd_rollback(args) -> int:
    target, credential = _stored_context(args.name)
    result = execute_rollback(
        target,
        args.known_hosts,
        credential,
        ROOT,
        args.sha,
    )
    print(json.dumps(_result_payload(result), ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="CheckupAuto Deployment Center controller",
    )
    sub = root.add_subparsers(dest="command", required=True)

    profiles = sub.add_parser("profiles")
    profiles.set_defaults(func=cmd_profiles)

    validate = sub.add_parser("validate")
    validate.add_argument("--target", required=True)
    validate.set_defaults(func=cmd_validate)

    save = sub.add_parser("save")
    save.add_argument("--name", required=True)
    save.add_argument("--target", required=True)
    save.add_argument("--identity-file")
    save.add_argument("--password-stdin", action="store_true")
    save.set_defaults(func=cmd_save)

    listing = sub.add_parser("list")
    listing.set_defaults(func=cmd_list)

    for name, handler in (("probe", cmd_probe), ("plan", cmd_plan)):
        command = sub.add_parser(name)
        command.add_argument("--name", required=True)
        command.add_argument("--known-hosts", required=True)
        if name == "plan":
            command.add_argument("--sha", required=True)
        command.set_defaults(func=handler)

    for name, handler in (
        ("install", cmd_install),
        ("update", cmd_update),
        ("rollback", cmd_rollback),
    ):
        command = sub.add_parser(name)
        command.add_argument("--name", required=True)
        command.add_argument("--known-hosts", required=True)
        command.add_argument("--sha", required=True)
        command.set_defaults(func=handler)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except (ValueError, RuntimeError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "ok": False,
            "error": type(exc).__name__,
            "detail": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
