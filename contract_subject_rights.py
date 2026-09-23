from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from pathlib import Path

import compliance_contract_rights
import compliance_store
import data_subject_rights
import mercure_rights
import rights_subject_bindings


ADAPTER = "compliance_contracts"
SUPPORTED_RIGHTS = ("access", "portability")
PARTIAL_ACTION = "export"
COMPLETE_ACTION = "export_complete"


def _verify_mercure_subject(
    row: sqlite3.Row,
    subject_ref: str,
    db_path: Path | str | None = None,
) -> None:
    mercure_rights.parse_subject_ref(subject_ref)
    digest = hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()
    if hmac.compare_digest(str(row["subject_ref_hash"]), digest):
        return
    if rights_subject_bindings.is_bound(
        str(row["request_id"]),
        rights_subject_bindings.MERCURE_CONTACT_ADAPTER,
        subject_ref,
        db_path,
    ):
        return
    raise PermissionError("référence Mercure du demandeur refusée")


def _actions(request_id: str, db_path: Path | str | None = None) -> set[str]:
    data_subject_rights._init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            "SELECT action FROM rights_execution_audit WHERE request_id=? AND adapter=?",
            (request_id, ADAPTER),
        ).fetchall()
    return {str(row["action"]) for row in rows}


def _audit(
    row: sqlite3.Row,
    action: str,
    evidence: dict,
    db_path: Path | str | None = None,
) -> str:
    """Record retryable subject-wide contract evidence with race-safe completion."""
    data_subject_rights._init_audit(db_path)
    canonical = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    execution_id = uuid.uuid4().hex
    stamp = data_subject_rights._now_iso()
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT status FROM rights_requests WHERE request_id=?",
            (row["request_id"],),
        ).fetchone()
        if not current or str(current["status"]) not in {"open", "in_progress"}:
            raise RuntimeError("demande non exécutable")
        previous = {
            str(item["action"])
            for item in db.execute(
                "SELECT action FROM rights_execution_audit WHERE request_id=? AND adapter=?",
                (row["request_id"], ADAPTER),
            ).fetchall()
        }
        if COMPLETE_ACTION in previous:
            raise RuntimeError("adaptateur déjà exécuté complètement pour cette demande")
        db.execute(
            """INSERT INTO rights_execution_audit(
                 execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                execution_id,
                row["request_id"],
                row["request_type"],
                ADAPTER,
                action,
                evidence_hash,
                stamp,
            ),
        )
        db.execute(
            "UPDATE rights_requests SET status='in_progress',closed_at='' WHERE request_id=?",
            (row["request_id"],),
        )
    return execution_id


def execute(
    request_id: object,
    subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    """Execute a subject-wide contract export when a Mercure identity is proven.

    A non-Mercure subject keeps the legacy exact-contract behavior. A Mercure
    subject may be retried after partial provider/evidence coverage and becomes
    permanently complete only after ``subject_snapshot`` proves both the complete
    appointment boundary and the independent subject-to-contract attestation.
    """
    rid = data_subject_rights._request_id(request_id)
    ref = str(subject_ref or "").strip()
    try:
        mercure_rights.parse_subject_ref(ref)
    except ValueError:
        return data_subject_rights.execute(
            rid,
            ref,
            adapter=ADAPTER,
            db_path=db_path,
        )

    row = data_subject_rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    request_type = str(row["request_type"])
    if request_type not in SUPPORTED_RIGHTS:
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")
    _verify_mercure_subject(row, ref, db_path)
    if COMPLETE_ACTION in _actions(rid, db_path):
        raise RuntimeError("adaptateur déjà exécuté complètement pour cette demande")

    provider_snapshot = mercure_rights.contact_snapshot(ref)
    data = compliance_contract_rights.subject_snapshot(provider_snapshot, db_path)
    complete = bool(data.get("coverageComplete"))
    action = COMPLETE_ACTION if complete else PARTIAL_ACTION
    evidence = {
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "partial": not complete,
        "coverageComplete": complete,
        "providerAppointmentsComplete": bool(data.get("providerAppointmentsComplete")),
        "subjectInventoryAttested": bool(
            (data.get("subjectInventory") or {}).get("attested")
        ),
        "contractCount": int(data.get("contractCount") or 0),
        "exportHash": hashlib.sha256(
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    execution_id = _audit(row, action, evidence, db_path)
    return {
        "ok": True,
        "requestId": rid,
        "requestType": request_type,
        "adapter": ADAPTER,
        "format": "application/json",
        "data": data,
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }


def capability() -> dict:
    return {
        "adapter": ADAPTER,
        "supportedRights": list(SUPPORTED_RIGHTS),
        "subjectWideExportReady": True,
        "completeAction": COMPLETE_ACTION,
        "partialRetryAllowedUntilComplete": True,
        "requiresVerifiedMercureSubject": True,
        "legacyExactContractFallback": True,
        "rawSubjectReferencePersisted": False,
        "auditStoresEvidenceHashOnly": True,
    }
