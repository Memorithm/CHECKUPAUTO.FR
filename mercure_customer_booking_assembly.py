"""Build a read-only, validated Mercure customer booking payload.

No booking writer or HTTP endpoint is exposed here.
"""
from __future__ import annotations

from mercure_booking_write_contract import BookingWriteRequest
from mercure_customer_payload_contract import QualifiedCustomerDetails,qualify
from mercure_invoice_contact_contract import validate as validate_invoice
from mercure_vehicle_reference_resolver import resolve


class CustomerBookingAssemblyError(ValueError):
    pass


def assemble(*, request: BookingWriteRequest, account: dict, vehicle: dict) -> dict:
    if not isinstance(account,dict) or not isinstance(vehicle,dict):
        raise CustomerBookingAssemblyError("booking_context_invalid")
    if account.get("accountId") != request.account_id or vehicle.get("vehicleId") != request.vehicle_id:
        raise CustomerBookingAssemblyError("booking_account_vehicle_mismatch")
    billing=validate_invoice({
        "surname":account.get("surname"),"givenName":account.get("givenName"),
        "address":account.get("addressLine1"),"postalCode":account.get("postalCode"),
        "city":account.get("city"),"phone":account.get("phone"),"email":account.get("email"),
    })
    characteristics=vehicle.get("characteristics")
    if not isinstance(characteristics,dict):
        raise CustomerBookingAssemblyError("booking_vehicle_characteristics_missing")
    mapping=resolve(brand=characteristics.get("brand"),model=characteristics.get("model"),
                    energy=characteristics.get("energy"))
    if mapping.get("mappingVerified") is not True:
        raise CustomerBookingAssemblyError("booking_vehicle_mapping_unverified")
    details=QualifiedCustomerDetails(
        account_id=request.account_id,vehicle_id=request.vehicle_id,
        registration=str(vehicle.get("registration") or ""),
        surname=billing["surname"],given_name=billing["givenName"],
        email=billing["email"],telephone=billing["phone"],
        provider_brand_id=mapping["brandId"],provider_model_id=mapping["modelId"],
        provider_energy_id=mapping["energyId"],mapping_verified=True)
    payload=qualify(request,details)
    return {"appointment":payload,"billing":billing,
            "providerWritePerformed":False,"bookingConfirmed":False}
