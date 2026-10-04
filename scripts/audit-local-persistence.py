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
        text=path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    persistence=bool(re.search(r"sqlite3|CREATE TABLE|\.sqlite3|write_text\(|write_bytes\(|open\([^\n]+["'](?:w|a|x|wb|ab)["']",text,re.I))
    if not persistence:
        continue
    tables=sorted(set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+([A-Za-z0-9_]+)",text,re.I)))
    dbs=sorted(set(re.findall(r"["']([^"']+\.sqlite3)["']",text)))
    writes=[]
    for pat in (r"\.write_text\(",r"\.write_bytes\(",r"open\([^\n]+["'](?:w|a|x|wb|ab)["']"):
        if re.search(pat,text):
            writes.append(pat)
    rows.append({"file":rel,"tables":tables,"sqliteLiterals":dbs,"fileWritePatterns":writes})
print(json.dumps({"schema":"checkupauto.local-persistence-audit/v1","files":rows},sort_keys=True,separators=(",",":")))
