"""Read-only Mercure calendar qualification. No appointment writes or PII output."""
from __future__ import annotations

import datetime as dt
import json
import sys

import mercure_admin_client as mercure


def inspect(day: str) -> dict:
    parsed=dt.date.fromisoformat(day)
    if parsed.isoformat()!=day:
        raise ValueError("invalid_day")
    end=(parsed+dt.timedelta(days=1)).isoformat()
    session=mercure._session()
    events=mercure._calendar_events(session,day,end)
    if not isinstance(events,list):
        raise RuntimeError("invalid_calendar")
    return {
        "ok":True,
        "date":day,
        "calendarReadable":True,
        "eventCount":len(events),
        "providerWritesPerformed":False,
        "bookingConfirmed":False,
    }


if __name__=="__main__":
    try:
        result=inspect(sys.argv[1])
        print(json.dumps(result,sort_keys=True))
    except Exception:
        print(json.dumps({"ok":False,"error":"calendar_probe_failed"}))
        raise SystemExit(1)
