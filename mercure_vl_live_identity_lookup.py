"""Independent authenticated Mercure appointment read for VL booking identity."""
from __future__ import annotations

import datetime as dt
import mercure_admin_client as mercure
from mercure_vl_appointment_row_identity import verify as verify_row


class MercureVlLiveIdentityError(ValueError):
    pass


def read_and_verify(*, reference: str, date: str, account_id: str,
                    vehicle_id: str, service: str, registration: str,
                    expected_service_label: str):
    try:
        day=dt.date.fromisoformat(date)
    except (TypeError,ValueError) as exc:
        raise MercureVlLiveIdentityError("mercure_date_invalid") from exc
    if day.isoformat()!=date:
        raise MercureVlLiveIdentityError("mercure_date_invalid")
    session=mercure._session()
    rows=mercure._appointments(session,date,(day+dt.timedelta(days=1)).isoformat())
    if not isinstance(rows,list):
        raise MercureVlLiveIdentityError("mercure_appointments_invalid")
    matches=[row for row in rows if isinstance(row,dict) and str(row.get("id") or "")==reference]
    if len(matches)!=1:
        raise MercureVlLiveIdentityError("mercure_appointment_missing_or_ambiguous")
    return verify_row(row=matches[0],reference=reference,account_id=account_id,
                      vehicle_id=vehicle_id,service=service,registration=registration,
                      expected_service_label=expected_service_label)
