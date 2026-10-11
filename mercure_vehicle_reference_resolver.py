"""Exact, fail-closed mapping of customer vehicle descriptors to Mercure IDs."""
from __future__ import annotations

import os
import unicodedata

import mercure_brand_energy_reference as lists
import mercure_vehicle_reference as models_api


GENERIC_MODEL_ENV = "CHECKUPAUTO_MERCURE_ALLOW_GENERIC_MODEL"
GENERIC_MODEL_LABELS = frozenset({"autres modeles", "autres modèles", "autre modele", "autre modèle"})


class VehicleReferenceResolutionError(ValueError):
    pass


def generic_model_allowed(environ=None) -> bool:
    """Mercure's generic "Autres modèles" row is refused unless explicitly enabled."""
    source = os.environ if environ is None else environ
    return str(source.get(GENERIC_MODEL_ENV, "")).strip() == "true"


def is_generic_model(label: object) -> bool:
    return isinstance(label, str) and _normalize(label) in GENERIC_MODEL_LABELS


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


def resolve(*, brand: str, model: str, energy: str, centre_type: str = "1",
            allow_generic_model: bool | None = None) -> dict:
    refs=lists.fetch_references()
    brand_id=_unique(refs["marque"],brand)
    energy_id=_unique(refs["energie"],energy)
    models=models_api.models(centre_type=centre_type,brand_id=brand_id)
    allowed = generic_model_allowed() if allow_generic_model is None else allow_generic_model is True
    if _normalize(model) in GENERIC_MODEL_LABELS and not allowed:
        raise VehicleReferenceResolutionError("vehicle_reference_generic_model_unqualified")
    model_id=_unique(models,model)
    return {"brandId":brand_id,"modelId":model_id,"energyId":energy_id,
            "centreType":centre_type,"mappingVerified":True}
