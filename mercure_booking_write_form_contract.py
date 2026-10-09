"""Read-only contract for observed Mercure administrator appointment form.

This module cannot issue network requests or create appointments. Presence of
a form key is not proof that a customer write is safe or qualified.
"""
from __future__ import annotations

from dataclasses import dataclass


REQUIRED_FIELDS=frozenset({
    "centre_type","ligne_id","duree","client_compte",
    "nom","prenom","email","telephone","marque","modele","energie",
    "immatriculation","prestation","utilisateur","date",
    "rendezvous_id","tcheckDispo",
})


class MercureWriteFormContractError(ValueError):
    pass


@dataclass(frozen=True)
class MercureWriteFormQualification:
    missing_fields: tuple[str,...]
    unknown_fields: tuple[str,...]
    contract_observed: bool
    customer_write_qualified: bool = False


def audit(observed_fields: object) -> MercureWriteFormQualification:
    if not isinstance(observed_fields,(list,tuple,set,frozenset)) or len(observed_fields)>500:
        raise MercureWriteFormContractError("mercure_write_form_invalid")
    if not all(isinstance(field,str) and 0<len(field)<=80 for field in observed_fields):
        raise MercureWriteFormContractError("mercure_write_form_invalid")
    fields=set(observed_fields)
    missing=tuple(sorted(REQUIRED_FIELDS-fields))
    return MercureWriteFormQualification(
        missing_fields=missing,
        unknown_fields=tuple(sorted(fields-REQUIRED_FIELDS)),
        contract_observed=not missing,
        customer_write_qualified=False,
    )
