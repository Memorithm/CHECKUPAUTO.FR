"""Server-side booking configuration source. Never reads customer request fields."""
from __future__ import annotations
import os
import re


class BookingServerConfigError(ValueError):
    pass


def load(*, environ=None) -> dict:
    source=os.environ if environ is None else environ
    if not hasattr(source,"get"):
        raise BookingServerConfigError("booking_server_config_invalid")
    enabled=source.get("CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED")=="true"
    line=source.get("CHECKUPAUTO_MERCURE_VL_LINE_ID","")
    operator=source.get("CHECKUPAUTO_MERCURE_VL_OPERATOR_ID","")
    if not enabled:
        return {"enabled":False,"lineId":"","operatorId":""}
    if not all(isinstance(value,str) and re.fullmatch(r"[0-9]{1,12}",value)
               for value in (line,operator)):
        raise BookingServerConfigError("booking_server_ids_unqualified")
    return {"enabled":True,"lineId":line,"operatorId":operator}
