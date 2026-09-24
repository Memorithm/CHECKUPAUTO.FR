from __future__ import annotations

import mercure_admin_client as mercure


# Provider data we have actually observed through bounded read paths. These names
# describe application semantics, not undocumented Mercure field names.
VERIFIED_AUTHORITATIVE_READ_FIELDS = (
    "contact.email",
    "contact.telephone",
    "vehicle.technicalInspectionDueDate",
)

# Deliberately empty until a provider-backed mutation route is both documented
# and implemented with verification. Synthetic appointment writes are not proof
# that Mercure supports authoritative customer/vehicle rectification.
VERIFIED_AUTHORITATIVE_MUTATION_FIELDS: tuple[str, ...] = ()

_NON_RECTIFICATION_WRITE_PRIMITIVES = (
    ("synthetic_appointment_create", "create_synthetic_test_appointment"),
    ("synthetic_appointment_remove", "remove_synthetic_test_appointment"),
)


def capability() -> dict:
    """Expose the verified Mercure rectification boundary without inference.

    The admin client can create/remove synthetic appointments for operational
    probes, but no repository code currently proves an authoritative write path
    for the contact fields or technical-inspection due date read from Mercure.
    A future provider mutation must update this boundary explicitly and add a
    read-after-write or equivalent provider-backed verification test.
    """
    observed_non_rectification_writes = [
        semantic
        for semantic, attribute in _NON_RECTIFICATION_WRITE_PRIMITIVES
        if callable(getattr(mercure, attribute, None))
    ]
    mutation_fields = list(VERIFIED_AUTHORITATIVE_MUTATION_FIELDS)
    primitive_implemented = bool(mutation_fields)
    return {
        "provider": "mercure",
        "state": "verified" if primitive_implemented else "unverified",
        "verifiedAuthoritativeReadFields": list(VERIFIED_AUTHORITATIVE_READ_FIELDS),
        "verifiedAuthoritativeMutationFields": mutation_fields,
        "applicationMutationPrimitiveImplemented": primitive_implemented,
        "providerMutationCapabilityVerified": primitive_implemented,
        "completionEligible": primitive_implemented,
        "observedNonRectificationWrites": observed_non_rectification_writes,
        "syntheticAppointmentWritesCountAsRectificationEvidence": False,
        "requiresExplicitProviderMutationEvidence": True,
        "requiresProviderBackedVerificationTest": True,
        "reason": "" if primitive_implemented else "no_verified_provider_rectification_primitive",
    }
