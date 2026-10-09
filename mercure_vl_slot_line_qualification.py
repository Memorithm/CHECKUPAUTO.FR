"""Conservative VL line qualification against independently observed calendar events."""
from __future__ import annotations
import datetime as dt
import re
from mercure_vl_calendar_line_evidence import verify


def qualify(*, events: list, line_id: str, date: str, time: str) -> dict:
    if not isinstance(events,list) or not isinstance(line_id,str) or not re.fullmatch(r"[0-9]{1,12}",line_id):
        raise ValueError("mercure_slot_line_invalid")
    expected=dt.datetime.fromisoformat(date+"T"+time)
    matching=[]
    for event in events:
        if not isinstance(event,dict):
            continue
        try:
            start=dt.datetime.fromisoformat(str(event.get("start") or "").replace("Z","+00:00"))
            if start.tzinfo is not None:
                start=start.astimezone(dt.timezone(dt.timedelta(hours=2))).replace(tzinfo=None)
        except ValueError:
            continue
        if start!=expected:
            continue
        try:
            evidence=verify(event)
        except ValueError:
            continue
        if evidence["lineId"]==line_id:
            matching.append(evidence)
    if len(matching)!=1:
        raise ValueError("mercure_slot_line_not_independently_qualified")
    return {"lineId":line_id,"observed":True,"slotAvailable":False,
            "customerWriteEnabled":False}
