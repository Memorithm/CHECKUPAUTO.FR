"""Server-only booking context. No browser-controlled metadata or payment proof."""
from __future__ import annotations

import mercure_vl_provider_metadata_resolver


class BookingRouteContextError(ValueError):
    pass


def build(*, service: str, server_config: dict,
          payment_policy: dict, payment_evidence: dict | None) -> dict:
    if not isinstance(server_config,dict) or set(server_config)!={"lineId","operatorId","enabled"}:
        raise BookingRouteContextError("booking_server_config_invalid")
    if server_config["enabled"] is not True:
        raise BookingRouteContextError("booking_server_not_authorized")
    line_id=server_config["lineId"]
    operator_id=server_config["operatorId"]
    if not isinstance(line_id,str) or not isinstance(operator_id,str):
        raise BookingRouteContextError("booking_provider_ids_invalid")
    resolved=mercure_vl_provider_metadata_resolver.resolve(
        service=service,line_id=line_id,operator_id=operator_id)
    return {
        "metadata":resolved["metadata"],
        "observed_metadata":resolved["observed_metadata"],
        "service_label":resolved["service_label"],
        "payment_policy":payment_policy,
        "payment_evidence":payment_evidence,
    }
