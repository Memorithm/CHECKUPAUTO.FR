from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import sqlite3
import uuid
from pathlib import Path

import compliance_contract_rights
import compliance_store
import mercure_rights
import mobile_devices


MERCURE_CONTACT_ADAPTER = "mercure_customer_contact"
COMPLIANCE_CONTRACT_ADAPTER = "compliance_contracts"
MOBILE_BINDING_PROVENANCE = "mobile_vehicle_binding"
MERCURE_APPOINTMENT_PROVENANCE = "mercure_appointment"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 32:
        raise ValueError("requestId invalide")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise ValueError("requestId invalide") from exc
    return raw


def _installation_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("installationId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("installationId invalide")
    return raw


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS rights_subject_binding(
              request_id TEXT NOT NULL,
              adapter TEXT NOT NULL,
              subject_ref_hash TEXT NOT NULL,
              provenance TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(request_id,adapter,subject_ref_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_rights_subject_binding_request
              ON rights_subject_binding(request_id,adapter,created_at);
            """
        )


def is_bound(
    request_id: str,
    adapter: str,
    subject_ref: str,
    db_path: Path | str | None = None,
) -> bool:
    init_db(db_path)
    digest = _hash(subject_ref)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            "SELECT subject_ref_hash FROM rights_subject_binding WHERE request_id=? AND adapter=?",
            (request_id, adapter),
        ).fetchall()
    return any(hmac.compare_digest(str(row["subject_ref_hash"]), digest) for row in rows)


def _open_request(request_id: str, db_path: Path | str | None = None) -> sqlite3.Row:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        request = db.execute(
            "SELECT status,subject_ref_hash FROM rights_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
    if not request:
        raise LookupError("demande inconnue")
    if str(request["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    return request


def _persist_binding(
    request_id: str,
    adapter: str,
    subject_ref: str,
    provenance: str,
    evidence: dict,
    db_path: Path | str | None = None,
) -> None:
    evidence_hash = _hash(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    stamp = _now_iso()
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO rights_subject_binding(
                 request_id,adapter,subject_ref_hash,provenance,evidence_hash,created_at
               ) VALUES(?,?,?,?,?,?)
               ON CONFLICT(request_id,adapter,subject_ref_hash) DO UPDATE SET
                 provenance=excluded.provenance,
                 evidence_hash=excluded.evidence_hash,
                 created_at=excluded.created_at""",
            (request_id, adapter, _hash(subject_ref), provenance, evidence_hash, stamp),
        )


def bind_mercure_from_mobile(
    request_id: str,
    installation_id: object,
    mercure_subject_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    """Bind a Mercure subject to a rights request using an existing mobile claim.

    Both raw identifiers are supplied at execution time. Only SHA-256 values and
    non-identifying provenance evidence are persisted in the compliance store.
    The binding is accepted only if ``mobile_vehicle_binding`` already proves the
    same installation -> Mercure customer relation.
    """
    request_id = _request_id(request_id)
    installation = _installation_id(installation_id)
    mercure_ref = str(mercure_subject_ref or "").strip()
    client_kind, client_id = mercure_rights.parse_subject_ref(mercure_ref)

    request = _open_request(request_id, db_path)
    if not hmac.compare_digest(str(request["subject_ref_hash"]), _hash(installation)):
        raise PermissionError("référence du demandeur refusée")

    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        rows = db.execute(
            """SELECT binding_id FROM mobile_vehicle_binding
               WHERE installation_id=? AND client_kind=? AND client_id=?""",
            (installation, client_kind, client_id),
        ).fetchall()
    if not rows:
        raise PermissionError("liaison Mercure non prouvée")

    evidence = {
        "requestId": request_id,
        "adapter": MERCURE_CONTACT_ADAPTER,
        "provenance": MOBILE_BINDING_PROVENANCE,
        "bindingCount": len(rows),
    }
    _persist_binding(
        request_id,
        MERCURE_CONTACT_ADAPTER,
        mercure_ref,
        MOBILE_BINDING_PROVENANCE,
        evidence,
        db_path,
    )
    return {
        "bound": True,
        "adapter": MERCURE_CONTACT_ADAPTER,
        "provenance": MOBILE_BINDING_PROVENANCE,
        "bindingCount": len(rows),
        "rawSubjectReferencePersisted": False,
    }


def bind_contract_from_mercure(
    request_id: object,
    mercure_subject_ref: object,
    contract_ref: object,
    db_path: Path | str | None = None,
) -> dict:
    """Bind local contract evidence only after Mercure proves appointment ownership.

    The Mercure subject must already be the request subject or have a previously
    proven binding (for example through ``mobile_vehicle_binding``). A contract is
    then accepted only when the live, privacy-bounded Mercure inventory contains
    the exact appointment identifier *and* CheckupAuto has a finalized checkout
    acceptance for that exact contract reference. Only hashes and aggregate proof
    metadata are persisted; neither raw identifier is stored in the binding table.
    """
    rid = _request_id(request_id)
    mercure_ref = str(mercure_subject_ref or "").strip()
    mercure_rights.parse_subject_ref(mercure_ref)
    contract = compliance_contract_rights._contract_ref(contract_ref)
    request = _open_request(rid, db_path)

    mercure_primary = hmac.compare_digest(str(request["subject_ref_hash"]), _hash(mercure_ref))
    mercure_bound = is_bound(rid, MERCURE_CONTACT_ADAPTER, mercure_ref, db_path)
    if not (mercure_primary or mercure_bound):
        raise PermissionError("référence Mercure du demandeur refusée")

    mercure_snapshot = mercure_rights.contact_snapshot(mercure_ref)
    inventory = mercure_snapshot.get("operationalInventory") or {}
    if not isinstance(inventory, dict) or inventory.get("state") != "available":
        raise RuntimeError("inventaire Mercure indisponible pour la preuve contractuelle")
    appointments = inventory.get("appointments") or []
    matches = [
        item for item in appointments
        if isinstance(item, dict) and str(item.get("appointmentId") or "") == contract
    ]
    if not matches:
        raise PermissionError("contrat non prouvé pour ce client Mercure")

    contract_snapshot = compliance_contract_rights.snapshot(contract, db_path)
    acceptances = contract_snapshot.get("checkoutAcceptances") or []
    if not acceptances:
        raise PermissionError("acceptation contractuelle locale non prouvée")

    evidence = {
        "requestId": rid,
        "adapter": COMPLIANCE_CONTRACT_ADAPTER,
        "provenance": MERCURE_APPOINTMENT_PROVENANCE,
        "appointmentMatchCount": len(matches),
        "checkoutAcceptanceCount": len(acceptances),
    }
    _persist_binding(
        rid,
        COMPLIANCE_CONTRACT_ADAPTER,
        contract,
        MERCURE_APPOINTMENT_PROVENANCE,
        evidence,
        db_path,
    )
    return {
        "bound": True,
        "adapter": COMPLIANCE_CONTRACT_ADAPTER,
        "provenance": MERCURE_APPOINTMENT_PROVENANCE,
        "appointmentMatchCount": len(matches),
        "checkoutAcceptanceCount": len(acceptances),
        "rawSubjectReferencePersisted": False,
    }


def rows(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    """Return non-identifying binding metadata for audits and diagnostics."""
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        records = db.execute(
            """SELECT request_id,adapter,provenance,evidence_hash,created_at
               FROM rights_subject_binding ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [
        {
            "requestId": str(row["request_id"]),
            "adapter": str(row["adapter"]),
            "provenance": str(row["provenance"]),
            "evidenceHash": str(row["evidence_hash"]),
            "createdAt": str(row["created_at"]),
        }
        for row in records
    ]
