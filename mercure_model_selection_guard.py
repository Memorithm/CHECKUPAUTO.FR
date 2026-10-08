"""Check model selection belongs to the selected provider brand."""
from __future__ import annotations

class MercureModelSelectionError(ValueError):
    pass

def validate(*, brand_id: str, loaded_brand_id: str, model_id: str, models: list[dict]) -> str:
    if not brand_id or brand_id!=loaded_brand_id:
        raise MercureModelSelectionError("vehicle_model_stale_brand")
    if not isinstance(models,list) or sum(
        isinstance(row,dict) and row.get("id")==model_id for row in models
    )!=1:
        raise MercureModelSelectionError("vehicle_model_unverified")
    return model_id
