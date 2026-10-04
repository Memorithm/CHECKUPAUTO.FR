from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import json
import os
import tempfile


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "data" / "site-config.json"
DEFAULT_RUNTIME_CONFIG = Path("/root/CyberCheckData/site-config.json")
_CANONICAL_HOST = "www.checkupauto.fr"


def runtime_config_path() -> Path:
    raw = str(os.environ.get("CYBERCHECK_SITE_CONFIG_PATH") or "").strip()
    if raw:
        return Path(raw)
    data_dir = str(os.environ.get("CYBERCHECK_DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir) / "site-config.json"
    return DEFAULT_RUNTIME_CONFIG


def load(*, runtime_path: Path | None = None, default_path: Path | None = None) -> dict:
    runtime = Path(runtime_path) if runtime_path is not None else runtime_config_path()
    default = Path(default_path) if default_path is not None else DEFAULT_CONFIG
    source = runtime if runtime.is_file() else default
    return json.loads(source.read_text())


def _validate_public_canonical(config: dict) -> None:
    if not isinstance(config, dict):
        raise ValueError("site config must be an object")
    seo = config.get("seo")
    if not isinstance(seo, dict) or "canonicalUrl" not in seo:
        return
    raw = str(seo.get("canonicalUrl") or "").strip()
    try:
        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("seo.canonicalUrl invalid") from exc
    if (
        parsed.scheme != "https"
        or hostname != _CANONICAL_HOST
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("seo.canonicalUrl must use the CheckupAuto production origin")


def _validate_booking_mode(config: dict) -> None:
    if not isinstance(config, dict):
        raise ValueError("site config must be an object")
    business=config.get("business")
    if not isinstance(business,dict):
        return
    mode=str(business.get("bookingMode") or "payline").strip().lower()
    if mode not in {"payline","mercureweb-delegated"}:
        raise ValueError("business.bookingMode invalid")
    if mode!="mercureweb-delegated":
        return
    raw=str(business.get("bookingUrl") or "").strip()
    try:
        parsed=urlparse(raw)
        valid=(
            parsed.scheme=="https"
            and (parsed.hostname or "").lower()=="rdv.checkupauto.fr"
            and parsed.port in (None,443)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.path in ("","/")
        )
    except (TypeError,ValueError):
        valid=False
    if not valid:
        raise ValueError("delegated MercureWeb bookingUrl invalid")


def save(config: dict, *, runtime_path: Path | None = None) -> Path:
    _validate_public_canonical(config)
    _validate_booking_mode(config)
    target = Path(runtime_path) if runtime_path is not None else runtime_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="site-config.", suffix=".json", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, target)
        try:
            target.chmod(0o640)
        except PermissionError:
            pass
        return target
    finally:
        if tmp.exists():
            tmp.unlink()
