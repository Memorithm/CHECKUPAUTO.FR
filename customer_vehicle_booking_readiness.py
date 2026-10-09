"""Read-only readiness assessment for previously saved customer vehicles."""
from __future__ import annotations
from customer_vehicle_characteristics import require_booking_essentials,VehicleCharacteristicsError

def assess(vehicle: object) -> dict:
    if not isinstance(vehicle,dict):
        return {"ready":False,"missing":["vehicle"]}
    missing=[]
    if not str(vehicle.get("registration") or "").strip():
        missing.append("registration")
    try:
        require_booking_essentials(vehicle.get("characteristics"))
    except VehicleCharacteristicsError:
        missing.append("characteristics")
    if vehicle.get("registrationSystem")=="siv" and vehicle.get("formulaNumberPresent") is not True:
        missing.append("formulaNumber")
    if vehicle.get("registrationSystem")=="fni" and not vehicle.get("cardIssueDate"):
        missing.append("cardIssueDate")
    if vehicle.get("registrationSystem") not in ("siv","fni"):
        missing.append("registrationSystem")
    return {"ready":not missing,"missing":missing}
