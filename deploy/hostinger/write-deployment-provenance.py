#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import os
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import public_surface_provenance


def write(root: Path, approved_sha: str) -> Path:
    root = Path(root).resolve()
    expected_root = ROOT.resolve()
    if root != expected_root:
        raise ValueError("release root mismatch")

    evidence = public_surface_provenance.deployment_artifact_evidence(approved_sha)
    if evidence.get("verified") is not True:
        raise ValueError("invalid approved sha")

    target = root / public_surface_provenance.DEPLOYMENT_ARTIFACT_PATH.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > 4096:
        raise ValueError("provenance payload too large")

    fd, temp_name = tempfile.mkstemp(prefix=".deployment-provenance.", dir=str(target.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o644)
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return 64
    try:
        target = write(Path(argv[1]), argv[2])
    except (OSError, ValueError):
        return 65
    print(f"HOSTINGER_DEPLOYMENT_PROVENANCE_WRITTEN={target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
