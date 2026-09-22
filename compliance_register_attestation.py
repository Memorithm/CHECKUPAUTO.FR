from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import compliance_operations
import compliance_store


def _now_iso() -> str:
    return compliance_operations._now_iso()


def init_db(db_path: Path | str | None = None) -> None:
    compliance_operations.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS operational_register_attestation(
              attestation_id TEXT PRIMARY KEY,
              register_hash TEXT NOT NULL,
              reviewed_at TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_register_attestation_reviewed
              ON operational_register_attestation(reviewed_at,attestation_id);
            """
        )


def _stable_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in {"createdAt", "updatedAt", "reviewOverdue"}
    }


def register_payload(db_path: Path | str | None = None) -> dict:
    activities = sorted(
        (_stable_row(row) for row in compliance_operations.processing_activities(db_path)),
        key=lambda row: str(row.get("id") or ""),
    )
    processors = sorted(
        (_stable_row(row) for row in compliance_operations.processors(db_path)),
        key=lambda row: str(row.get("id") or ""),
    )
    return {
        "schema": "checkupauto.operational-registers.v1",
        "processingActivities": activities,
        "processors": processors,
    }


def register_hash(db_path: Path | str | None = None) -> str:
    canonical = json.dumps(
        register_payload(db_path), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attest(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    operations = compliance_operations.summary(db_path)
    if int(operations.get("activeActivityCount") or 0) == 0:
        raise RuntimeError("registre des activités vide")
    if int(operations.get("activeProcessorCount") or 0) == 0:
        raise RuntimeError("inventaire des sous-traitants vide")
    if not bool(operations.get("operationalRegistersReady")):
        raise RuntimeError("registres opérationnels bloqués")

    digest = register_hash(db_path)
    reviewed_at = _now_iso()
    attestation_id = uuid.uuid4().hex
    evidence = {
        "attestationId": attestation_id,
        "registerHash": digest,
        "reviewedAt": reviewed_at,
    }
    evidence_hash = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO operational_register_attestation(
                 attestation_id,register_hash,reviewed_at,evidence_hash,created_at
               ) VALUES(?,?,?,?,?)""",
            (attestation_id, digest, reviewed_at, evidence_hash, reviewed_at),
        )
    return status(db_path)


def status(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    current_hash = register_hash(db_path)
    with compliance_store.connect(db_path) as db:
        latest = db.execute(
            """SELECT attestation_id,register_hash,reviewed_at,evidence_hash
               FROM operational_register_attestation
               ORDER BY reviewed_at DESC,attestation_id DESC LIMIT 1"""
        ).fetchone()
        count = int(db.execute("SELECT COUNT(*) FROM operational_register_attestation").fetchone()[0])
    if not latest:
        return {
            "required": True,
            "current": False,
            "stale": False,
            "currentRegisterHash": current_hash,
            "attestedRegisterHash": "",
            "reviewedAt": "",
            "evidenceHash": "",
            "attestationCount": count,
        }
    attested_hash = str(latest["register_hash"])
    current = attested_hash == current_hash
    return {
        "required": True,
        "current": current,
        "stale": not current,
        "currentRegisterHash": current_hash,
        "attestedRegisterHash": attested_hash,
        "reviewedAt": str(latest["reviewed_at"]),
        "evidenceHash": str(latest["evidence_hash"]),
        "attestationCount": count,
    }
