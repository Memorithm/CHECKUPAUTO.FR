"""Read-only provider calendar lookup; a reference alone is not identity proof."""
from __future__ import annotations
import datetime as dt
import re
import mercure_admin_client as mercure


def read_reference(*, reference: str, date: str) -> dict:
    if not isinstance(reference,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",reference):
        raise ValueError("mercure_reference_invalid")
    day=dt.date.fromisoformat(date)
    if day.isoformat()!=date:
        raise ValueError("mercure_date_invalid")
    end=(day+dt.timedelta(days=1)).isoformat()
    session=mercure._session()
    events=mercure._calendar_events(session,date,end)
    matches=[event for event in events if mercure._event_id(event)==reference]
    if len(matches)!=1:
        raise ValueError("mercure_reference_missing_or_ambiguous")
    return {"reference":reference,"calendarRead":True,
            "customerIdentityVerified":False}
