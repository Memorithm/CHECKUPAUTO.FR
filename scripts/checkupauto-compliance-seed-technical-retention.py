#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

import retention_enforcement

BASELINE=ROOT/"fixtures/compliance-technical-retention-baseline.json"
SCHEMA="checkupauto.compliance-technical-retention-baseline/v1"
EXPECTED_RULES={"review_followup","reminder_targets","security_telemetry"}


def load_baseline() -> dict:
    data=json.loads(BASELINE.read_text(encoding="utf-8"))
    if data.get("schema")!=SCHEMA:
        raise RuntimeError("technical retention schema invalid")
    rules=data.get("rules")
    if not isinstance(rules,list) or not rules:
        raise RuntimeError("technical retention rules missing")
    ids=[str(row.get("ruleId") or "") for row in rules if isinstance(row,dict)]
    if len(ids)!=len(rules) or set(ids)!=EXPECTED_RULES or len(ids)!=len(set(ids)):
        raise RuntimeError("technical retention rule set invalid")
    for row in rules:
        rule_id=str(row["ruleId"])
        meta=retention_enforcement.CONFIGURABLE_RULES.get(rule_id)
        if not meta or meta.get("legalReviewRequired"):
            raise RuntimeError("technical retention rule requires legal review")
        if row.get("legalReviewConfirmed") is not False:
            raise RuntimeError("technical retention must not assert legal review")
        if row.get("enabled") is not True:
            raise RuntimeError("technical retention rule must be enabled")
        days=int(row.get("activeDays") or 0)
        minimum=int(meta.get("minimumDays") or 1)
        if days<minimum or days>retention_enforcement.MAX_RETENTION_DAYS:
            raise RuntimeError("technical retention duration invalid")
        justification=str(row.get("justification") or "").strip()
        if len(justification)<12 or len(justification)>1000:
            raise RuntimeError("technical retention justification invalid")
    return data


def _expected_setting(row: dict) -> dict:
    return {
        "activeDays":int(row["activeDays"]),
        "justification":str(row["justification"]).strip(),
        "legalReviewConfirmed":False,
        "enabled":True,
    }


def apply(db_path=None) -> dict:
    baseline=load_baseline()
    changed=[]
    verified=[]
    for row in baseline["rules"]:
        rule_id=str(row["ruleId"])
        expected=_expected_setting(row)
        current=retention_enforcement.policy(rule_id,db_path)
        if current.get("configured"):
            actual={
                "activeDays":int(current.get("activeDays") or 0),
                "justification":str(current.get("justification") or "").strip(),
                "legalReviewConfirmed":bool(current.get("legalReviewConfirmed")),
                "enabled":bool(current.get("enabled")),
            }
            if actual!=expected:
                raise RuntimeError("technical retention conflicts with runtime policy")
        else:
            retention_enforcement.save_policy({
                "ruleId":rule_id,
                **expected,
            },db_path)
            changed.append(rule_id)
        state=retention_enforcement.policy(rule_id,db_path)
        if not state.get("ready"):
            raise RuntimeError("technical retention rule not ready")
        verified.append(rule_id)

    status=retention_enforcement.status(db_path)
    remaining=sorted(str(row.get("ruleId") or "") for row in status.get("blockers") or [])
    return {
        "schema":"checkupauto.compliance-technical-retention-result/v1",
        "changedRuleIds":sorted(changed),
        "verifiedRuleIds":sorted(verified),
        "readyRuleCount":int(status.get("readyRuleCount") or 0),
        "ruleCount":int(status.get("ruleCount") or 0),
        "remainingBlockerRuleIds":remaining,
        "retentionBound":bool(status.get("bound")),
        "legalReviewAsserted":False,
    }


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--db")
    parser.add_argument("--confirm",required=True)
    args=parser.parse_args()
    if args.confirm!="APPLY-TECHNICAL-RETENTION-BASELINE":
        parser.error("--confirm doit valoir APPLY-TECHNICAL-RETENTION-BASELINE")
    result=apply(Path(args.db) if args.db else None)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
