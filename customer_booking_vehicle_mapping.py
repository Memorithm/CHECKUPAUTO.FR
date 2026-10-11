"""Booking step: verify, and if needed let the customer fix, the Mercure vehicle mapping.

Read-only towards Mercure (reference lists only).  The only write is to the
customer's own saved vehicle, replacing brand/model/energy with labels taken
verbatim from Mercure's reference lists, so that the exact resolver used by
the booking writer then matches.  Mercure IDs are never accepted from the
browser without being re-checked against the live lists.
"""
from __future__ import annotations

import re

import customer_accounts
import mercure_brand_energy_reference as lists
import mercure_vehicle_reference as models_api
import mercure_vehicle_reference_resolver as resolver


class VehicleMappingError(ValueError):
    pass


class VehicleMappingUnavailable(RuntimeError):
    pass


def _owned_vehicle(account_id: str, vehicle_id: object) -> dict:
    if not isinstance(vehicle_id, str) or not vehicle_id.strip():
        raise VehicleMappingError("booking_vehicle_not_owned")
    try:
        return customer_accounts.vehicle_summary(account_id, vehicle_id)
    except customer_accounts.CustomerAccountError as exc:
        raise VehicleMappingError("booking_vehicle_not_owned") from exc


def _assess(vehicle: dict) -> dict:
    characteristics = vehicle.get("characteristics") or {}
    current = {key: str(characteristics.get(key) or "") for key in ("brand", "model", "energy")}
    try:
        resolver.resolve(brand=current["brand"], model=current["model"], energy=current["energy"])
    except resolver.VehicleReferenceResolutionError as exc:
        return {"verified": False, "reason": str(exc), "current": current}
    except Exception as exc:
        raise VehicleMappingUnavailable("vehicle_reference_unavailable") from exc
    return {"verified": True, "reason": "", "current": current}


def check(*, account_id: str, vehicle_id: object) -> dict:
    vehicle = _owned_vehicle(account_id, vehicle_id)
    result = _assess(vehicle)
    return {"ok": True, "vehicleId": vehicle["vehicleId"], **result,
            "genericModelAllowed": resolver.generic_model_allowed()}


def _unique(rows: object, identifier: str) -> dict:
    if not isinstance(rows, list):
        raise VehicleMappingUnavailable("vehicle_reference_unavailable")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == identifier]
    if len(matches) != 1:
        raise VehicleMappingError("vehicle_reference_selection_invalid")
    return matches[0]


def apply(*, account_id: str, payload: object) -> dict:
    if (not isinstance(payload, dict)
            or set(payload) != {"vehicleId", "brandId", "modelId", "energyId"}
            or not all(isinstance(value, str) for value in payload.values())):
        raise VehicleMappingError("vehicle_mapping_request_invalid")
    if not all(re.fullmatch(r"[0-9]{1,12}", payload[key]) for key in ("brandId", "modelId", "energyId")):
        raise VehicleMappingError("vehicle_reference_selection_invalid")
    vehicle = _owned_vehicle(account_id, payload["vehicleId"])
    try:
        refs = lists.fetch_references()
        brand = _unique(refs.get("marque"), payload["brandId"])
        energy = _unique(refs.get("energie"), payload["energyId"])
        model = _unique(models_api.models(centre_type="1", brand_id=brand["id"]), payload["modelId"])
    except VehicleMappingError:
        raise
    except Exception as exc:
        raise VehicleMappingUnavailable("vehicle_reference_unavailable") from exc
    if resolver.is_generic_model(model["label"]) and not resolver.generic_model_allowed():
        raise VehicleMappingError("vehicle_reference_generic_model_unqualified")
    try:
        updated = customer_accounts.update_vehicle_characteristics(
            account_id, vehicle["vehicleId"],
            {"brand": brand["label"], "model": model["label"], "energy": energy["label"]})
    except customer_accounts.CustomerAccountError as exc:
        raise VehicleMappingError(str(exc)) from exc
    result = _assess(updated)
    return {"ok": True, "vehicleId": updated["vehicleId"], **result,
            "genericModelAllowed": resolver.generic_model_allowed()}
