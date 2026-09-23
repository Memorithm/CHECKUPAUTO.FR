from __future__ import annotations

import os
import re
from pathlib import Path

import analytics_store
import compliance_store


CONTRACT_PROVIDER = "mercure-rdv"
SUBJECT_INVENTORY_SOURCE_ENV = "CYBERCHECK_CONTRACT_DSAR_SUBJECT_INVENTORY_SOURCE"
SUBJECT_INVENTORY_EVIDENCE_SHA256_ENV = (
    "CYBERCHECK_CONTRACT_DSAR_SUBJECT_INVENTORY_EVIDENCE_SHA256"
)
AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE = "mercure_complete_appointment_contract_index"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _contract_ref(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("contractRef invalide")
    return raw


def subject_inventory_attestation() -> dict:
    """Return external evidence for the subject-to-all-contracts boundary.

    A single contract reference can be safely exported, but it does not prove
    that every contract belonging to the data subject has been discovered. A
    subject-wide DSAR may only promote this adapter to complete after external
    provider/contract evidence attests that the complete Mercure appointment
    inventory is also the authoritative index of CheckupAuto contract refs.
    Only the evidence SHA-256 is exposed; the evidence body stays outside Git.
    """
    source_raw = os.environ.get(SUBJECT_INVENTORY_SOURCE_ENV, "").strip().lower()
    evidence_raw = os.environ.get(
        SUBJECT_INVENTORY_EVIDENCE_SHA256_ENV, ""
    ).strip().lower()

    if not source_raw and not evidence_raw:
        return {
            "state": "unconfigured",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "contract_subject_inventory_not_attested",
        }
    if not source_raw or not evidence_raw:
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "contract_subject_inventory_configuration_incomplete",
        }
    if source_raw != AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE:
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "contract_subject_inventory_source_unsupported",
        }
    if not _SHA256_RE.fullmatch(evidence_raw):
        return {
            "state": "invalid",
            "attested": False,
            "source": "",
            "evidenceSha256": "",
            "reason": "contract_subject_inventory_evidence_hash_invalid",
        }
    return {
        "state": "attested",
        "attested": True,
        "source": AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE,
        "evidenceSha256": evidence_raw,
        "reason": "",
    }


def _booking_conversions(contract_ref: str) -> list[dict]:
    """Return only the Mercure conversion bound to this contract reference.

    ``external_id`` is not globally namespaced in analytics: another provider may
    legally reuse the same opaque identifier. Contract evidence originates from
    the Mercure checkout/finalisation path, so rights exports must constrain both
    provider and external identifier to avoid cross-provider disclosure.
    """
    if not Path(analytics_store.DB).exists():
        return []
    with analytics_store.connect() as db:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='booking_conversions'"
        ).fetchone()
        if not table:
            return []
        columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(booking_conversions)")}
        referral_expr = "referral_code" if "referral_code" in columns else "'' AS referral_code"
        rows = db.execute(
            f"""SELECT provider,external_id,status,first_seen_at,updated_at,confirmed_at,
                       appointment_at,amount_cents,service,source,campaign,device,{referral_expr}
                FROM booking_conversions WHERE provider=? AND external_id=?
                ORDER BY first_seen_at,provider""",
            (CONTRACT_PROVIDER, contract_ref),
        ).fetchall()
    return [{
        "provider": str(r["provider"]),
        "externalId": str(r["external_id"]),
        "status": str(r["status"]),
        "firstSeenAt": str(r["first_seen_at"]),
        "updatedAt": str(r["updated_at"]),
        "confirmedAt": str(r["confirmed_at"] or ""),
        "appointmentAt": str(r["appointment_at"] or ""),
        "amountCents": int(r["amount_cents"] or 0),
        "service": str(r["service"] or ""),
        "source": str(r["source"] or ""),
        "campaign": str(r["campaign"] or ""),
        "device": str(r["device"] or ""),
        "referralCode": str(r["referral_code"] or ""),
    } for r in rows]


