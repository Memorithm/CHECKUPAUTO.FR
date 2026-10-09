"""Read-only provider identity inspection; incomplete Mercure records fail closed."""
from __future__ import annotations

from mercure_booking_identity_evidence import VerifiedBookingIdentity


class ProviderIdentityUnavailable(ValueError):
    pass


def verify_record(*, record: object, provider_reference: str,
                  account_id: str, vehicle_id: str, service: str,
                  registration: str, expected_provider_service: str) -> VerifiedBookingIdentity:
    if not isinstance(record,dict):
        raise ProviderIdentityUnavailable("mercure_identity_record_missing")
    expected={
        "id":provider_reference,
        "immatriculation":registration,
        "prestation_id":expected_provider_service,
    }
    if not all(isinstance(value,str) and value for value in expected.values()):
        raise ProviderIdentityUnavailable("mercure_identity_expected_fields_missing")
    if any(str(record.get(key) or "")!=value for key,value in expected.items()):
        raise ProviderIdentityUnavailable("mercure_identity_provider_mismatch")
    if record.get("independentRead") is not True:
        raise ProviderIdentityUnavailable("mercure_identity_read_not_independent")
    return VerifiedBookingIdentity(provider_reference,account_id,vehicle_id,service,True)
