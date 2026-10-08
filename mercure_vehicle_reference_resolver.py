"""Exact, fail-closed mapping of customer vehicle descriptors to Mercure IDs."""
from __future__ import annotations

import unicodedata

import mercure_brand_energy_reference as lists
import mercure_vehicle_reference as models_api


class VehicleReferenceResolutionError(ValueError):
    pass


def _normalize(value: str) -> str:
    if not isinstance(value,str):
        raise VehicleReferenceResolutionError("vehicle_reference_invalid")
    return " ".join(unicodedata.normalize("NFKC",value).casefold().split())


def _unique(items: list[dict],label: str) -> str:
    target=_normalize(label)
    matches=[item["id"] for item in items if _normalize(item["label"])==target]
    if len(matches)!=1:
        raise VehicleReferenceResolutionError("vehicle_reference_missing_or_ambiguous")
    return matches[0]


def resolve(*, brand: str, model: str, energy: str, centre_type: str = "1") -> dict:
    refs=lists.fetch_references()
    brand_id=_unique(refs["marque"],brand)
    energy_id=_unique(refs["energie"],energy)
    models=models_api.models(centre_type=centre_type,brand_id=brand_id)
    model_id=_unique(models,model)
    return {"brandId":brand_id,"modelId":model_id,"energyId":energy_id,
            "centreType":centre_type,"mappingVerified":True}
