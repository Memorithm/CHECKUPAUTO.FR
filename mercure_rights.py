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


def _bounded_billing_inventory(
    session,
    start: str,
    end_exclusive: str,
    appointment_ids: set[str],
) -> dict:
    """Cross-reference provider billing rows only through subject-proven appointment IDs.

    ``/admin/rdv_by_client`` returns a centre-wide period inventory. It must never
    be exported directly for a DSAR. Calendar rows already prove which appointment
    IDs belong to the exact Mercure subject, so only those IDs may cross this
    boundary. Provider failures are reduced to a bounded state and never reflected.
    """
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


def _bounded_operational_inventory(session, client_kind: str, client_id: str) -> dict:
    today = mercure.business_today()
    start = today - datetime.timedelta(days=INVENTORY_PAST_DAYS)
    end_exclusive = today + datetime.timedelta(days=INVENTORY_FUTURE_DAYS + 1)
    start_value = start.isoformat()
    end_value = end_exclusive.isoformat()
    events = mercure._calendar_events(session, start_value, end_value)

    appointments = []
    appointment_ids: set[str] = set()
    vehicle_ids: list[str] = []
    matching_count = 0
    for event in events:
        if not isinstance(event, dict) or not _event_belongs_to(event, client_kind, client_id):
            continue
        matching_count += 1
        ids = _event_vehicle_ids(event)
        for vehicle_id in ids:
            if vehicle_id not in vehicle_ids:
                vehicle_ids.append(vehicle_id)
        appointment_id = _provider_id(mercure._event_id(event))
        if appointment_id:
            appointment_ids.add(appointment_id)
        if len(appointments) >= MAX_APPOINTMENTS:
            continue
        appointments.append(
            {
                "appointmentId": appointment_id,
                "startAt": _iso_datetime(event.get("start")),
                "endAt": _iso_datetime(event.get("end")),
                "vehicleIds": ids[:16],
            }
        )

    vehicles = []
    for vehicle_id in vehicle_ids[:MAX_VEHICLES]:
        details = mercure.vehicle_details(vehicle_id, session)
        due_date = str((details or {}).get("date_echeance") or "").strip()[:10]
        try:
            datetime.date.fromisoformat(due_date)
        except ValueError:
            due_date = ""
        vehicles.append(
            {
                "vehicleId": vehicle_id,
                "technicalInspectionDueDate": due_date,
            }
        )

    billing = _bounded_billing_inventory(session, start_value, end_value, appointment_ids)
    return {
        "state": "available",
        "window": {
            "start": start_value,
            "endExclusive": end_value,
            "pastDays": INVENTORY_PAST_DAYS,
            "futureDays": INVENTORY_FUTURE_DAYS,
        },
        "appointments": appointments,
        "vehicles": vehicles,
        "billing": billing["rows"],
        "billingState": billing["state"],
        "appointmentCountInWindow": matching_count,
        "billingCountInWindow": billing["matchingCountInWindow"],
        "appointmentsTruncated": matching_count > MAX_APPOINTMENTS,
        "vehiclesTruncated": len(vehicle_ids) > MAX_VEHICLES,
        "billingTruncated": billing["truncated"],
    }


def contact_snapshot(subject_ref: object) -> dict:
    """Return a privacy-bounded Mercure export without exposing raw provider objects.

    Contact data is covered directly. The operational inventory is intentionally
    limited to a disclosed two-year window and therefore does not claim complete
    historical vehicle, appointment or billing coverage. A separate provider
    boundary attestation records whether the external historical/future boundary
    is evidenced; it is not yet used to widen this bounded inventory.
    """
    client_kind, client_id = parse_subject_ref(subject_ref)
    session = mercure._session()
    contact = mercure._customer_contact(session, client_kind, client_id)
    email = str(contact.get("email") or "").strip()[:254]
    telephone = str(contact.get("telephone") or "").strip()[:40]
    try:
        inventory = _bounded_operational_inventory(session, client_kind, client_id)
    except Exception:
        inventory = {
            "state": "unavailable",
            "appointments": [],
            "vehicles": [],
            "billing": [],
            "billingState": "unavailable",
            "appointmentCountInWindow": 0,
            "billingCountInWindow": 0,
            "appointmentsTruncated": False,
            "vehiclesTruncated": False,
            "billingTruncated": False,
        }
    provider_boundary = mercure_provider_coverage.boundary(mercure.business_today())
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
            "vehicles": False,
            "appointments": False,
            "billing": False,
            "boundedOperationalInventory": inventory.get("state") == "available",
            "boundedBillingInventory": inventory.get("billingState") == "available",
            "providerBoundaryAttested": bool(provider_boundary.get("attested")),
            "providerBoundaryAppliedToInventory": False,
        },
        "partial": True,
    }
