#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_subject_rights
import rights_execution_dispatch


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
        description="Exécution opérateur des demandes de droits CheckupAuto via un dispatcher borné."
    )
    parser.add_argument("--db", help="Chemin explicite vers compliance.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capability")
    audit = sub.add_parser("audit")
    audit.add_argument("--limit", type=int, default=100)
    execute = sub.add_parser("execute")
    execute.add_argument(
        "json_file",
        help=(
            "Fichier JSON local contenant id, subjectRef, adapter et les champs "
            "strictement requis par cet adaptateur."
        ),
    )
    args = parser.parse_args()
    db = Path(args.db) if args.db else None

    if args.command == "capability":
        _print(rights_execution_dispatch.capability(db))
    elif args.command == "audit":
        _print(data_subject_rights.audit_rows(db, args.limit))
    elif args.command == "execute":
        _print(rights_execution_dispatch.execute(_payload(args.json_file), db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
