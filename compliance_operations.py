from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from pathlib import Path

import compliance_store


ACTIVITY_ROLES = {"controller", "processor", "joint_controller"}
ACTIVITY_STATUSES = {"active", "inactive"}
RISK_LEVELS = {"standard", "high"}
DPIA_STATUSES = {"not_screened", "not_required", "required_pending", "in_progress", "approved"}
PROCESSOR_STATUSES = {"active", "inactive"}
DPA_STATUSES = {"pending", "signed", "not_required"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _text(value: object, name: str, limit: int, *, required: bool = False) -> str:
    value = str(value or "").strip()
    if required and not value:
        raise ValueError(f"{name} requis")
    if len(value) > limit:
        raise ValueError(f"{name} trop long")
    return value


def _items(value: object, name: str, *, required: bool = False) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError(f"{name} doit être une liste")
    if len(value) > 100:
        raise ValueError(f"{name} contient trop d'éléments")
    result: list[str] = []
    for item in value:
        item = _text(item, name, 300, required=True)
        if item not in result:
            result.append(item)
    if required and not result:
        raise ValueError(f"{name} requis")
    return result


def _date(value: object, name: str, *, required: bool = False) -> str:
    text = _text(value, name, 10, required=required)
    if not text:
        return ""
    try:
        parsed = datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} invalide") from exc
    return parsed.isoformat()


