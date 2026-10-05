from __future__ import annotations

import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CATALOG_PATH=ROOT/"fixtures/local-persistence-catalog.json"
SCHEMA="checkupauto.local-persistence-catalog/v2"
_TABLE_RE=re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MODULE_RE=re.compile(r"^[A-Za-z0-9_./-]+\.py$")
_RELATIONS={"none","direct","pseudonymous","evidence","transient","staging","sandbox","aggregate","runtime_profiled"}
_EXECUTION_STATES={"not_applicable","wired","partial","retention_only","unmapped","ephemeral","staging_only","sandbox_only","runtime_guarded"}
_ADAPTER_RE=re.compile(r"^[A-Za-z0-9_.-]{0,80}$")


def load() -> dict:
    data=json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema")!=SCHEMA:
        raise RuntimeError("local persistence catalog schema invalid")
    rows=data.get("tables")
    if not isinstance(rows,list) or not rows:
        raise RuntimeError("local persistence catalog empty")
    seen=set()
    normalized=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!={
            "table","module","subjectRelation","executionState","adapter",
            "subjectExecutionRequired",
        }:
            raise RuntimeError("local persistence catalog row invalid")
        table=str(row.get("table") or "")
        module=str(row.get("module") or "")
        relation=str(row.get("subjectRelation") or "")
        execution=str(row.get("executionState") or "")
        adapter=str(row.get("adapter") or "")
        required=row.get("subjectExecutionRequired")
        if not _TABLE_RE.fullmatch(table) or table in seen:
            raise RuntimeError("local persistence table invalid")
        if not _MODULE_RE.fullmatch(module) or module.startswith("/") or ".." in Path(module).parts:
            raise RuntimeError("local persistence module invalid")
        if relation not in _RELATIONS:
            raise RuntimeError("local persistence subject relation invalid")
        if execution not in _EXECUTION_STATES:
            raise RuntimeError("local persistence execution state invalid")
        if not _ADAPTER_RE.fullmatch(adapter):
            raise RuntimeError("local persistence adapter invalid")
        if not isinstance(required,bool):
            raise RuntimeError("local persistence subject execution flag invalid")
        if required and execution in {"not_applicable","ephemeral","staging_only","sandbox_only","runtime_guarded","retention_only"}:
            raise RuntimeError("required subject execution cannot be classified non-executable")
        seen.add(table)
        normalized.append({
            "table":table,
            "module":module,
            "subjectRelation":relation,
            "executionState":execution,
            "adapter":adapter,
            "subjectExecutionRequired":required,
        })
    normalized.sort(key=lambda row:row["table"])
    return {
        "schema":SCHEMA,
        "reviewedAt":str(data.get("reviewedAt") or ""),
        "scope":str(data.get("scope") or ""),
        "tables":normalized,
    }


def snapshot() -> dict:
    try:
        data=load()
    except Exception:
        return {
            "scope":"production-sqlite-create-table-v1",
            "complete":False,
            "tableCount":0,
            "tableNames":[],
            "privacyExecutionCoverageAsserted":False,
            "state":"unavailable",
        }
    names=[row["table"] for row in data["tables"]]
    required=[row for row in data["tables"] if row["subjectExecutionRequired"]]
    gaps=[
        row for row in required
        if row["executionState"] not in {"wired"}
    ]
    return {
        "scope":"production-sqlite-create-table-v2",
        "complete":True,
        "mappingComplete":True,
        "tableCount":len(names),
        "tableNames":names,
        "subjectExecutionRequiredCount":len(required),
        "executionGapCount":len(gaps),
        "executionGapTables":[row["table"] for row in gaps],
        "privacyExecutionCoverageAsserted":not gaps,
        "state":"mapped" if not gaps else "mapped_with_execution_gaps",
    }
