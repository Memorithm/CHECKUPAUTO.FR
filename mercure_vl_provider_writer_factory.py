"""Internal VL writer construction. Caller must supply verified provider metadata."""
from __future__ import annotations

import mercure_admin_client as mercure
from mercure_vl_write_adapter import MercureVlWriteAdapter
from mercure_vl_live_identity_lookup import read_and_verify


class MercureVlWriterFactoryError(ValueError):
    pass


def create(*, appointment: dict, metadata: dict, observed_metadata: dict,
           expected_service_label: str, authorized: bool = False):
    if authorized is not True:
        raise MercureVlWriterFactoryError("mercure_customer_write_not_authorized")
    if not isinstance(metadata,dict) or not isinstance(observed_metadata,dict):
        raise MercureVlWriterFactoryError("mercure_metadata_unqualified")
    required={"service_id":"prestation","duration":"duree","centre_type":"centre_type",
              "line_id":"ligne_id","operator_id":"utilisateur"}
    if set(metadata)!=set(required):
        raise MercureVlWriterFactoryError("mercure_metadata_incomplete")
    for field,observed_key in required.items():
        options=observed_metadata.get(observed_key)
        if not isinstance(options,(list,tuple,set,frozenset)) or metadata[field] not in options:
            raise MercureVlWriterFactoryError("mercure_metadata_unverified")
    if not isinstance(expected_service_label,str) or not expected_service_label.strip():
        raise MercureVlWriterFactoryError("mercure_service_label_unqualified")
    return MercureVlWriteAdapter(
        session=mercure._session(),base_url=mercure.BASE,metadata=metadata,
        appointment=appointment,authorized=True,identity_reader=read_and_verify,
        expected_service_label=expected_service_label)
