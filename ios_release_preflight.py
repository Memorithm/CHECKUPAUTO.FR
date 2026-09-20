from __future__ import annotations

import json
import plistlib
import re
from pathlib import Path
import xml.etree.ElementTree as ET

import qrcode

import app_download
import mobile_claim_delivery

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "ios" / "CheckupAutoReminder" / "project.yml"
ENTITLEMENTS = ROOT / "ios" / "CheckupAutoReminder" / "CheckupAutoReminder.entitlements"
RELEASE_RUNNER = ROOT / "ios_release_runner.py"
QR_SITE = ROOT / "assets" / "app" / "qr-site.svg"
QR_CENTRE = ROOT / "assets" / "app" / "qr-centre.svg"
CENTRE_POSTER = ROOT / "assets" / "app" / "centre-poster.svg"
QR_TARGETS = {
    QR_SITE: "https://www.checkupauto.fr/app?src=qr-site",
    QR_CENTRE: "https://www.checkupauto.fr/app?src=qr-centre",
}
EXPECTED_BUNDLE_ID = mobile_claim_delivery.BUNDLE_ID
EXPECTED_ASSOCIATED_DOMAIN = "applinks:www.checkupauto.fr"
EXPECTED_LANDING_URL = "https://www.checkupauto.fr/app"


def _check(code: str, ok: bool, detail: str) -> dict:
    return {"code": code, "ok": bool(ok), "detail": str(detail)}


def _manifest_checks(text: str) -> list[dict]:
    bundle_match = re.search(r"^\s*PRODUCT_BUNDLE_IDENTIFIER:\s*([^\s#]+)\s*$", text, re.M)
    bundle_id = bundle_match.group(1) if bundle_match else ""
    release_push = bool(re.search(
        r"^\s{4}Release:\s*\n(?:^\s{6,}.*\n)*?^\s{6,}APS_ENVIRONMENT:\s*production\s*$",
        text,
        re.M,
    ))
    entitlement_match = re.search(r"^\s*CODE_SIGN_ENTITLEMENTS:\s*([^\s#]+)\s*$", text, re.M)
    entitlement_path = entitlement_match.group(1) if entitlement_match else ""
    release_configured = bool(re.search(r"^\s{2}Release:\s*release\s*$", text, re.M))
    return [
        _check("bundle_identifier", bundle_id == EXPECTED_BUNDLE_ID, bundle_id or "missing"),
        _check("release_configuration", release_configured, "Release=release" if release_configured else "missing"),
        _check("release_apns_environment", release_push, "production" if release_push else "missing_or_invalid"),
        _check(
            "code_sign_entitlements",
            entitlement_path == "CheckupAutoReminder.entitlements",
            entitlement_path or "missing",
        ),
    ]


def _entitlement_checks(payload: bytes) -> list[dict]:
    try:
        entitlements = plistlib.loads(payload)
    except Exception:
        return [
            _check("aps_entitlement", False, "invalid_plist"),
            _check("associated_domains", False, "invalid_plist"),
        ]
    aps = str(entitlements.get("aps-environment") or "")
    domains = entitlements.get("com.apple.developer.associated-domains") or []
    domains = [str(item) for item in domains if isinstance(item, str)]
    return [
        _check("aps_entitlement", aps == "$(APS_ENVIRONMENT)", aps or "missing"),
        _check(
            "associated_domains",
            domains == [EXPECTED_ASSOCIATED_DOMAIN],
            ",".join(domains) if domains else "missing",
        ),
    ]


def _expected_qr_modules(url: str) -> tuple[int, set[tuple[int, int]]]:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    modules = {(x, y) for y, row in enumerate(matrix) for x, value in enumerate(row) if value}
    return len(matrix), modules


def _svg_modules(path: Path) -> tuple[tuple[int, int] | None, set[tuple[int, int]]]:
    text = path.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    if not root.tag.endswith("svg"):
        raise ValueError("not_svg")
    view_box = str(root.attrib.get("viewBox") or "").split()
    dimensions = None
    if len(view_box) == 4 and view_box[:2] == ["0", "0"]:
        try:
            dimensions = (int(float(view_box[2])), int(float(view_box[3])))
        except ValueError:
            dimensions = None
    modules: set[tuple[int, int]] = set()
    for element in root.iter():
        if not element.tag.endswith("path"):
            continue
        data = str(element.attrib.get("d") or "")
        modules.update((int(x), int(y)) for x, y in re.findall(r"M(\d+),(\d+)H\d+V\d+H\d+z", data))
    return dimensions, modules


