"""Independent provider-read identity check; never trust the write receipt alone."""
from mercure_booking_identity_evidence import validate_identity

def verify(*, reference, account_id, vehicle_id, service, provider_evidence, calendar_verified):
    validate_identity(provider_evidence,appointment_reference=reference,
                      account_id=account_id,vehicle_id=vehicle_id,service=service)
    if calendar_verified is not True:
        raise ValueError("mercure_calendar_not_verified")
    return {"confirmed":True,"providerReference":reference}
