"""Strict customer appointment input contract for future Mercure adapter.

Never infer Mercure's proprietary vehicle/energy/model IDs from display labels.
Only explicitly qualified provider mappings may be used for customer writes.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import re

from mercure_booking_write_contract import BookingWriteRequest
from mercure_booking_write_validation import validate


class CustomerPayloadNotQualified(ValueError):
    pass


@dataclass(frozen=True)
class QualifiedCustomerDetails:
    account_id: str
    vehicle_id: str
    registration: str
    surname: str
    given_name: str
    email: str
    telephone: str
    provider_brand_id: str
    provider_model_id: str
    provider_energy_id: str
    mapping_verified: bool
    registration_system: str = "siv"
    formula_number_present: bool = True
    card_issue_date: str = ""


def qualify(request: BookingWriteRequest, details: QualifiedCustomerDetails) -> dict:
    validate(request)
    if not isinstance(details, QualifiedCustomerDetails):
        raise CustomerPayloadNotQualified("mercure_customer_details_missing")
    if details.mapping_verified is not True:
        raise CustomerPayloadNotQualified("mercure_vehicle_mapping_unverified")
    if details.account_id != request.account_id or details.vehicle_id != request.vehicle_id:
        raise CustomerPayloadNotQualified("mercure_customer_vehicle_mismatch")
    if details.registration_system=="siv":
        if not re.fullmatch(r"[A-Z]{2}-[0-9]{3}-[A-Z]{2}",details.registration):
            raise CustomerPayloadNotQualified("mercure_registration_invalid")
        if details.formula_number_present is not True or details.card_issue_date:
            raise CustomerPayloadNotQualified("mercure_registration_document_invalid")
    elif details.registration_system=="fni":
        import customer_accounts
        try:
            normalized=customer_accounts._registration(details.registration,"fni")
        except customer_accounts.CustomerAccountError as exc:
            raise CustomerPayloadNotQualified("mercure_registration_invalid") from exc
        if normalized!=details.registration or details.formula_number_present:
            raise CustomerPayloadNotQualified("mercure_registration_document_invalid")
        try:
            issued=dt.date.fromisoformat(details.card_issue_date)
        except (TypeError,ValueError) as exc:
            raise CustomerPayloadNotQualified("mercure_card_issue_date_invalid") from exc
        if issued.isoformat()!=details.card_issue_date or not dt.date(1900,1,1)<=issued<=dt.date.today():
            raise CustomerPayloadNotQualified("mercure_card_issue_date_invalid")
    else:
        raise CustomerPayloadNotQualified("mercure_registration_system_invalid")
    if not all(isinstance(value,str) and value.strip() for value in (
        details.surname,details.given_name,details.email,details.telephone,
        details.provider_brand_id,details.provider_model_id,details.provider_energy_id,
    )):
        raise CustomerPayloadNotQualified("mercure_customer_details_incomplete")
    if not all(re.fullmatch(r"[0-9]{1,12}",value) for value in (
        details.provider_brand_id,details.provider_model_id,details.provider_energy_id,
    )):
        raise CustomerPayloadNotQualified("mercure_provider_mapping_invalid")
    return {
        "nom":details.surname.strip(),
        "prenom":details.given_name.strip(),
        "email":details.email.strip(),
        "telephone":details.telephone.strip(),
        "immatriculation":details.registration,
        "marque":details.provider_brand_id,
        "modele":details.provider_model_id,
        "energie":details.provider_energy_id,
        "date":request.date+"T"+request.time,
    }
