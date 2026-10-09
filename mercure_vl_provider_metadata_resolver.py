"""Read-only provider metadata qualification for VL booking composition."""
from __future__ import annotations
import mercure_public_client
import mercure_vl_live_metadata_options
import mercure_vl_embedded_service_catalog
import mercure_admin_client as mercure


class MercureVlMetadataResolutionError(ValueError):
    pass


def resolve(*, service: str, line_id: str, operator_id: str,
            centre_type: str = "1") -> dict:
    item=mercure_public_client.service(service)
    metadata={"service_id":str(item["id"]),"duration":str(item["duration"]),
              "centre_type":centre_type,"line_id":line_id,"operator_id":operator_id}
    observed=mercure_vl_live_metadata_options.fetch()
    session=mercure._session()
    response=mercure._check_auth(session.get(
        mercure.BASE+"/admin/calendrier",timeout=20,allow_redirects=False))
    response.raise_for_status()
    catalog=mercure_vl_embedded_service_catalog.extract(response.text)
    entry=catalog.get(metadata["service_id"])
    if not isinstance(entry,dict) or entry["duration"]!=metadata["duration"]:
        raise MercureVlMetadataResolutionError("mercure_vl_catalog_mismatch")
    if entry["label"]!=str(item["providerLabel"]):
        raise MercureVlMetadataResolutionError("mercure_vl_catalog_label_mismatch")
    if centre_type!="1":
        raise MercureVlMetadataResolutionError("mercure_vl_class_invalid")
    if centre_type not in observed.get("centre_type",[]):
        raise MercureVlMetadataResolutionError("mercure_vl_centre_unverified")
    if operator_id not in observed.get("utilisateur",[]):
        raise MercureVlMetadataResolutionError("mercure_vl_operator_unverified")
    # ligne_id is a hidden numeric field, not a dropdown. It requires
    # independent slot/resource evidence before any customer write.
    if not isinstance(line_evidence,dict) or line_evidence.get("observed") is not True:
        raise MercureVlMetadataResolutionError("mercure_vl_line_evidence_required")
    if line_evidence.get("lineId")!=line_id or line_evidence.get("slotAvailable") is not True:
        raise MercureVlMetadataResolutionError("mercure_vl_slot_evidence_required")
    return {"metadata":metadata,"observed_metadata":observed,
            "service_label":str(item["providerLabel"])}
