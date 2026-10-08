"""Customer-provided vehicle characteristics, distinct from verified Mercure IDs."""
from __future__ import annotations

import re


FIELDS=("brand","model","energy","vehicleType","firstRegistrationDate","vin",
        "commercialName","bodyStyle","category","grossWeightKg")


class VehicleCharacteristicsError(ValueError):
    pass


def normalize(data: object) -> dict:
    if data is None:
        return {}
    if not isinstance(data,dict) or set(data)-set(FIELDS):
        raise VehicleCharacteristicsError("customer_vehicle_characteristics_invalid")
    result={}
    for field in FIELDS:
        value=data.get(field,"")
        if not isinstance(value,str):
            raise VehicleCharacteristicsError("customer_vehicle_characteristics_invalid")
        value=" ".join(value.strip().split())
        if len(value)>120 or any(ord(c)<32 for c in value):
            raise VehicleCharacteristicsError("customer_vehicle_characteristics_invalid")
        if field=="vin" and value and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}",value.upper()):
            raise VehicleCharacteristicsError("customer_vehicle_vin_invalid")
        if field=="firstRegistrationDate" and value:
            import datetime as dt
            try:
                day=dt.date.fromisoformat(value)
            except ValueError as exc:
                raise VehicleCharacteristicsError("customer_vehicle_date_invalid") from exc
            if day.isoformat()!=value or day>dt.date.today():
                raise VehicleCharacteristicsError("customer_vehicle_date_invalid")
        if field=="grossWeightKg" and value and (not value.isdecimal() or not 1<=int(value)<=100000):
            raise VehicleCharacteristicsError("customer_vehicle_weight_invalid")
        result[field]=value.upper() if field=="vin" else value
    return result


def require_booking_essentials(data: object) -> dict:
    """Validate required booking descriptors without changing legacy saved records."""
    result=normalize(data)
    if not all(result.get(key,"").strip() for key in ("brand","model","energy")):
        raise VehicleCharacteristicsError("customer_vehicle_booking_essentials_missing")
    return result