def _qr_asset_ok(path: Path, url: str) -> bool:
    try:
        expected_size, expected_modules = _expected_qr_modules(url)
        dimensions, modules = _svg_modules(path)
    except (OSError, ValueError, ET.ParseError):
        return False
    return dimensions == (expected_size, expected_size) and modules == expected_modules


def _poster_ok(path: Path, qr_url: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
        ET.fromstring(text)
        _, modules = _svg_modules(path)
        _, expected_modules = _expected_qr_modules(qr_url)
    except (OSError, ValueError, ET.ParseError):
        return False
    return modules == expected_modules and "checkupauto.fr/app" in text


def _asset_checks() -> list[dict]:
    checks = [
        _check(
            f"asset_{path.stem}",
            _qr_asset_ok(path, url),
            path.name,
        )
        for path, url in QR_TARGETS.items()
    ]
    checks.append(_check(
        "asset_centre-poster",
        _poster_ok(CENTRE_POSTER, QR_TARGETS[QR_CENTRE]),
        CENTRE_POSTER.name,
    ))
    return checks


def _release_automation_check() -> dict:
    try:
        text = RELEASE_RUNNER.read_text(encoding="utf-8")
    except OSError:
        return _check("release_automation", False, "runner_unavailable")
    required = (
        'choices=("preflight", "test", "archive", "export")',
        'release_guard(require_main=True)',
        'validate_signed_entitlements(entitlements)',
        'upload_requires_explicit_allow_upload',
    )
    ok = all(token in text for token in required)
    return _check("release_automation", ok, RELEASE_RUNNER.name if ok else "runner_incomplete")


def _association_check(config: dict) -> tuple[dict, dict]:
    state = mobile_claim_delivery.status(config)
    if not state.get("ready"):
        return _check("aasa", False, "apple_identifier_prefix_required"), state
    try:
        document = mobile_claim_delivery.association_document(config)
        parsed = json.loads(document)
        details = ((parsed.get("applinks") or {}).get("details") or [])
        app_ids = details[0].get("appIDs") if details else []
        components = details[0].get("components") if details else []
        ok = (
            state.get("appIdentifier") in (app_ids or [])
            and any(item.get("/") == mobile_claim_delivery.CLAIM_PATH for item in (components or []))
        )
    except Exception:
        ok = False
    return _check("aasa", ok, state.get("appIdentifier") or "not_ready"), state


def status(config: dict) -> dict:
    checks: list[dict] = []
    try:
        checks.extend(_manifest_checks(PROJECT.read_text(encoding="utf-8")))
    except OSError:
        checks.extend([
            _check("bundle_identifier", False, "project_manifest_unavailable"),
            _check("release_configuration", False, "project_manifest_unavailable"),
            _check("release_apns_environment", False, "project_manifest_unavailable"),
            _check("code_sign_entitlements", False, "project_manifest_unavailable"),
        ])
    try:
        checks.extend(_entitlement_checks(ENTITLEMENTS.read_bytes()))
    except OSError:
        checks.extend([
            _check("aps_entitlement", False, "entitlements_unavailable"),
            _check("associated_domains", False, "entitlements_unavailable"),
        ])
    checks.extend(_asset_checks())
    checks.append(_release_automation_check())

    distribution = app_download.status(config)
    ios = distribution.get("ios") or {}
    landing_ok = distribution.get("landingUrl") == EXPECTED_LANDING_URL and ios.get("downloadPath") == "/go/app"
    checks.append(_check("distribution_landing", landing_ok, distribution.get("landingUrl") or "missing"))

    aasa_check, claim = _association_check(config)
    checks.append(aasa_check)

    project_ready = all(item["ok"] for item in checks if item["code"] != "aasa")
    association_ready = bool(aasa_check["ok"])
    publication_ready = bool(ios.get("available") and ios.get("targetUrl"))
    if not project_ready:
        state = "degraded"
    elif not association_ready:
        state = "configuration_required"
    elif not publication_ready:
        state = "blocked_external"
    else:
        state = "ready"
    return {
        "ready": state == "ready",
        "state": state,
        "projectReady": project_ready,
        "associationReady": association_ready,
        "publicationReady": publication_ready,
        "bundleId": EXPECTED_BUNDLE_ID,
        "channel": ios.get("channel") or "pending",
        "landingUrl": distribution.get("landingUrl"),
        "claimPath": claim.get("claimPath"),
        "appIdentifier": claim.get("appIdentifier"),
        "checks": checks,
    }