def _json(value: list[str]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_list(value: str) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS processing_activities(
              activity_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              role TEXT NOT NULL,
              purposes_json TEXT NOT NULL,
              data_categories_json TEXT NOT NULL,
              subject_categories_json TEXT NOT NULL,
              legal_bases_json TEXT NOT NULL,
              recipients_json TEXT NOT NULL,
              transfers_json TEXT NOT NULL,
              retention TEXT NOT NULL,
              security_controls_json TEXT NOT NULL,
              systems_json TEXT NOT NULL,
              owner TEXT NOT NULL,
              risk_level TEXT NOT NULL,
              dpia_status TEXT NOT NULL,
              review_due_at TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_processing_activity_status
              ON processing_activities(status,review_due_at);
            CREATE TABLE IF NOT EXISTS processor_inventory(
              processor_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              service TEXT NOT NULL,
              dpa_status TEXT NOT NULL,
              dpa_evidence_sha256 TEXT NOT NULL DEFAULT '',
              hosting_location TEXT NOT NULL,
              transfer_required INTEGER NOT NULL,
              transfer_mechanism TEXT NOT NULL,
              subprocessors_json TEXT NOT NULL,
              review_due_at TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_processor_status
              ON processor_inventory(status,review_due_at);
            CREATE TABLE IF NOT EXISTS compliance_operation_audit(
              event_id TEXT PRIMARY KEY,
              object_type TEXT NOT NULL,
              object_id TEXT NOT NULL,
              action TEXT NOT NULL,
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_compliance_audit_object
              ON compliance_operation_audit(object_type,object_id,created_at);
            """
        )
        processor_columns = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(processor_inventory)")
        }
        if "dpa_evidence_sha256" not in processor_columns:
            db.execute(
                "ALTER TABLE processor_inventory "
                "ADD COLUMN dpa_evidence_sha256 TEXT NOT NULL DEFAULT ''"
            )


def _audit(db, object_type: str, object_id: str, action: str, evidence: dict) -> None:
    canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    db.execute(
        """INSERT INTO compliance_operation_audit(
          event_id,object_type,object_id,action,evidence_hash,created_at
        ) VALUES(?,?,?,?,?,?)""",
        (
            uuid.uuid4().hex,
            object_type,
            object_id,
            action,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            _now_iso(),
        ),
    )


def upsert_processing_activity(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("activité de traitement invalide")
    activity_id = _text(payload.get("id"), "id", 64) or uuid.uuid4().hex
    name = _text(payload.get("name"), "name", 180, required=True)
    role = str(payload.get("role") or "controller").strip()
    if role not in ACTIVITY_ROLES:
        raise ValueError("rôle de traitement invalide")
    status = str(payload.get("status") or "active").strip()
    if status not in ACTIVITY_STATUSES:
        raise ValueError("statut activité invalide")
    risk_level = str(payload.get("riskLevel") or "standard").strip()
    if risk_level not in RISK_LEVELS:
        raise ValueError("niveau de risque invalide")
    dpia_status = str(payload.get("dpiaStatus") or "not_screened").strip()
    if dpia_status not in DPIA_STATUSES:
        raise ValueError("statut AIPD invalide")

    required = status == "active"
    purposes = _items(payload.get("purposes"), "purposes", required=required)
    data_categories = _items(payload.get("dataCategories"), "dataCategories", required=required)
    subject_categories = _items(payload.get("dataSubjects"), "dataSubjects", required=required)
    legal_bases = _items(payload.get("legalBases"), "legalBases", required=required)
    recipients = _items(payload.get("recipients"), "recipients", required=required)
    transfers = _items(payload.get("transfers"), "transfers")
    retention = _text(payload.get("retention"), "retention", 600, required=required)
    security_controls = _items(payload.get("securityControls"), "securityControls", required=required)
    systems = _items(payload.get("systems"), "systems", required=required)
    owner = _text(payload.get("owner"), "owner", 180, required=required)
    review_due = _date(payload.get("reviewDueAt"), "reviewDueAt", required=required)

    init_db(db_path)
    stamp = _now_iso()
    evidence = {
        "id": activity_id,
        "name": name,
        "role": role,
        "purposes": purposes,
        "dataCategories": data_categories,
        "dataSubjects": subject_categories,
        "legalBases": legal_bases,
        "recipients": recipients,
        "transfers": transfers,
        "retention": retention,
        "securityControls": security_controls,
        "systems": systems,
        "owner": owner,
        "riskLevel": risk_level,
        "dpiaStatus": dpia_status,
        "reviewDueAt": review_due,
        "status": status,
    }
    with compliance_store.connect(db_path) as db:
        existing = db.execute(
            "SELECT created_at FROM processing_activities WHERE activity_id=?", (activity_id,)
        ).fetchone()
        created = existing["created_at"] if existing else stamp
        db.execute(
            """INSERT INTO processing_activities(
              activity_id,name,role,purposes_json,data_categories_json,subject_categories_json,
              legal_bases_json,recipients_json,transfers_json,retention,security_controls_json,
              systems_json,owner,risk_level,dpia_status,review_due_at,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(activity_id) DO UPDATE SET
              name=excluded.name,role=excluded.role,purposes_json=excluded.purposes_json,
              data_categories_json=excluded.data_categories_json,
              subject_categories_json=excluded.subject_categories_json,
              legal_bases_json=excluded.legal_bases_json,recipients_json=excluded.recipients_json,
              transfers_json=excluded.transfers_json,retention=excluded.retention,
              security_controls_json=excluded.security_controls_json,systems_json=excluded.systems_json,
              owner=excluded.owner,risk_level=excluded.risk_level,dpia_status=excluded.dpia_status,
              review_due_at=excluded.review_due_at,status=excluded.status,updated_at=excluded.updated_at""",
            (
                activity_id,
                name,
                role,
                _json(purposes),
                _json(data_categories),
                _json(subject_categories),
                _json(legal_bases),
                _json(recipients),
                _json(transfers),
                retention,
                _json(security_controls),
                _json(systems),
                owner,
                risk_level,
                dpia_status,
                review_due,
                status,
                created,
                stamp,
            ),
        )
        _audit(db, "processing_activity", activity_id, "upsert", evidence)
    return next(row for row in processing_activities(db_path) if row["id"] == activity_id)


def processing_activities(db_path: Path | str | None = None) -> list[dict]:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute("SELECT * FROM processing_activities ORDER BY name,activity_id").fetchall()
    today = _now().date()
    return [
        {
            "id": row["activity_id"],
            "name": row["name"],
            "role": row["role"],
            "purposes": _load_list(row["purposes_json"]),
            "dataCategories": _load_list(row["data_categories_json"]),
            "dataSubjects": _load_list(row["subject_categories_json"]),
            "legalBases": _load_list(row["legal_bases_json"]),
            "recipients": _load_list(row["recipients_json"]),
            "transfers": _load_list(row["transfers_json"]),
            "retention": row["retention"],
            "securityControls": _load_list(row["security_controls_json"]),
            "systems": _load_list(row["systems_json"]),
            "owner": row["owner"],
            "riskLevel": row["risk_level"],
            "dpiaStatus": row["dpia_status"],
            "reviewDueAt": row["review_due_at"],
            "reviewOverdue": bool(
                row["status"] == "active"
                and row["review_due_at"]
                and datetime.date.fromisoformat(row["review_due_at"]) < today
            ),
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def upsert_processor(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("sous-traitant invalide")
    processor_id = _text(payload.get("id"), "id", 64) or uuid.uuid4().hex
    name = _text(payload.get("name"), "name", 180, required=True)
    service = _text(payload.get("service"), "service", 300, required=True)
    status = str(payload.get("status") or "active").strip()
    if status not in PROCESSOR_STATUSES:
        raise ValueError("statut sous-traitant invalide")
    dpa_status = str(payload.get("dpaStatus") or "pending").strip()
    if dpa_status not in DPA_STATUSES:
        raise ValueError("statut DPA invalide")
    dpa_evidence_sha256 = str(payload.get("dpaEvidenceSha256") or "").strip().lower()
    if dpa_evidence_sha256 and not _SHA256_RE.fullmatch(dpa_evidence_sha256):
        raise ValueError("empreinte de preuve DPA invalide")
    if dpa_status == "signed" and not dpa_evidence_sha256:
        raise ValueError("preuve DPA requise pour le statut signé")
    if dpa_status != "signed":
        dpa_evidence_sha256 = ""
    hosting_location = _text(payload.get("hostingLocation"), "hostingLocation", 180, required=status == "active")
    raw_transfer_required = payload.get("transferRequired", False)
    if not isinstance(raw_transfer_required, bool):
        raise ValueError("transferRequired doit être booléen")
    transfer_required = raw_transfer_required
    transfer_mechanism = _text(payload.get("transferMechanism"), "transferMechanism", 300)
    if transfer_required and not transfer_mechanism:
        raise ValueError("mécanisme de transfert requis")
    subprocessors = _items(payload.get("subprocessors"), "subprocessors")
    review_due = _date(payload.get("reviewDueAt"), "reviewDueAt", required=status == "active")

    init_db(db_path)
    stamp = _now_iso()
    evidence = {
        "id": processor_id,
        "name": name,
        "service": service,
        "dpaStatus": dpa_status,
        "dpaEvidenceSha256": dpa_evidence_sha256,
        "hostingLocation": hosting_location,
        "transferRequired": transfer_required,
        "transferMechanism": transfer_mechanism,
        "subprocessors": subprocessors,
        "reviewDueAt": review_due,
        "status": status,
    }
    with compliance_store.connect(db_path) as db:
        existing = db.execute(
            "SELECT created_at FROM processor_inventory WHERE processor_id=?", (processor_id,)
        ).fetchone()
        created = existing["created_at"] if existing else stamp
        db.execute(
            """INSERT INTO processor_inventory(
              processor_id,name,service,dpa_status,dpa_evidence_sha256,hosting_location,transfer_required,
              transfer_mechanism,subprocessors_json,review_due_at,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(processor_id) DO UPDATE SET
              name=excluded.name,service=excluded.service,dpa_status=excluded.dpa_status,
              dpa_evidence_sha256=excluded.dpa_evidence_sha256,
              hosting_location=excluded.hosting_location,transfer_required=excluded.transfer_required,
              transfer_mechanism=excluded.transfer_mechanism,subprocessors_json=excluded.subprocessors_json,
              review_due_at=excluded.review_due_at,status=excluded.status,updated_at=excluded.updated_at""",
            (
                processor_id,
                name,
                service,
                dpa_status,
                dpa_evidence_sha256,
                hosting_location,
                int(transfer_required),
                transfer_mechanism,
                _json(subprocessors),
                review_due,
                status,
                created,
                stamp,
            ),
        )
        _audit(db, "processor", processor_id, "upsert", evidence)
    return next(row for row in processors(db_path) if row["id"] == processor_id)


def processors(db_path: Path | str | None = None) -> list[dict]:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute("SELECT * FROM processor_inventory ORDER BY name,processor_id").fetchall()
    today = _now().date()
    return [
        {
            "id": row["processor_id"],
            "name": row["name"],
            "service": row["service"],
            "dpaStatus": row["dpa_status"],
            "dpaEvidenceSha256": str(row["dpa_evidence_sha256"] or ""),
            "hostingLocation": row["hosting_location"],
            "transferRequired": bool(row["transfer_required"]),
            "transferMechanism": row["transfer_mechanism"],
            "subprocessors": _load_list(row["subprocessors_json"]),
            "reviewDueAt": row["review_due_at"],
            "reviewOverdue": bool(
                row["status"] == "active"
                and row["review_due_at"]
                and datetime.date.fromisoformat(row["review_due_at"]) < today
            ),
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def audit_events(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT event_id,object_type,object_id,action,evidence_hash,created_at
               FROM compliance_operation_audit ORDER BY created_at DESC,event_id DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [
        {
            "id": row["event_id"],
            "objectType": row["object_type"],
            "objectId": row["object_id"],
            "action": row["action"],
            "evidenceHash": row["evidence_hash"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def summary(db_path: Path | str | None = None) -> dict:
    activities = processing_activities(db_path)
    processor_rows = processors(db_path)
    blockers: list[dict] = []
    for row in activities:
        if row["status"] != "active":
            continue
        if row["reviewOverdue"]:
            blockers.append({"type": "activity_review_overdue", "id": row["id"], "name": row["name"]})
        if row["riskLevel"] == "high" and row["dpiaStatus"] != "approved":
            blockers.append({"type": "dpia_unresolved", "id": row["id"], "name": row["name"]})
        elif row["dpiaStatus"] == "not_screened":
            blockers.append({"type": "dpia_not_screened", "id": row["id"], "name": row["name"]})
    for row in processor_rows:
        if row["status"] != "active":
            continue
        if row["dpaStatus"] == "pending":
            blockers.append({"type": "processor_dpa_pending", "id": row["id"], "name": row["name"]})
        elif row["dpaStatus"] == "signed" and not row["dpaEvidenceSha256"]:
            blockers.append({"type": "processor_dpa_evidence_missing", "id": row["id"], "name": row["name"]})
        if row["transferRequired"] and not row["transferMechanism"]:
            blockers.append({"type": "processor_transfer_unresolved", "id": row["id"], "name": row["name"]})
        if row["reviewOverdue"]:
            blockers.append({"type": "processor_review_overdue", "id": row["id"], "name": row["name"]})
    return {
        "activityCount": len(activities),
        "activeActivityCount": sum(1 for row in activities if row["status"] == "active"),
        "highRiskActivityCount": sum(
            1 for row in activities if row["status"] == "active" and row["riskLevel"] == "high"
        ),
        "processorCount": len(processor_rows),
        "activeProcessorCount": sum(1 for row in processor_rows if row["status"] == "active"),
        "blockerCount": len(blockers),
        "blockers": blockers,
        "operationalRegistersReady": not blockers,
    }


def snapshot(db_path: Path | str | None = None) -> dict:
    return {
        "ok": True,
        "summary": summary(db_path),
        "processingActivities": processing_activities(db_path),
        "processors": processors(db_path),
        "audit": audit_events(db_path),
    }
