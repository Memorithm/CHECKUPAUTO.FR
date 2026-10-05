#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

import compliance_store

BASELINE=ROOT/"fixtures/compliance-known-identity.json"
SCHEMA="checkupauto.compliance-known-identity/v1"


def load_baseline() -> dict:
    data=json.loads(BASELINE.read_text(encoding="utf-8"))
    if data.get("schema")!=SCHEMA:
        raise RuntimeError("known identity schema invalid")
    settings=data.get("settings")
    if not isinstance(settings,dict) or not settings:
        raise RuntimeError("known identity settings missing")
    unknown=set(settings)-set(compliance_store.SETTINGS_FIELDS)
    if unknown:
        raise RuntimeError("known identity fields invalid")
    for forbidden in data.get("deliberatelyUnasserted") or []:
        if forbidden in settings:
            raise RuntimeError("unasserted identity field present")
    return data


def apply(db_path=None) -> dict:
    baseline=load_baseline()
    current=compliance_store.settings(db_path)
    expected=baseline["settings"]
    conflicts={}
    changes={}
    for key,value in expected.items():
        existing=str(current.get(key) or "").strip()
        value=str(value or "").strip()
        if existing and existing!=value:
            conflicts[key]={"existing":existing,"expected":value}
        elif not existing and value:
            changes[key]=value
    if conflicts:
        raise RuntimeError("known identity conflicts with runtime settings")
    updated=compliance_store.save_settings({**current,**changes},db_path) if changes else current
    summary=compliance_store.summary(db_path)
    return {
        "schema":"checkupauto.compliance-known-identity-result/v1",
        "changedFields":sorted(changes),
        "knownFieldsVerified":all(str(updated.get(k) or "").strip()==str(v).strip() for k,v in expected.items()),
        "identityComplete":bool(summary.get("identityComplete")),
        "missingIdentityFields":sorted(str(x) for x in summary.get("missingIdentityFields") or []),
        "deliberatelyUnasserted":sorted(str(x) for x in baseline.get("deliberatelyUnasserted") or []),
    }


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--db")
    parser.add_argument("--confirm",required=True)
    args=parser.parse_args()
    if args.confirm!="APPLY-KNOWN-IDENTITY-FACTS":
        parser.error("--confirm doit valoir APPLY-KNOWN-IDENTITY-FACTS")
    result=apply(Path(args.db) if args.db else None)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
