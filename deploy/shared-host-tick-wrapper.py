from __future__ import annotations

from pathlib import Path
import os
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "current"
PRIVATE = ROOT / "shared" / "private"
_ENV_KEY = re.compile(r"^CYBERCHECK_[A-Z0-9_]+$")


def _load_runtime_env() -> None:
    path = PRIVATE / "runtime.env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if _ENV_KEY.fullmatch(key):
            os.environ.setdefault(key, value.strip())


def main() -> None:
    shared = ROOT / "shared"
    os.environ.setdefault("CYBERCHECK_DATA_DIR", str(shared / "data"))
    os.environ.setdefault("CYBERCHECK_PRIVATE_DIR", str(shared / "private"))
    os.environ.setdefault("CYBERCHECK_SECURITY_DIR", str(shared / "security"))
    os.environ.setdefault("CYBERCHECK_INTEGRITY_DIR", str(shared / "integrity"))
    os.environ.setdefault(
        "CYBERCHECK_GSC_CREDENTIALS_PATH",
        str(shared / "private" / "gsc-service-account.json"),
    )
    os.environ.setdefault(
        "CYBERCHECK_SITE_CONFIG_PATH",
        str(shared / "data" / "site-config.json"),
    )
    _load_runtime_env()
    if not CURRENT.is_dir():
        raise RuntimeError("release CheckupAuto active introuvable")
    os.chdir(CURRENT)
    sys.path.insert(0, str(CURRENT))
    runpy.run_path(
        str(CURRENT / "scripts" / "checkupauto-shared-tick.py"),
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
