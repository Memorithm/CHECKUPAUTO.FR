from __future__ import annotations

import datetime
import re

import mercure_admin_client as mercure
import mercure_provider_coverage


CLIENT_KINDS = {"account", "free"}
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
INVENTORY_PAST_DAYS = 365
INVENTORY_FUTURE_DAYS = 365
MAX_APPOINTMENTS = 500
MAX_VEHICLES = 200
MAX_BILLING_ROWS = 500
MAX_PROVIDER_WINDOW_DAYS = 365
MAX_PROVIDER_WINDOWS = 256


def parse_subject_ref(value: object) -> tuple[str, str]:
    """Parse an opaque Mercure customer reference without accepting URL fragments."""
    raw = str(value or "").strip()
    if raw.count(":") != 1:
        raise ValueError("subjectRef Mercure invalide")
    client_kind_raw, client_id = raw.split(":", 1)
    client_kind = client_kind_raw.strip().lower()
    if client_kind not in CLIENT_KINDS:
        raise ValueError("subjectRef Mercure invalide")
    if not _CLIENT_ID_RE.fullmatch(client_id):
        raise ValueError("subjectRef Mercure invalide")
    return client_kind, client_id


def _provider_id(value: object) -> str:
    raw = str(value or "").strip()
    return raw if _PROVIDER_ID_RE.fullmatch(raw) else ""


