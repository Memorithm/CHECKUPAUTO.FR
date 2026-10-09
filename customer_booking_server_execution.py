"""Internal booking execution. Never accept provider authority from browser input."""
from __future__ import annotations
import customer_booking_api
import mercure_vl_booking_coordinator
from mercure_booking_write_contract import BookingWriteRequest


class CustomerBookingExecutionError(RuntimeError):
    pass


def execute(*, payload: dict, account: dict, vehicle: dict,
            metadata: dict, observed_metadata: dict, service_label: str,
            server_authorized: bool = False):
    if server_authorized is not True:
        raise CustomerBookingExecutionError("booking_execution_not_authorized")
    if not isinstance(payload,dict) or not isinstance(account,dict) or not isinstance(vehicle,dict):
        raise CustomerBookingExecutionError("booking_context_missing")
    if vehicle.get("vehicleId")!=payload.get("vehicleId"):
        raise CustomerBookingExecutionError("booking_vehicle_mismatch")
    if set(payload)!={"service","date","time","vehicleId","requestKey"}:
        raise CustomerBookingExecutionError("booking_payload_invalid")
    preflight=customer_booking_api.preflight(
        {key:payload[key] for key in ("service","date","time","vehicleId")},
        account={**account,"vehicles":[vehicle]})
    if preflight.get("bookingEnabled") is not True:
        raise CustomerBookingExecutionError("booking_provider_not_ready")
    request=BookingWriteRequest(
        request_key=payload["requestKey"],account_id=account["accountId"],
        vehicle_id=vehicle["vehicleId"],service=preflight["service"],
        date=preflight["date"],time=preflight["time"],
        price_cents=preflight["priceCents"])
    return mercure_vl_booking_coordinator.create_and_verify(
        request=request,account=account,vehicle=vehicle,metadata=metadata,
        observed_metadata=observed_metadata,
        expected_service_label=service_label,authorized=True)
