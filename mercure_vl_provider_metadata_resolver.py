"""Read-only provider metadata qualification for VL booking composition."""
from __future__ import annotations
import mercure_public_client
import mercure_vl_live_metadata_options


class MercureVlMetadataResolutionError(ValueError):
    pass


def resolve(*, service: str, line_id: str, operator_id: str,
            centre_type: str = "1") -> dict:
    item=mercure_public_client.service(service)
    metadata={"service_id":str(item["id"]),"duration":str(item["duration"]),
              "centre_type":centre_type,"line_id":line_id,"operator_id":operator_id}
    observed=mercure_vl_live_metadata_options.fetch()
    field_names={"service_id":"prestation","duration":"duree",
                 "centre_type":"centre_type","line_id":"ligne_id","operator_id":"utilisateur"}
    for field,source in field_names.items():
        options=observed.get(source)
        if not isinstance(options,list) or metadata[field] not in options:
            raise MercureVlMetadataResolutionError("mercure_vl_metadata_unverified")
    if centre_type not in {"1","4"}:
        raise MercureVlMetadataResolutionError("mercure_vl_class_invalid")
    return {"metadata":metadata,"observed_metadata":observed,
            "service_label":str(item["providerLabel"])}
