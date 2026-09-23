from __future__ import annotations

import threading

import mobile_devices
import privacy_suppression as privacy
import reminder_dispatch

INTERVAL_SECONDS = 3600
_STOP = threading.Event()
_THREAD = None


def sync_installation(installation_id: str) -> dict:
    installation = mobile_devices._install_id(installation_id)
    if privacy.is_suppressed("installation", installation, "all_processing"):
        return {
            "ok": True,
            "installationId": installation,
            "bindings": 0,
            "authoritativeDeadlines": 0,
            "privacySuppressed": True,
        }

    bindings = mobile_devices.registered_vehicle_bindings(installation)
    if not bindings:
        return {
            "ok": True,
            "installationId": installation,
            "bindings": 0,
            "authoritativeDeadlines": 0,
            "privacySuppressed": False,
        }

    inventory = {
        row["vehicle_id"]: row["due_date"]
        for row in reminder_dispatch.deadlines_for_vehicle_ids(
            [row["vehicle_id"] for row in bindings]
        )
    }
    deadlines = [
        {"deadlineId": row["binding_id"], "dueDate": inventory[row["vehicle_id"]]}
        for row in bindings
        if row["vehicle_id"] in inventory
    ]
    result = mobile_devices.sync_authoritative_deadlines(installation, deadlines)
    return {
        "ok": True,
        "installationId": installation,
        "bindings": len(bindings),
        "authoritativeDeadlines": result["deadlineCount"],
        "privacySuppressed": False,
    }


def sync_once() -> dict:
    bindings = mobile_devices.registered_vehicle_bindings()
    installation_ids = sorted({row["installation_id"] for row in bindings})
    synced = 0
    suppressed = 0
    deadlines = 0
    failed = 0
    for installation_id in installation_ids:
        try:
            result = sync_installation(installation_id)
            if result.get("privacySuppressed"):
                suppressed += 1
                continue
            synced += 1
            deadlines += int(result["authoritativeDeadlines"])
        except Exception:
            failed += 1
    return {
        "ok": failed == 0,
        "installations": len(installation_ids),
        "synced": synced,
        "privacySuppressed": suppressed,
        "authoritativeDeadlines": deadlines,
        "failed": failed,
    }


def _loop(interval: int) -> None:
    while not _STOP.is_set():
        try:
            sync_once()
        except Exception:
            pass
        if _STOP.wait(interval):
            break


def start(interval: int = INTERVAL_SECONDS) -> None:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _THREAD = threading.Thread(
        target=_loop,
        args=(max(60, int(interval)),),
        name="mobile-authoritative-sync",
        daemon=True,
    )
    _THREAD.start()
