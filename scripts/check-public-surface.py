#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import public_surface_provenance


def main(argv: list[str]) -> int:
    canonical_url = argv[1] if len(argv) > 1 else "https://www.checkupauto.fr/"
    result = public_surface_provenance.probe(canonical_url)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
