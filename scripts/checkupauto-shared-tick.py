#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import fcntl
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import admin_server
import booking_test
import mobile_authoritative_sync
import mobile_reminder_dispatch
import reminder_dispatch
import review_followup
import security_alerts
import withdrawal_service


def _run(name: str, fn) -> dict:
    started = time.monotonic()
    try:
        result = fn()
        return {
            "name": name,
            "ok": True,
            "durationMs": int((time.monotonic() - started) * 1000),
            "result": result if isinstance(result, dict) else {"completed": True},
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "durationMs": int((time.monotonic() - started) * 1000),
            "error": type(exc).__name__,
        }


def tick() -> dict:
    admin_server.initialize_runtime(background=False)
    tasks = [
        ("booking_test_cleanup", booking_test.purge_expired),
        ("reminder_dispatch", reminder_dispatch.process_once),
        ("mobile_authoritative_sync", mobile_authoritative_sync.sync_once),
        ("mobile_reminder_dispatch", mobile_reminder_dispatch.process_once),
        ("review_followup", review_followup.process_once),
        ("withdrawal_receipts", withdrawal_service.dispatch_pending),
        ("security_alert_retry", security_alerts.retry_pending),
    ]
    rows = [_run(name, fn) for name, fn in tasks]
    return {
        "schemaVersion": 1,
        "ok": all(row["ok"] for row in rows),
        "tasks": rows,
    }


def main() -> int:
    data_dir = Path(
        os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".shared-host-tick.lock"
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({
                "schemaVersion": 1,
                "ok": True,
                "state": "already_running",
            }))
            return 0
        result = tick()
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
