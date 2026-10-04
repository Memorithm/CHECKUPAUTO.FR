#!/usr/bin/env python3
from __future__ import annotations
import json,re,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
tracked=subprocess.check_output(["git","ls-files","*.py"],cwd=ROOT,text=True).splitlines()
rows=[]
for rel in tracked:
    if rel.endswith("_test.py") or rel.startswith("ios/"):
        continue
    path=ROOT/rel
    try:
        source=path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    persistence_markers=(
        "sqlite3",
        "CREATE TABLE",
        ".sqlite3",
        ".write_text(",
        ".write_bytes(",
    )
    if not any(marker in source for marker in persistence_markers):
        continue
    tables=sorted(set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+([A-Za-z0-9_]+)",source,re.I)))
    dbs=sorted(set(re.findall(r"""["']([^"']+\.sqlite3)["']""",source)))
    writes=[]
    if ".write_text(" in source:
        writes.append("write_text")
    if ".write_bytes(" in source:
        writes.append("write_bytes")
    rows.append({
        "file":rel,
        "tables":tables,
        "sqliteLiterals":dbs,
        "fileWritePatterns":writes,
    })
print(json.dumps({"schema":"checkupauto.local-persistence-audit/v1","files":rows},sort_keys=True,separators=(",",":")))
