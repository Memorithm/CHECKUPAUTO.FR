"""Read-only Mercure calendar line evidence, not proof of an available slot."""
from __future__ import annotations
import re


class MercureVlLineEvidenceError(ValueError):
    pass


def verify(event: object) -> dict:
    if not isinstance(event,dict) or not isinstance(event.get("extendedProps"),dict):
        raise MercureVlLineEvidenceError("mercure_line_event_invalid")
    props=event["extendedProps"]
    if str(props.get("centreTypeId") or "")!="1":
        raise MercureVlLineEvidenceError("mercure_line_not_vl")
    resource=str(event.get("resourceId") or "")
    line=str(props.get("ligneId") or "")
    if not re.fullmatch(r"[0-9]{1,12}",resource) or resource!=line:
        raise MercureVlLineEvidenceError("mercure_line_mismatch")
    return {"lineId":line,"centreType":"1","observed":True,
            "slotAvailabilityVerified":False,"customerWriteEnabled":False}