def _iso_datetime(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 64:
        return ""
    try:
        datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return raw


def _event_belongs_to(event: dict, client_kind: str, client_id: str) -> bool:
    ext = event.get("extendedProps") or {}
    if not isinstance(ext, dict):
        return False
    field = "clientCompteId" if client_kind == "account" else "clientLibreId"
    return str(ext.get(field) or "").strip() == client_id


def _event_vehicle_ids(event: dict) -> list[str]:
    ext = event.get("extendedProps") or {}
    if not isinstance(ext, dict):
        return []
    values = ext.get("vehiculeId") or []
    if not isinstance(values, list):
        values = [values]
    result = []
    for value in values:
        vehicle_id = _provider_id(value)
        if vehicle_id and vehicle_id not in result:
            result.append(vehicle_id)
    return result


def _provider_windows(start: datetime.date, end_exclusive: datetime.date) -> list[tuple[str, str]]:
    if start >= end_exclusive:
        raise ValueError("fenêtre Mercure invalide")
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor < end_exclusive:
        if len(windows) >= MAX_PROVIDER_WINDOWS:
            raise ValueError("frontière Mercure trop étendue")
        next_cursor = min(
            cursor + datetime.timedelta(days=MAX_PROVIDER_WINDOW_DAYS),
            end_exclusive,
        )
        windows.append((cursor.isoformat(), next_cursor.isoformat()))
        cursor = next_cursor
    return windows


def _bounded_billing_inventory(
    session,
    start: str,
    end_exclusive: str,
    appointment_ids: set[str],
) -> dict:
    """Cross-reference centre-wide billing only through subject-proven appointment IDs."""
    try:
        rows = mercure._appointments(session, start, end_exclusive)
    except Exception:
        return {
            "state": "unavailable",
            "rows": [],
            "matchingCountInWindow": 0,
            "truncated": False,
        }

    matched = []
    seen: set[str] = set()
    matching_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        appointment_id = _provider_id(row.get("id"))
        if not appointment_id or appointment_id not in appointment_ids or appointment_id in seen:
            continue
        seen.add(appointment_id)
        matching_count += 1
        if len(matched) >= MAX_BILLING_ROWS:
            continue
        raw_price = row.get("prix_tcc")
        matched.append(
            {
                "appointmentId": appointment_id,
                "paymentState": str(row.get("etat_paiement") or "").strip()[:40],
                "priceTtc": None if raw_price in (None, "") else round(mercure._price(raw_price), 2),
            }
        )
    return {
        "state": "available",
        "rows": matched,
        "matchingCountInWindow": matching_count,
        "truncated": matching_count > MAX_BILLING_ROWS,
    }


def _window_inventory(
    session,
    client_kind: str,
    client_id: str,
    start: str,
    end_exclusive: str,
) -> dict:
    events = mercure._calendar_events(session, start, end_exclusive)
    appointments = []
    appointment_ids: set[str] = set()
    vehicle_ids: list[str] = []
    missing_appointment_ids = 0

    for event in events:
        if not isinstance(event, dict) or not _event_belongs_to(event, client_kind, client_id):
            continue
        ids = _event_vehicle_ids(event)
        for vehicle_id in ids:
            if vehicle_id not in vehicle_ids and len(vehicle_ids) <= MAX_VEHICLES:
                vehicle_ids.append(vehicle_id)
        appointment_id = _provider_id(mercure._event_id(event))
        if appointment_id:
            appointment_ids.add(appointment_id)
        else:
            missing_appointment_ids += 1
        if len(appointments) < MAX_APPOINTMENTS:
            appointments.append(
                {
                    "appointmentId": appointment_id,
                    "startAt": _iso_datetime(event.get("start")),
                    "endAt": _iso_datetime(event.get("end")),
                    "vehicleIds": ids[:16],
                }
            )

    billing = _bounded_billing_inventory(session, start, end_exclusive, appointment_ids)
    return {
        "appointments": appointments,
        "appointmentIds": appointment_ids,
        "missingAppointmentIds": missing_appointment_ids,
        "vehicleIds": vehicle_ids,
        "billing": billing,
    }


def _vehicle_inventory(session, vehicle_ids: list[str]) -> dict:
    rows = []
    try:
        for vehicle_id in vehicle_ids[:MAX_VEHICLES]:
            details = mercure.vehicle_details(vehicle_id, session)
            due_date = str((details or {}).get("date_echeance") or "").strip()[:10]
            try:
                datetime.date.fromisoformat(due_date)
            except ValueError:
                due_date = ""
            rows.append(
                {
                    "vehicleId": vehicle_id,
                    "technicalInspectionDueDate": due_date,
                }
            )
    except Exception:
        return {"state": "unavailable", "rows": []}
    return {"state": "available", "rows": rows}


def _merge_operational_windows(
    session,
    client_kind: str,
    client_id: str,
    windows: list[tuple[str, str]],
    window_metadata: dict,
) -> dict:
    appointments = []
    appointment_ids: set[str] = set()
    missing_appointment_ids = 0
    vehicle_ids: list[str] = []
    billing_rows = []
    billing_ids: set[str] = set()
    billing_available = True
    billing_truncated = False

    for start, end_exclusive in windows:
        part = _window_inventory(session, client_kind, client_id, start, end_exclusive)
        missing_appointment_ids += int(part["missingAppointmentIds"])
        appointment_ids.update(part["appointmentIds"])
        for row in part["appointments"]:
            appointment_id = str(row.get("appointmentId") or "")
            if appointment_id and any(
                str(existing.get("appointmentId") or "") == appointment_id
                for existing in appointments
            ):
                continue
            if len(appointments) < MAX_APPOINTMENTS:
                appointments.append(row)
        for vehicle_id in part["vehicleIds"]:
            if vehicle_id not in vehicle_ids and len(vehicle_ids) <= MAX_VEHICLES:
                vehicle_ids.append(vehicle_id)

        billing = part["billing"]
        if billing["state"] != "available":
            billing_available = False
        billing_truncated = billing_truncated or bool(billing["truncated"])
        for row in billing["rows"]:
            appointment_id = str(row.get("appointmentId") or "")
            if not appointment_id or appointment_id in billing_ids:
                continue
            billing_ids.add(appointment_id)
            if len(billing_rows) < MAX_BILLING_ROWS:
                billing_rows.append(row)

    vehicle_inventory = _vehicle_inventory(session, vehicle_ids)
    appointment_count = len(appointment_ids) + missing_appointment_ids
    appointments_truncated = appointment_count > MAX_APPOINTMENTS
    vehicles_truncated = len(vehicle_ids) > MAX_VEHICLES
    billing_truncated = billing_truncated or len(billing_ids) > MAX_BILLING_ROWS
    billing_matches_appointments = bool(
        billing_available
        and not billing_truncated
        and missing_appointment_ids == 0
        and billing_ids == appointment_ids
    )
    return {
        "state": "available",
        "window": dict(window_metadata),
        "sourceWindowCount": len(windows),
        "appointments": appointments,
        "vehicles": vehicle_inventory["rows"],
        "vehicleState": vehicle_inventory["state"],
        "billing": billing_rows,
        "billingState": "available" if billing_available else "unavailable",
        "appointmentCountInWindow": appointment_count,
        "billingCountInWindow": len(billing_ids),
        "appointmentIdsMissing": missing_appointment_ids,
        "billingMatchesAppointments": billing_matches_appointments,
        "appointmentsTruncated": appointments_truncated,
        "vehiclesTruncated": vehicles_truncated,
        "billingTruncated": billing_truncated,
    }


def _bounded_operational_inventory(
    session,
    client_kind: str,
    client_id: str,
    today: datetime.date | None = None,
) -> dict:
    current = today or mercure.business_today()
    start = current - datetime.timedelta(days=INVENTORY_PAST_DAYS)
    end_exclusive = current + datetime.timedelta(days=INVENTORY_FUTURE_DAYS + 1)
    return _merge_operational_windows(
        session,
        client_kind,
        client_id,
        [(start.isoformat(), end_exclusive.isoformat())],
        {
            "start": start.isoformat(),
            "endExclusive": end_exclusive.isoformat(),
            "pastDays": INVENTORY_PAST_DAYS,
            "futureDays": INVENTORY_FUTURE_DAYS,
            "mode": "bounded_default",
        },
    )


def _attested_operational_inventory(
    session,
    client_kind: str,
    client_id: str,
    provider_boundary: dict,
    today: datetime.date,
) -> dict:
    if not provider_boundary.get("attested"):
        raise ValueError("frontière Mercure non attestée")
    start = datetime.date.fromisoformat(str(provider_boundary.get("historyStart") or ""))
    future_days = int(provider_boundary.get("futureDays") or 0)
    end_exclusive = today + datetime.timedelta(days=future_days + 1)
    windows = _provider_windows(start, end_exclusive)
    return _merge_operational_windows(
        session,
        client_kind,
        client_id,
        windows,
        {
            "start": start.isoformat(),
            "endExclusive": end_exclusive.isoformat(),
            "futureDays": future_days,
            "mode": "attested_provider_boundary",
        },
    )


def _unavailable_inventory() -> dict:
    return {
        "state": "unavailable",
        "appointments": [],
        "vehicles": [],
        "vehicleState": "unavailable",
        "billing": [],
        "billingState": "unavailable",
        "appointmentCountInWindow": 0,
        "billingCountInWindow": 0,
        "appointmentIdsMissing": 0,
        "billingMatchesAppointments": False,
        "appointmentsTruncated": False,
        "vehiclesTruncated": False,
        "billingTruncated": False,
        "sourceWindowCount": 0,
    }


def contact_snapshot(subject_ref: object) -> dict:
    """Return a privacy-bounded Mercure export without exposing raw provider objects.

    Without an evidence-backed provider boundary, operational data remains the
    disclosed ±365-day inventory. When an attested boundary is configured, the
    exact interval is scanned in bounded provider windows. Appointment/billing
    completeness is only asserted when that scan succeeds without truncation or
    missing identifiers. Vehicle completeness additionally requires independent
    provider/contract evidence that the subject-bound appointment calendar is
    the authoritative subject-to-vehicle inventory. The snapshot is only marked
    complete when all four disclosed Mercure data classes are proven complete.
    """
    client_kind, client_id = parse_subject_ref(subject_ref)
    session = mercure._session()
    contact = mercure._customer_contact(session, client_kind, client_id)
    email = str(contact.get("email") or "").strip()[:254]
    telephone = str(contact.get("telephone") or "").strip()[:40]
    today = mercure.business_today()
    provider_boundary = mercure_provider_coverage.boundary(today)
    vehicle_boundary = provider_boundary.get("vehicleInventory") or {}
    boundary_applied = False
    try:
        if provider_boundary.get("attested"):
            inventory = _attested_operational_inventory(
                session, client_kind, client_id, provider_boundary, today
            )
            boundary_applied = inventory.get("state") == "available"
        else:
            inventory = _bounded_operational_inventory(session, client_kind, client_id, today)
    except Exception:
        inventory = _unavailable_inventory()

    appointments_complete = bool(
        provider_boundary.get("attested")
        and boundary_applied
        and inventory.get("state") == "available"
        and not inventory.get("appointmentsTruncated")
        and int(inventory.get("appointmentIdsMissing") or 0) == 0
    )
    billing_complete = bool(
        appointments_complete
        and inventory.get("billingState") == "available"
        and not inventory.get("billingTruncated")
        and inventory.get("billingMatchesAppointments")
    )
    vehicles_complete = bool(
        provider_boundary.get("attested")
        and boundary_applied
        and vehicle_boundary.get("attested")
        and inventory.get("state") == "available"
        and inventory.get("vehicleState") == "available"
        and not inventory.get("vehiclesTruncated")
    )
    export_complete = bool(vehicles_complete and appointments_complete and billing_complete)
    return {
        "provider": "mercure",
        "subject": {
            "clientKind": client_kind,
            "clientId": client_id,
        },
        "contact": {
            "email": email,
            "telephone": telephone,
        },
        "operationalInventory": inventory,
        "providerBoundary": provider_boundary,
        "coverage": {
            "contact": True,
            "vehicles": vehicles_complete,
            "appointments": appointments_complete,
            "billing": billing_complete,
            "boundedOperationalInventory": inventory.get("state") == "available",
            "boundedVehicleInventory": inventory.get("vehicleState") == "available",
            "boundedBillingInventory": inventory.get("billingState") == "available",
            "providerBoundaryAttested": bool(provider_boundary.get("attested")),
            "providerBoundaryAppliedToInventory": boundary_applied,
            "providerVehicleInventoryAttested": bool(vehicle_boundary.get("attested")),
        },
        "partial": not export_complete,
    }
