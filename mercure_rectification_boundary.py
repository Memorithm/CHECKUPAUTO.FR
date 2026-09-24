from __future__ import annotations

import os
import re

import mercure_admin_client as mercure


# Provider data we have actually observed through bounded read paths. These names
# describe application semantics, not undocumented Mercure field names.
VERIFIED_AUTHORITATIVE_READ_FIELDS = (
    "contact.email",
    "contact.telephone",
    "vehicle.technicalInspectionDueDate",
)

# Deliberately empty until a provider-backed mutation route is documented and
# implemented. Synthetic appointment writes are not proof that Mercure supports
# authoritative customer/vehicle rectification.
VERIFIED_AUTHORITATIVE_MUTATION_FIELDS: tuple[str, ...] = ()

# Deliberately independent from implementation. A future mutation field is not
# completion-eligible until its provider-backed verification (read-after-write or
# equivalent externally verifiable proof) is explicitly represented here too.
PROVIDER_BACKED_VERIFICATION_FIELDS: tuple[str, ...] = ()

PROVIDER_FIELDS_ENV = "CYBERCHECK_MERCURE_RECTIFICATION_FIELDS"
PROVIDER_EVIDENCE_SHA256_ENV = "CYBERCHECK_MERCURE_RECTIFICATION_EVIDENCE_SHA256"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_NON_RECTIFICATION_WRITE_PRIMITIVES = (
    ("synthetic_appointment_create", "create_synthetic_test_appointment"),
    ("synthetic_appointment_remove", "remove_synthetic_test_appointment"),
)


def provider_attestation() -> dict:
    """Return a non-secret attestation of documented provider mutation support.

    The raw provider contract/documentation remains outside Git and runtime
    responses. Operators may configure only semantic fields already observed on
    authoritative read paths plus the SHA-256 of external evidence. This
    attestation never makes the application mutation-capable by itself.
    """
    fields_raw = os.environ.get(PROVIDER_FIELDS_ENV, "").strip()
    evidence_raw = os.environ.get(PROVIDER_EVIDENCE_SHA256_ENV, "").strip().lower()

    if not fields_raw and not evidence_raw:
        return {
            "state": "unconfigured",
            "attested": False,
            "fields": [],
            "evidenceSha256": "",
            "reason": "provider_rectification_not_attested",
        }
    if not fields_raw or not evidence_raw:
        return {
            "state": "invalid",
            "attested": False,
            "fields": [],
            "evidenceSha256": "",
            "reason": "provider_rectification_configuration_incomplete",
        }

    fields = tuple(dict.fromkeys(part.strip() for part in fields_raw.split(",") if part.strip()))
    allowed = set(VERIFIED_AUTHORITATIVE_READ_FIELDS)
    if not fields or any(field not in allowed for field in fields):
        return {
            "state": "invalid",
            "attested": False,
            "fields": [],
            "evidenceSha256": "",
            "reason": "provider_rectification_fields_unsupported",
        }
    if not _SHA256_RE.fullmatch(evidence_raw):
        return {
            "state": "invalid",
            "attested": False,
            "fields": [],
            "evidenceSha256": "",
            "reason": "provider_rectification_evidence_hash_invalid",
        }
    return {
        "state": "attested",
        "attested": True,
        "fields": list(fields),
        "evidenceSha256": evidence_raw,
        "reason": "",
    }


def capability() -> dict:
    """Expose the verified Mercure rectification boundary without inference.

    The admin client can create/remove synthetic appointments for operational
    probes, but no repository code currently proves an authoritative write path
    for the contact fields or technical-inspection due date read from Mercure.
    External evidence may attest provider support, but completion additionally
    requires an application primitive and provider-backed verification for every
    implemented field.
    """
    observed_non_rectification_writes = [
        semantic
        for semantic, attribute in _NON_RECTIFICATION_WRITE_PRIMITIVES
        if callable(getattr(mercure, attribute, None))
    ]
    mutation_fields = list(VERIFIED_AUTHORITATIVE_MUTATION_FIELDS)
    provider_verified_fields = set(PROVIDER_BACKED_VERIFICATION_FIELDS)
    primitive_implemented = bool(mutation_fields)
    attestation = provider_attestation()
    attested_fields = set(attestation.get("fields") or []) if attestation.get("attested") else set()
    evidence_covers_implementation = primitive_implemented and set(mutation_fields).issubset(attested_fields)
    verification_covers_implementation = primitive_implemented and set(mutation_fields).issubset(provider_verified_fields)
    verified = bool(
        primitive_implemented
        and attestation.get("attested")
        and evidence_covers_implementation
        and verification_covers_implementation
    )

    if verified:
        state = "verified"
        reason = ""
    elif attestation.get("state") == "invalid":
        state = "invalid"
        reason = str(attestation.get("reason") or "provider_rectification_evidence_invalid")
    elif not primitive_implemented:
        state = "provider_attested" if attestation.get("attested") else "unverified"
        reason = "no_verified_provider_rectification_primitive"
    elif not attestation.get("attested"):
        state = "unverified"
        reason = "provider_rectification_not_attested"
    elif not evidence_covers_implementation:
        state = "unverified"
        reason = "provider_rectification_evidence_does_not_cover_implementation"
    else:
        state = "unverified"
        reason = "provider_backed_verification_incomplete"

    return {
        "provider": "mercure",
        "state": state,
        "verifiedAuthoritativeReadFields": list(VERIFIED_AUTHORITATIVE_READ_FIELDS),
        "verifiedAuthoritativeMutationFields": mutation_fields,
        "providerBackedVerificationFields": list(PROVIDER_BACKED_VERIFICATION_FIELDS),
        "applicationMutationPrimitiveImplemented": primitive_implemented,
        "providerMutationEvidence": attestation,
        "providerMutationCapabilityVerified": verified,
        "completionEligible": verified,
        "observedNonRectificationWrites": observed_non_rectification_writes,
        "syntheticAppointmentWritesCountAsRectificationEvidence": False,
        "requiresExplicitProviderMutationEvidence": True,
        "requiresProviderBackedVerificationTest": True,
        "rawEvidenceStoredInRepository": False,
        "reason": reason,
    }
