"""Read-only provider metadata qualification for VL booking composition."""
from __future__ import annotations
import mercure_public_client
import mercure_vl_live_metadata_options
import mercure_vl_embedded_service_catalog
import mercure_admin_client as mercure
import mercure_vl_live_slot_evidence


class MercureVlMetadataResolutionError(ValueError):
    pass


def resolve(*, service: str, line_id: str, operator_id: str,
            centre_type: str = "1", line_evidence: dict | None = None,
            date: str | None = None, time: str | None = None) -> dict:
    item=mercure_public_client.service(service)
    metadata={"service_id":str(item["id"]),"duration":str(item["duration"]),
              "centre_type":centre_type,"line_id":line_id,"operator_id":operator_id}
    observed=mercure_vl_live_metadata_options.fetch()
    session=mercure._session()
    try:
        response=mercure._check_auth(session.get(
            mercure.BASE+"/admin/calendrier",timeout=20,allow_redirects=False))
        response.raise_for_status()
        catalog=mercure_vl_embedded_service_catalog.extract(response.text)
    finally:
        session.close()
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
    live_evidence = None
    if date is not None or time is not None:
        if line_evidence is not None or not isinstance(date,str) or not isinstance(time,str):
            raise MercureVlMetadataResolutionError("mercure_vl_slot_evidence_override_forbidden")
        live_evidence = mercure_vl_live_slot_evidence.load(
            service=service,date=date,time=time,line_id=line_id)
        line_evidence = live_evidence
    if not isinstance(line_evidence,dict) or line_evidence.get("observed") is not True:
        raise MercureVlMetadataResolutionError("mercure_vl_line_evidence_required")
    if line_evidence.get("lineId")!=line_id or line_evidence.get("slotAvailable") is not True:
        raise MercureVlMetadataResolutionError("mercure_vl_slot_evidence_required")
    # These are dynamic inputs, not HTML dropdowns. Populate only from the
    # authenticated catalog and independently verified resource/slot sources.
    qualified_observed = {**observed, "prestation": [metadata["service_id"]],
                          "duree": [metadata["duration"]], "ligne_id": [line_id]}
    result = {"metadata": metadata, "observed_metadata": qualified_observed,
              "service_label": str(item["providerLabel"])}
    if live_evidence is not None:
        result["slot_evidence"] = live_evidence
    return result
