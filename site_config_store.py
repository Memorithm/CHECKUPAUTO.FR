from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "data" / "site-config.json"
DEFAULT_RUNTIME_CONFIG = Path("/root/CyberCheckData/site-config.json")


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


def save(config: dict, *, runtime_path: Path | None = None) -> Path:
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
