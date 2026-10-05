from __future__ import annotations

import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CATALOG_PATH=ROOT/"fixtures/local-persistence-catalog.json"
SCHEMA="checkupauto.local-persistence-catalog/v1"
_TABLE_RE=re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MODULE_RE=re.compile(r"^[A-Za-z0-9_./-]+\.py$")


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
        if not isinstance(row,dict) or set(row)!={"table","module"}:
            raise RuntimeError("local persistence catalog row invalid")
        table=str(row.get("table") or "")
        module=str(row.get("module") or "")
        if not _TABLE_RE.fullmatch(table) or table in seen:
            raise RuntimeError("local persistence table invalid")
        if not _MODULE_RE.fullmatch(module) or module.startswith("/") or ".." in Path(module).parts:
            raise RuntimeError("local persistence module invalid")
        seen.add(table)
        normalized.append({"table":table,"module":module})
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
    return {
        "scope":"production-sqlite-create-table-v1",
        "complete":True,
        "tableCount":len(names),
        "tableNames":names,
        "privacyExecutionCoverageAsserted":False,
        "state":"catalogued",
    }
