#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import compliance_operations as operations

EXPECTED_STATUS = "pending"
TARGET_STATUS = "reviewed_insufficient"
CONFIRMATION = "TRANSITION-PROCESSOR-DPA-REVIEW"


def _payload(row: dict, *, dpa_status: str) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "service": row["service"],
        "dpaStatus": dpa_status,
        "dpaEvidenceSha256": "",
        "hostingLocation": row["hostingLocation"],
        "transferRequired": bool(row["transferRequired"]),
        "transferMechanism": row["transferMechanism"],
        "subprocessors": list(row["subprocessors"]),
        "reviewDueAt": row["reviewDueAt"],
        "status": row["status"],
    }


def transition(processor_id: str, db_path: Path | str | None = None) -> dict:
    processor_id = str(processor_id or "").strip()
    if not processor_id:
        raise ValueError("processor id required")

    rows = {row["id"]: row for row in operations.processors(db_path)}
    current = rows.get(processor_id)
    if current is None:
        raise LookupError("processor not found")

    previous = str(current.get("dpaStatus") or "")
    if previous == TARGET_STATUS:
        state = "already_target"
        resulting = current
    elif previous in {"signed", "not_required"}:
        state = "already_resolved"
        resulting = current
    elif previous == EXPECTED_STATUS:
        resulting = operations.upsert_processor(
            _payload(current, dpa_status=TARGET_STATUS),
            db_path,
        )
        state = "transitioned"
    else:
        raise RuntimeError("unexpected processor DPA state")

    return {
        "schema": "checkupauto.processor-dpa-review-transition/v1",
        "processorId": processor_id,
        "previousStatus": previous,
        "currentStatus": str(resulting.get("dpaStatus") or ""),
        "state": state,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    parser.add_argument("--processor-id", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        parser.error(f"--confirm doit valoir {CONFIRMATION}")
    result = transition(
        args.processor_id,
        Path(args.db) if args.db else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
