from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS_SOURCE = ROOT / "ios" / "CheckupAutoReminder"
PROJECT_NAME = "CheckupAutoReminder"
SCHEME = PROJECT_NAME
EXPECTED_BUNDLE_ID = "fr.checkupauto.reminder"
EXPECTED_ASSOCIATED_DOMAIN = "applinks:www.checkupauto.fr"


class ReleaseError(RuntimeError):
    pass


def _run(cmd: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if proc.returncode:
        detail = (proc.stdout or "").strip() if capture else ""
        raise ReleaseError(f"command_failed:{cmd[0]}:{proc.returncode}:{detail[-1200:]}")
    return (proc.stdout or "") if capture else ""


def _git(args: list[str]) -> str:
    return _run(["git", *args], cwd=ROOT, capture=True).strip()


def release_guard(*, require_main: bool = True) -> dict:
    if _git(["status", "--porcelain"]):
        raise ReleaseError("git_tree_not_clean")
    branch = _git(["branch", "--show-current"])
    head = _git(["rev-parse", "HEAD"])
    pinned = os.environ.get("CHECKUPAUTO_RELEASE_PINNED_SHA", "").strip().lower()
    if pinned:
        if not re.fullmatch(r"[0-9a-f]{40}", pinned):
            raise ReleaseError("release_pinned_sha_invalid")
        remote = _git(["rev-parse", "origin/main"])
        if head != pinned or remote != pinned:
            raise ReleaseError(f"release_pinned_sha_mismatch:{head}:{remote}:{pinned}")
    else:
        _git(["fetch", "origin", "main"])
        remote = _git(["rev-parse", "origin/main"])
    if require_main and branch != "main":
        raise ReleaseError(f"release_requires_main:{branch or 'detached'}")
    if head != remote:
        raise ReleaseError(f"release_head_not_origin_main:{head}:{remote}")
    return {"branch": branch, "head": head, "originMain": remote}


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ReleaseError(f"missing_tool:{name}")
    return path


def mac_toolchain_status() -> dict:
    return {
        "platform": sys.platform,
        "xcodegen": shutil.which("xcodegen"),
        "xcodebuild": shutil.which("xcodebuild"),
        "xcrun": shutil.which("xcrun"),
        "codesign": shutil.which("codesign"),
    }


def _runtime_version(runtime: str) -> tuple[int, ...]:
    match = re.search(r"iOS[- ](\d+(?:[-.]\d+)*)", runtime)
    if not match:
        return ()
    return tuple(int(part) for part in re.split(r"[-.]", match.group(1)))


def select_simulator(payload: dict) -> dict:
    candidates: list[tuple[tuple[int, ...], str, str, str]] = []
    for runtime, devices in (payload.get("devices") or {}).items():
        version = _runtime_version(str(runtime))
        for device in devices or []:
            name = str(device.get("name") or "")
            udid = str(device.get("udid") or "")
            available = device.get("isAvailable", True)
            if available and udid and name.startswith("iPhone"):
                candidates.append((version, name, udid, str(runtime)))
    if not candidates:
        raise ReleaseError("no_available_iphone_simulator")
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    version, name, udid, runtime = candidates[0]
    return {
        "name": name,
        "udid": udid,
        "runtime": runtime,
        "destination": f"platform=iOS Simulator,id={udid}",
        "runtimeVersion": ".".join(str(x) for x in version),
    }


def discover_simulator() -> dict:
    raw = _run([_require_tool("xcrun"), "simctl", "list", "devices", "available", "--json"], capture=True)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseError("invalid_simctl_json") from exc
    return select_simulator(payload)


def parse_build_settings(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def validate_release_settings(settings: dict[str, str]) -> None:
    expected = {
        "PRODUCT_BUNDLE_IDENTIFIER": EXPECTED_BUNDLE_ID,
        "APS_ENVIRONMENT": "production",
        "CODE_SIGN_STYLE": "Automatic",
    }
    for key, value in expected.items():
        if settings.get(key) != value:
            raise ReleaseError(f"invalid_build_setting:{key}:{settings.get(key, 'missing')}")
    entitlements = settings.get("CODE_SIGN_ENTITLEMENTS", "")
    if not entitlements.endswith("CheckupAutoReminder.entitlements"):
        raise ReleaseError(f"invalid_build_setting:CODE_SIGN_ENTITLEMENTS:{entitlements or 'missing'}")


def validate_signed_entitlements(entitlements: dict) -> None:
    aps = entitlements.get("aps-environment")
    if aps != "production":
        raise ReleaseError(f"invalid_signed_entitlement:aps-environment:{aps or 'missing'}")
    domains = entitlements.get("com.apple.developer.associated-domains") or []
    if EXPECTED_ASSOCIATED_DOMAIN not in domains:
        raise ReleaseError("invalid_signed_entitlement:associated-domains")
    app_identifier = str(entitlements.get("application-identifier") or "")
    if not app_identifier.endswith("." + EXPECTED_BUNDLE_ID):
        raise ReleaseError("invalid_signed_entitlement:application-identifier")


def _stage_project(root: Path) -> Path:
    staged = root / PROJECT_NAME
    shutil.copytree(
        IOS_SOURCE,
        staged,
        ignore=shutil.ignore_patterns("*.xcodeproj", "DerivedData", ".build", "build"),
    )
    return staged


def _show_release_settings(project_dir: Path) -> dict[str, str]:
    output = _run([
        _require_tool("xcodebuild"),
        "-project", str(project_dir / f"{PROJECT_NAME}.xcodeproj"),
        "-target", PROJECT_NAME,
        "-configuration", "Release",
        "-showBuildSettings",
    ], capture=True)
    settings = parse_build_settings(output)
    validate_release_settings(settings)
    return settings


def _archive_app(archive_path: Path) -> Path:
    info_path = archive_path / "Info.plist"
    try:
        info = plistlib.loads(info_path.read_bytes())
    except Exception as exc:
        raise ReleaseError("archive_info_unreadable") from exc
    relative = ((info.get("ApplicationProperties") or {}).get("ApplicationPath") or "")
    app_path = archive_path / "Products" / str(relative)
    if not relative or not app_path.is_dir():
        raise ReleaseError("archive_application_missing")
    app_info = app_path / "Info.plist"
    try:
        payload = plistlib.loads(app_info.read_bytes())
    except Exception as exc:
        raise ReleaseError("archive_app_info_unreadable") from exc
    if payload.get("CFBundleIdentifier") != EXPECTED_BUNDLE_ID:
        raise ReleaseError(f"archive_bundle_mismatch:{payload.get('CFBundleIdentifier') or 'missing'}")
    return app_path


def _signed_entitlements(app_path: Path) -> dict:
    output = _run([_require_tool("codesign"), "-d", "--entitlements", ":-", str(app_path)], capture=True)
    start = output.find("<?xml")
    if start < 0:
        raise ReleaseError("signed_entitlements_missing")
    try:
        return plistlib.loads(output[start:].encode("utf-8"))
    except Exception as exc:
        raise ReleaseError("signed_entitlements_invalid") from exc




def app_store_connect_auth_args(*, required: bool = False) -> list[str]:
    key_id = os.environ.get("CHECKUPAUTO_ASC_KEY_ID", "").strip()
    issuer_id = os.environ.get("CHECKUPAUTO_ASC_ISSUER_ID", "").strip()
    key_path_raw = os.environ.get("CHECKUPAUTO_ASC_KEY_PATH", "").strip()
    present = bool(key_id or issuer_id or key_path_raw)
    if not present and not required:
        return []
    if not re.fullmatch(r"[A-Za-z0-9]{10}", key_id):
        raise ReleaseError("app_store_connect_key_id_required")
    if not re.fullmatch(r"[0-9A-Fa-f-]{36}", issuer_id):
        raise ReleaseError("app_store_connect_issuer_id_required")
    key_path = Path(key_path_raw)
    if not key_path.is_file():
        raise ReleaseError("app_store_connect_key_file_required")
    return [
        "-authenticationKeyPath", str(key_path),
        "-authenticationKeyID", key_id,
        "-authenticationKeyIssuerID", issuer_id,
        "-allowProvisioningUpdates",
    ]


def _testflight_export_options(team_id: str, output_root: Path) -> Path:
    path = output_root / "ExportOptions-TestFlight.plist"
    payload = {
        "method": "app-store-connect",
        "destination": "upload",
        "signingStyle": "automatic",
        "teamID": team_id,
        "uploadSymbols": True,
    }
    path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
    return path


def run_release(*, stage: str, export_options: Path | None = None, allow_upload: bool = False) -> dict:
    if sys.platform != "darwin":
        raise ReleaseError(f"macos_required:{sys.platform}")
    guard = release_guard(require_main=True)
    for tool in ("xcodegen", "xcodebuild", "xcrun"):
        _require_tool(tool)
    output_root = Path.home() / "Library" / "Developer" / "CheckupAutoRelease" / guard["head"]
    output_root.mkdir(parents=True, exist_ok=True)
    result: dict = {"git": guard, "outputRoot": str(output_root), "stage": stage}
    with tempfile.TemporaryDirectory(prefix="checkupauto-ios-release-") as temp:
        project_dir = _stage_project(Path(temp))
        _run([_require_tool("xcodegen"), "generate"], cwd=project_dir)
        result["settings"] = _show_release_settings(project_dir)
        if stage == "preflight":
            return result
        simulator = discover_simulator()
        result["simulator"] = simulator
        _run([
            _require_tool("xcodebuild"), "test",
            "-project", str(project_dir / f"{PROJECT_NAME}.xcodeproj"),
            "-scheme", SCHEME,
            "-configuration", "Debug",
            "-destination", simulator["destination"],
            "CODE_SIGNING_ALLOWED=NO",
        ])
        if stage == "test":
            return result
        team_id = os.environ.get("CHECKUPAUTO_APPLE_TEAM_ID", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{10}", team_id):
            raise ReleaseError("apple_team_id_required")
        archive_path = output_root / f"{PROJECT_NAME}.xcarchive"
        if archive_path.exists():
            shutil.rmtree(archive_path)
        auth_args = app_store_connect_auth_args(required=stage == "testflight")
        build_number = os.environ.get("CHECKUPAUTO_BUILD_NUMBER", "").strip()
        if build_number and not re.fullmatch(r"[0-9]{1,18}", build_number):
            raise ReleaseError("build_number_invalid")
        if stage == "testflight" and not build_number:
            raise ReleaseError("build_number_required")
        if build_number:
            result["buildNumber"] = build_number
        archive_cmd = [
            _require_tool("xcodebuild"), "archive",
            "-project", str(project_dir / f"{PROJECT_NAME}.xcodeproj"),
            "-scheme", SCHEME,
            "-configuration", "Release",
            "-destination", "generic/platform=iOS",
            "-archivePath", str(archive_path),
            f"DEVELOPMENT_TEAM={team_id}",
        ]
        if build_number:
            archive_cmd.append(f"CURRENT_PROJECT_VERSION={build_number}")
        if auth_args:
            archive_cmd.extend(auth_args)
        elif os.environ.get("CHECKUPAUTO_ALLOW_PROVISIONING_UPDATES") == "1":
            archive_cmd.append("-allowProvisioningUpdates")
        _run(archive_cmd)
        app_path = _archive_app(archive_path)
        entitlements = _signed_entitlements(app_path)
        validate_signed_entitlements(entitlements)
        result["archivePath"] = str(archive_path)
        result["signedApp"] = str(app_path)
        if stage == "archive":
            return result
        if stage == "testflight":
            if not allow_upload:
                raise ReleaseError("upload_requires_explicit_allow_upload")
            export_options = _testflight_export_options(team_id, output_root)
        if export_options is None or not export_options.is_file():
            raise ReleaseError("export_options_plist_required")
        options = plistlib.loads(export_options.read_bytes())
        destination = str(options.get("destination") or "export")
        if destination == "upload" and not allow_upload:
            raise ReleaseError("upload_requires_explicit_allow_upload")
        export_path = output_root / "export"
        shutil.rmtree(export_path, ignore_errors=True)
        export_path.mkdir(parents=True)
        export_cmd = [
            _require_tool("xcodebuild"), "-exportArchive",
            "-archivePath", str(archive_path),
            "-exportPath", str(export_path),
            "-exportOptionsPlist", str(export_options),
        ]
        if auth_args:
            export_cmd.extend(auth_args)
        _run(export_cmd)
        result["exportPath"] = str(export_path)
        result["exportDestination"] = destination
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CheckupAuto reproducible iOS release runner")
    parser.add_argument("stage", choices=("preflight", "test", "archive", "export", "testflight"))
    parser.add_argument("--export-options", type=Path)
    parser.add_argument("--allow-upload", action="store_true")
    parser.add_argument("--toolchain-status", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.toolchain_status:
            print(json.dumps(mac_toolchain_status(), indent=2))
            return 0
        result = run_release(
            stage=args.stage,
            export_options=args.export_options,
            allow_upload=args.allow_upload,
        )
    except (ReleaseError, OSError, plistlib.InvalidFileException) as exc:
        print(f"IOS_RELEASE_ERROR:{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
