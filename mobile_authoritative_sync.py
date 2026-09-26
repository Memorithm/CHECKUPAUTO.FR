from __future__ import annotations

import datetime
import threading

import mercure_admin_client as mercure
import mobile_devices
import privacy_suppression as privacy
import reminder_dispatch

INTERVAL_SECONDS = 3600
UPCOMING_APPOINTMENT_DAYS = 180
_STOP = threading.Event()
_THREAD = None


def _binding_processing_suppressed(binding: dict) -> bool:
    """Re-check provider/vehicle restrictions for a persisted mobile binding."""
    vehicle_id = str(binding.get("vehicle_id") or "").strip()
    client_kind = str(binding.get("client_kind") or "").strip()
    client_id = str(binding.get("client_id") or "").strip()
    candidates: list[tuple[str, object]] = [("vehicle", vehicle_id)]
    if client_kind in {"account", "free"} and client_id:
        candidates.append(("mercure_" + client_kind, client_id))
    return privacy.any_suppressed(candidates, "all_processing")


def upcoming_appointments_snapshot() -> list[dict]:
    today = mercure.business_today()
    end = today + datetime.timedelta(days=UPCOMING_APPOINTMENT_DAYS)
    return mercure.upcoming_control_appointments(today.isoformat(), end.isoformat())


def sync_installation(
    installation_id: str,
    upcoming_appointments: list[dict] | None = None,
    *,
    refresh_appointments: bool = False,
) -> dict:
    installation = mobile_devices._install_id(installation_id)
    if privacy.is_suppressed("installation", installation, "all_processing"):
        return {
            "ok": True,
            "installationId": installation,
            "bindings": 0,
            "authoritativeDeadlines": 0,
            "privacySuppressed": True,
            "suppressedBindings": 0,
        }

    bindings = mobile_devices.registered_vehicle_bindings(installation)
    if not bindings:
        return {
            "ok": True,
            "installationId": installation,
            "bindings": 0,
            "authoritativeDeadlines": 0,
            "privacySuppressed": False,
            "suppressedBindings": 0,
        }

    if refresh_appointments and upcoming_appointments is None:
        try:
            upcoming_appointments = upcoming_appointments_snapshot()
        except Exception:
            upcoming_appointments = []

    allowed_bindings = []
    suppressed_bindings = 0
    for binding in bindings:
        if _binding_processing_suppressed(binding):
            suppressed_bindings += 1
            continue
        allowed_bindings.append(binding)

    inventory = {
        row["vehicle_id"]: row["due_date"]
        for row in reminder_dispatch.deadlines_for_vehicle_ids(
            [row["vehicle_id"] for row in allowed_bindings]
        )
    }
    appointment_by_identity: dict[tuple[str, str, str], str] = {}
    for item in sorted(upcoming_appointments or [], key=lambda row: str(row.get("appointmentAt") or "")):
        identity = (
            str(item.get("vehicleId") or ""),
            str(item.get("clientKind") or ""),
            str(item.get("clientId") or ""),
        )
        appointment_at = str(item.get("appointmentAt") or "")
        if all(identity) and appointment_at:
            appointment_by_identity.setdefault(identity, appointment_at)

    deadlines = []
    appointments = 0
    for row in allowed_bindings:
        vehicle_id = row["vehicle_id"]
        if vehicle_id not in inventory:
            continue
        identity = (vehicle_id, row["client_kind"], row["client_id"])
        appointment_at = appointment_by_identity.get(identity, "")
        item = {"deadlineId": row["binding_id"], "dueDate": inventory[vehicle_id]}
        if appointment_at:
            item["appointmentAt"] = appointment_at
            appointments += 1
        deadlines.append(item)
    # Always synchronize, including an empty allowed set: this removes previously
    # cached authoritative deadlines that became restricted after the binding existed.
    result = mobile_devices.sync_authoritative_deadlines(installation, deadlines)
    return {
        "ok": True,
        "installationId": installation,
        "bindings": len(bindings),
        "authoritativeDeadlines": result["deadlineCount"],
        "authoritativeAppointments": appointments,
        "privacySuppressed": False,
        "suppressedBindings": suppressed_bindings,
    }


def sync_once() -> dict:
    bindings = mobile_devices.registered_vehicle_bindings()
    installation_ids = sorted({row["installation_id"] for row in bindings})
    if not installation_ids:
        return {
            "ok": True,
            "installations": 0,
            "synced": 0,
            "privacySuppressed": 0,
            "suppressedBindings": 0,
            "authoritativeDeadlines": 0,
            "authoritativeAppointments": 0,
            "appointmentState": "no_bindings",
            "failed": 0,
        }

    appointment_state = "ready"
    try:
        upcoming = upcoming_appointments_snapshot()
    except Exception:
        upcoming = []
        appointment_state = "unavailable"

    synced = 0
    suppressed = 0
    suppressed_bindings = 0
    deadlines = 0
    appointments = 0
    failed = 0
    for installation_id in installation_ids:
        try:
            result = sync_installation(installation_id, upcoming)
            if result.get("privacySuppressed"):
                suppressed += 1
                continue
            synced += 1
            suppressed_bindings += int(result.get("suppressedBindings") or 0)
            deadlines += int(result["authoritativeDeadlines"])
            appointments += int(result.get("authoritativeAppointments") or 0)
        except Exception:
            failed += 1
    return {
        "ok": failed == 0,
        "installations": len(installation_ids),
        "synced": synced,
        "privacySuppressed": suppressed,
        "suppressedBindings": suppressed_bindings,
        "authoritativeDeadlines": deadlines,
        "authoritativeAppointments": appointments,
        "appointmentState": appointment_state,
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