def snapshot(contract_ref: object, db_path: Path | str | None = None) -> dict:
    ref = _contract_ref(contract_ref)
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        receipts = db.execute(
            "SELECT purpose,document_type,document_version,content_hash,accepted_at,immediate_performance,source FROM consent_receipts WHERE contract_ref=? ORDER BY accepted_at,receipt_id",
            (ref,),
        ).fetchall()
        acceptances = db.execute(
            "SELECT terms_version,terms_content_hash,accepted_at,reviewed,immediate_performance,source,finalized_at FROM checkout_acceptance_intents WHERE finalized_contract_ref=? ORDER BY accepted_at,finalized_at",
            (ref,),
        ).fetchall()
    return {
        "contractRef": ref,
        "consentReceipts": [{
            "purpose": str(r["purpose"]), "documentType": str(r["document_type"]),
            "documentVersion": str(r["document_version"]), "contentHash": str(r["content_hash"]),
            "acceptedAt": str(r["accepted_at"]), "immediatePerformance": bool(r["immediate_performance"]),
            "source": str(r["source"]),
        } for r in receipts],
        "checkoutAcceptances": [{
            "termsVersion": str(r["terms_version"]), "termsContentHash": str(r["terms_content_hash"]),
            "acceptedAt": str(r["accepted_at"]), "reviewed": bool(r["reviewed"]),
            "immediatePerformance": bool(r["immediate_performance"]), "source": str(r["source"]),
            "finalizedAt": str(r["finalized_at"]),
        } for r in acceptances],
        "bookingConversions": _booking_conversions(ref),
        "partial": True,
    }


def subject_snapshot(provider_snapshot: object, db_path: Path | str | None = None) -> dict:
    """Export every known contract behind a proven Mercure appointment inventory.

    This primitive deliberately accepts the already privacy-bounded Mercure
    snapshot rather than talking to the provider itself. Completeness is asserted
    only when Mercure proved the appointment inventory exhaustive *and* separate
    external evidence attests that this complete appointment set is the
    authoritative subject-to-contract index. Any mismatch stays partial.
    """
    if not isinstance(provider_snapshot, dict):
        raise ValueError("snapshot Mercure invalide")
    coverage = provider_snapshot.get("coverage") or {}
    inventory = provider_snapshot.get("operationalInventory") or {}
    if not isinstance(coverage, dict) or not isinstance(inventory, dict):
        raise ValueError("snapshot Mercure invalide")

    rows = inventory.get("appointments") or []
    if not isinstance(rows, list):
        raise ValueError("inventaire de contrats invalide")
    refs: list[str] = []
    invalid_ref = False
    for item in rows:
        if not isinstance(item, dict):
            invalid_ref = True
            continue
        try:
            ref = _contract_ref(item.get("appointmentId"))
        except ValueError:
            invalid_ref = True
            continue
        if ref not in refs:
            refs.append(ref)

    try:
        expected_count = int(inventory.get("appointmentCountInWindow") or 0)
    except (TypeError, ValueError):
        expected_count = -1
    appointments_complete = bool(
        coverage.get("appointments") is True
        and inventory.get("state") == "available"
        and not inventory.get("appointmentsTruncated")
        and int(inventory.get("appointmentIdsMissing") or 0) == 0
        and expected_count == len(refs)
        and not invalid_ref
    )
    attestation = subject_inventory_attestation()
    coverage_complete = bool(appointments_complete and attestation.get("attested"))
    contracts = [snapshot(ref, db_path) for ref in refs]
    return {
        "provider": CONTRACT_PROVIDER,
        "contracts": contracts,
        "contractCount": len(contracts),
        "providerAppointmentsComplete": appointments_complete,
        "subjectInventory": {
            "state": str(attestation.get("state") or "invalid"),
            "attested": bool(attestation.get("attested")),
            "source": str(attestation.get("source") or ""),
            "evidenceSha256": str(attestation.get("evidenceSha256") or ""),
            "reason": str(attestation.get("reason") or ""),
        },
        "coverageComplete": coverage_complete,
        "partial": not coverage_complete,
    }


def capability() -> dict:
    attestation = subject_inventory_attestation()
    return {
        "bound": True,
        "partial": True,
        "rights": ["access", "portability"],
        "crossIdentityBinding": False,
        "coveredStores": ["consent_receipts", "checkout_acceptance_intents", "booking_conversions"],
        "remainingStores": [],
        "subjectWideExportPrimitiveReady": True,
        "requiresSubjectInventoryAttestation": True,
        "authoritativeSubjectInventorySource": AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE,
        "subjectInventoryAttestation": attestation,
        "rawEvidenceStoredInRepository": False,
        "singleContractExportProvesSubjectExhaustion": False,
    }
