from __future__ import annotations

from pathlib import Path

import compliance_store


def _contract_ref(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("contractRef invalide")
    return raw


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
        "partial": True,
    }


def capability() -> dict:
    return {"bound": True, "partial": True, "rights": ["access", "portability"], "crossIdentityBinding": False, "remainingStores": ["booking_conversions"]}
