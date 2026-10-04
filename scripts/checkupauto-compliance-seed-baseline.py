#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

import compliance_operations as operations

BASELINE=ROOT/"fixtures/compliance-runtime-baseline.json"
SCHEMA="checkupauto.compliance-runtime-baseline/v1"

def load_baseline() -> dict:
    data=json.loads(BASELINE.read_text(encoding="utf-8"))
    if data.get("schema")!=SCHEMA: raise RuntimeError("baseline schema invalid")
    activities=data.get("processingActivities")
    processors=data.get("processors")
    if not isinstance(activities,list) or not activities: raise RuntimeError("activities missing")
    if not isinstance(processors,list) or not processors: raise RuntimeError("processors missing")
    return data

def apply(db_path=None) -> dict:
    data=load_baseline()
    saved_activities=[operations.upsert_processing_activity(row,db_path) for row in data["processingActivities"]]
    saved_processors=[operations.upsert_processor(row,db_path) for row in data["processors"]]
    state=operations.summary(db_path)
    return {
      "schema":"checkupauto.compliance-runtime-seed-result/v1",
      "activityCount":len(saved_activities),
      "processorCount":len(saved_processors),
      "operationalRegistersReady":bool(state.get("operationalRegistersReady")),
      "blockerTypes":sorted({str(x.get("type") or "") for x in state.get("blockers") or []}),
      "externalEvidencePending":any(str(x.get("dpaStatus") or "")=="pending" for x in saved_processors),
    }

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--db")
    parser.add_argument("--confirm",required=True)
    args=parser.parse_args()
    if args.confirm!="APPLY-REVIEWED-COMPLIANCE-BASELINE":
        parser.error("--confirm doit valoir APPLY-REVIEWED-COMPLIANCE-BASELINE")
    result=apply(Path(args.db) if args.db else None)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return 0

if __name__=="__main__": raise SystemExit(main())
