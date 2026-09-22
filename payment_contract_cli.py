"""Import a private acquiring-sheet JSON without writing its values to logs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

from payment_contract_store import ContractStore, MAX_BYTES, parse_json, validate_import


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--revision", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        # The import is intentionally a separate private file, never source data.
        if args.file.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise ValueError
        fd = os.open(args.file, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
                raise ValueError
            fields = validate_import(parse_json(handle.read(MAX_BYTES + 1)))
        result = ContractStore(args.store).update({"revision": args.revision, "mode": "import_missing", "fields": fields})
        print(json.dumps({"ok": True, "revision": result["revision"], "changedFields": result["changedFields"],
                          "livePaymentsEnabled": False}))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "error": "private_contract_import_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
