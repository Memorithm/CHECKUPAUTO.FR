from __future__ import annotations

from pathlib import Path

import analytics_store
import compliance_store


CONTRACT_PROVIDER = "mercure-rdv"


def _contract_ref(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("contractRef invalide")
    return raw


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


def capability() -> dict:
    return {
        "bound": True,
        "partial": True,
        "rights": ["access", "portability"],
        "crossIdentityBinding": False,
        "coveredStores": ["consent_receipts", "checkout_acceptance_intents", "booking_conversions"],
        "remainingStores": [],
    }
