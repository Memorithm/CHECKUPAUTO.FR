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
import compliance_register_attestation as register_attestation


def _payload(path: str) -> dict:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("le fichier JSON doit contenir un objet")
    return data


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Registres opérationnels RGPD CheckupAuto (article 30, sous-traitants, AIPD)."
    )
    parser.add_argument("--db", help="Chemin explicite vers compliance.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    sub.add_parser("activities")
    sub.add_parser("processors")
    sub.add_parser("audit")
    sub.add_parser("attestation-status")
    attest = sub.add_parser("attest")
    attest.add_argument(
        "--confirm",
        required=True,
        help="Confirmation explicite: CURRENT-REGISTERS-REVIEWED",
    )
    activity = sub.add_parser("upsert-activity")
    activity.add_argument("json_file")
    processor = sub.add_parser("upsert-processor")
    processor.add_argument("json_file")
    args = parser.parse_args()
    db = Path(args.db) if args.db else None

    if args.command == "summary":
        _print(operations.summary(db))
    elif args.command == "activities":
        _print(operations.processing_activities(db))
    elif args.command == "processors":
        _print(operations.processors(db))
    elif args.command == "audit":
        _print(operations.audit_events(db))
    elif args.command == "attestation-status":
        _print(register_attestation.status(db))
    elif args.command == "attest":
        if args.confirm != "CURRENT-REGISTERS-REVIEWED":
            parser.error("--confirm doit valoir CURRENT-REGISTERS-REVIEWED")
        _print(register_attestation.attest(db))
    elif args.command == "upsert-activity":
        _print(operations.upsert_processing_activity(_payload(args.json_file), db))
    elif args.command == "upsert-processor":
        _print(operations.upsert_processor(_payload(args.json_file), db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
