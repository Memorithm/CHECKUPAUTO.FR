"""Internal VL customer booking orchestration, disabled unless explicitly authorized."""
from __future__ import annotations

import customer_booking_creation
import mercure_customer_booking_assembly
import mercure_vl_provider_writer_factory


class MercureVlBookingCoordinatorError(ValueError):
    pass


def create_and_verify(*, request, account: dict, vehicle: dict,
                      metadata: dict, observed_metadata: dict,
                      expected_service_label: str, authorized: bool = False) -> dict:
    if authorized is not True:
        raise MercureVlBookingCoordinatorError("mercure_customer_write_not_authorized")
    assembled=mercure_customer_booking_assembly.assemble(
        request=request,account=account,vehicle=vehicle)
    writer=mercure_vl_provider_writer_factory.create(
        appointment=assembled["appointment"],metadata=metadata,
        observed_metadata=observed_metadata,
        expected_service_label=expected_service_label,authorized=True)
    return customer_booking_creation.create_and_verify(request=request,provider=writer)
