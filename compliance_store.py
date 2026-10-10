from __future__ import annotations

import calendar
import datetime
import hashlib
import json
import os
import re
import sqlite3
import uuid

import legacy_legal_baseline
from pathlib import Path
from urllib.parse import urlparse


DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "compliance.sqlite3"

DOCUMENT_TYPES = {
    "legal_notice": {"label": "Mentions légales", "slug": "/mentions-legales"},
    "privacy": {"label": "Politique de confidentialité", "slug": "/confidentialite"},
    "cookies": {"label": "Politique cookies & traceurs", "slug": "/cookies"},
    "terms": {"label": "Conditions générales de vente", "slug": "/cgv"},
    "withdrawal": {"label": "Rétractation", "slug": "/retractation"},
}
SLUG_TO_DOCUMENT = {meta["slug"]: key for key, meta in DOCUMENT_TYPES.items()}

SETTINGS_FIELDS = (
    "controllerName",
    "legalForm",
    "capital",
    "registeredAddress",
    "registrationId",
    "vatNumber",
    "publicationDirector",
    "contactEmail",
    "privacyContact",
    "mediatorName",
    "mediatorUrl",
    "mediatorAddress",
    "hostName",
    "hostAddress",
    "hostPhone",
    "approvalAuthority",
    "approvalReference",
)
REQUIRED_IDENTITY_FIELDS = (
    "controllerName",
    "legalForm",
    "registeredAddress",
    "registrationId",
    "publicationDirector",
    "contactEmail",
    "privacyContact",
    "mediatorName",
    "mediatorUrl",
    "hostName",
    "hostAddress",
    "approvalAuthority",
)

COOKIE_CATEGORIES = {"necessary", "preferences", "analytics", "marketing", "external_media"}
STORAGE_KINDS = {"cookie", "local_storage", "session_storage", "sdk", "none"}
RIGHT_TYPES = {"access", "rectification", "erasure", "restriction", "portability", "objection", "consent_withdrawal"}
RIGHT_STATES = {"open", "in_progress", "closed", "rejected"}
INCIDENT_RISKS = {"none", "low", "risk", "high_risk"}
INCIDENT_STATES = {"open", "contained", "notified", "closed"}

# Operational defaults are deliberately explicit and editable at implementation level.
# "activeDays=None" means event-triggered retention rather than a fixed duration.
RETENTION_POLICIES = (
    {
        "id": "accounting_records",
        "category": "Factures et pièces comptables",
        "purpose": "Obligations comptables et preuve",
        "legalBasis": "legal_obligation",
        "trigger": "date de clôture / émission",
        "activeDays": 3650,
        "archiveDays": 0,
    },
    {
        "id": "customer_prospecting",
        "category": "Prospection clients",
        "purpose": "Communication commerciale autorisée",
        "legalBasis": "consent_or_customer_exception",
        "trigger": "fin de relation commerciale / dernier contact",
        "activeDays": 1095,
        "archiveDays": 0,
    },
    {
        "id": "prospect_data",
        "category": "Prospects",
        "purpose": "Prospection commerciale",
        "legalBasis": "consent_or_legitimate_interest_as_applicable",
        "trigger": "collecte / dernier contact du prospect",
        "activeDays": 1095,
        "archiveDays": 0,
    },
)


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


def _https_url(value: object, name: str, *, required: bool = False) -> str:
    value = _text(value, name, 500, required=required)
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{name} doit utiliser HTTPS")
    return value


def _calendar_month_later(value: datetime.datetime) -> datetime.datetime:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def runtime_db_path() -> Path:
    data_dir = Path(os.environ.get("CYBERCHECK_DATA_DIR", str(DATA_DIR)))
    return data_dir / "compliance.sqlite3"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path is not None else runtime_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except PermissionError:
        pass
    db = sqlite3.connect(target, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db(db_path: Path | str | None = None) -> None:
    target = Path(db_path) if db_path is not None else runtime_db_path()
    with connect(target) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS compliance_settings(
              id INTEGER PRIMARY KEY CHECK(id=1),
              payload TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS legal_documents(
              document_type TEXT NOT NULL,
              version TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              published_at TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(document_type,version)
            );
            CREATE INDEX IF NOT EXISTS idx_legal_document_status
              ON legal_documents(document_type,status,published_at);
            CREATE TABLE IF NOT EXISTS cookie_registry(
              cookie_key TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              purpose TEXT NOT NULL,
              category TEXT NOT NULL,
              legal_basis TEXT NOT NULL,
              duration_days INTEGER NOT NULL,
              storage_kind TEXT NOT NULL,
              essential INTEGER NOT NULL,
              enabled INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rights_requests(
              request_id TEXT PRIMARY KEY,
              request_type TEXT NOT NULL,
              status TEXT NOT NULL,
              subject_ref_hash TEXT NOT NULL,
              received_at TEXT NOT NULL,
              due_at TEXT NOT NULL,
              closed_at TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_rights_due ON rights_requests(status,due_at);
            CREATE TABLE IF NOT EXISTS data_incidents(
              incident_id TEXT PRIMARY KEY,
              risk_level TEXT NOT NULL,
              status TEXT NOT NULL,
              detected_at TEXT NOT NULL,
              cnil_due_at TEXT NOT NULL DEFAULT '',
              notified_at TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL,
              notes TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_incident_due ON data_incidents(status,cnil_due_at);
            CREATE TABLE IF NOT EXISTS consent_receipts(
              receipt_id TEXT PRIMARY KEY,
              contract_ref TEXT NOT NULL,
              purpose TEXT NOT NULL,
              document_type TEXT NOT NULL,
              document_version TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              accepted_at TEXT NOT NULL,
              immediate_performance INTEGER NOT NULL DEFAULT 0,
              source TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_consent_contract ON consent_receipts(contract_ref,accepted_at);
            CREATE TABLE IF NOT EXISTS checkout_acceptance_intents(
              booking_token_hash TEXT PRIMARY KEY,
              terms_version TEXT NOT NULL,
              terms_content_hash TEXT NOT NULL,
              accepted_at TEXT NOT NULL,
              reviewed INTEGER NOT NULL,
              immediate_performance INTEGER NOT NULL DEFAULT 0,
              source TEXT NOT NULL,
              finalized_contract_ref TEXT NOT NULL DEFAULT '',
              finalized_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_checkout_acceptance_finalized
              ON checkout_acceptance_intents(finalized_contract_ref,finalized_at);
            """
        )
        row = db.execute("SELECT 1 FROM compliance_settings WHERE id=1").fetchone()
        if not row:
            db.execute(
                "INSERT INTO compliance_settings(id,payload,updated_at) VALUES(1,?,?)",
                (json.dumps({key: "" for key in SETTINGS_FIELDS}, ensure_ascii=False), _now_iso()),
            )
    try:
        target.chmod(0o600)
    except PermissionError:
        pass


def settings(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    with connect(db_path) as db:
        row = db.execute("SELECT payload,updated_at FROM compliance_settings WHERE id=1").fetchone()
    payload = json.loads(row["payload"]) if row else {}
    out = {key: str(payload.get(key) or "") for key in SETTINGS_FIELDS}
    out["updatedAt"] = str(row["updated_at"] if row else "")
    return out


def save_settings(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("configuration conformité invalide")
    current = settings(db_path)
    updated = {}
    for key in SETTINGS_FIELDS:
        updated[key] = _text(payload.get(key, current.get(key, "")), key, 500)
    updated["mediatorUrl"] = _https_url(updated["mediatorUrl"], "mediatorUrl")
    for key in ("contactEmail", "privacyContact"):
        if updated[key] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", updated[key]):
            raise ValueError(f"{key} invalide")
    stamp = _now_iso()
    with connect(db_path) as db:
        db.execute(
            "UPDATE compliance_settings SET payload=?,updated_at=? WHERE id=1",
            (json.dumps(updated, ensure_ascii=False, sort_keys=True), stamp),
        )
    return settings(db_path)


def _document_row(row: sqlite3.Row) -> dict:
    return {
        "type": row["document_type"],
        "label": DOCUMENT_TYPES[row["document_type"]]["label"],
        "slug": DOCUMENT_TYPES[row["document_type"]]["slug"],
        "version": row["version"],
        "title": row["title"],
        "body": row["body"],
        "contentHash": row["content_hash"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "publishedAt": row["published_at"],
    }


def save_document(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("document invalide")
    doc_type = str(payload.get("type") or "").strip()
    if doc_type not in DOCUMENT_TYPES:
        raise ValueError("type de document invalide")
    version = _text(payload.get("version"), "version", 32, required=True)
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]{0,31}", version):
        raise ValueError("version invalide")
    title = _text(payload.get("title"), "title", 180, required=True)
    body = _text(payload.get("body"), "body", 50000, required=True)
    if len(body) < 80:
        raise ValueError("document trop court")
    action = str(payload.get("action") or "save").strip().lower()
    if action not in {"save", "publish"}:
        raise ValueError("action document invalide")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    stamp = _now_iso()
    init_db(db_path)
    with connect(db_path) as db:
        existing = db.execute(
            "SELECT status FROM legal_documents WHERE document_type=? AND version=?",
            (doc_type, version),
        ).fetchone()
        if existing and existing["status"] in {"published", "retired"}:
            raise ValueError("une version déjà publiée est immuable")
        db.execute(
            """INSERT INTO legal_documents(document_type,version,title,body,content_hash,status,created_at,published_at)
               VALUES(?,?,?,?,?,'draft',?,'')
               ON CONFLICT(document_type,version) DO UPDATE SET
                 title=excluded.title,body=excluded.body,content_hash=excluded.content_hash""",
            (doc_type, version, title, body, digest, stamp),
        )
        if action == "publish":
            db.execute(
                "UPDATE legal_documents SET status='retired' WHERE document_type=? AND status='published'",
                (doc_type,),
            )
            db.execute(
                "UPDATE legal_documents SET status='published',published_at=? WHERE document_type=? AND version=?",
                (stamp, doc_type, version),
            )
        row = db.execute(
            "SELECT * FROM legal_documents WHERE document_type=? AND version=?",
            (doc_type, version),
        ).fetchone()
    return _document_row(row)


def documents(db_path: Path | str | None = None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT * FROM legal_documents
               ORDER BY document_type,
                 CASE status WHEN 'published' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
                 published_at DESC, created_at DESC"""
        ).fetchall()
    return [_document_row(row) for row in rows]


def published_document(doc_type: str, db_path: Path | str | None = None) -> dict | None:
    if doc_type not in DOCUMENT_TYPES:
        return None
    init_db(db_path)
    with connect(db_path) as db:
        row = db.execute(
            """SELECT * FROM legal_documents
               WHERE document_type=? AND status='published'
               ORDER BY published_at DESC LIMIT 1""",
            (doc_type,),
        ).fetchone()
    return _document_row(row) if row else None


def _test_or_placeholder_document(row: dict | None) -> bool:
    if not row:
        return False
    version = str(row.get("version") or "").strip().casefold()
    title = str(row.get("title") or "").strip().casefold()
    body = str(row.get("body") or "").strip().casefold()
    if re.match(r"^(test|draft|demo|provisoire)(?:[._-]|$)", version):
        return True
    markers = (
        "test uniquement",
        "environnement de test uniquement",
        "cgv provisoires",
        "cgv de substitution",
        "document juridique non publie",
        "document juridique non publié",
    )
    return any(marker in title or marker in body for marker in markers)


def public_document_for_path(path: str, db_path: Path | str | None = None) -> dict | None:
    doc_type = SLUG_TO_DOCUMENT.get(str(path or ""))
    if not doc_type:
        return None
    current = published_document(doc_type, db_path)
    if current and not _test_or_placeholder_document(current):
        return current
    return legacy_legal_baseline.document(doc_type) or current


def upsert_cookie(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("traceur invalide")
    key = _text(payload.get("key"), "key", 120, required=True)
    provider = _text(payload.get("provider"), "provider", 120, required=True)
    purpose = _text(payload.get("purpose"), "purpose", 600, required=True)
    category = str(payload.get("category") or "").strip()
    if category not in COOKIE_CATEGORIES:
        raise ValueError("catégorie traceur invalide")
    storage_kind = str(payload.get("storageKind") or "cookie").strip()
    if storage_kind not in STORAGE_KINDS:
        raise ValueError("stockage traceur invalide")
    essential = bool(payload.get("essential"))
    enabled = bool(payload.get("enabled", True))
    legal_basis = _text(payload.get("legalBasis"), "legalBasis", 80, required=True)
    if enabled and not essential and storage_kind != "none" and legal_basis != "consent":
        raise ValueError("un traceur non essentiel actif doit reposer sur le consentement")
    try:
        duration = int(payload.get("durationDays", 0))
    except Exception as exc:
        raise ValueError("durée traceur invalide") from exc
    if duration < 0 or duration > 4000:
        raise ValueError("durée traceur invalide")
    stamp = _now_iso()
    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO cookie_registry(cookie_key,provider,purpose,category,legal_basis,duration_days,storage_kind,essential,enabled,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(cookie_key) DO UPDATE SET
                 provider=excluded.provider,purpose=excluded.purpose,category=excluded.category,
                 legal_basis=excluded.legal_basis,duration_days=excluded.duration_days,
                 storage_kind=excluded.storage_kind,essential=excluded.essential,
                 enabled=excluded.enabled,updated_at=excluded.updated_at""",
            (key, provider, purpose, category, legal_basis, duration, storage_kind, int(essential), int(enabled), stamp),
        )
    return next(item for item in cookies(db_path) if item["key"] == key)


def cookies(db_path: Path | str | None = None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as db:
        rows = db.execute("SELECT * FROM cookie_registry ORDER BY category,cookie_key").fetchall()
    return [
        {
            "key": row["cookie_key"],
            "provider": row["provider"],
            "purpose": row["purpose"],
            "category": row["category"],
            "legalBasis": row["legal_basis"],
            "durationDays": int(row["duration_days"]),
            "storageKind": row["storage_kind"],
            "essential": bool(row["essential"]),
            "enabled": bool(row["enabled"]),
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def cookie_policy(db_path: Path | str | None = None) -> dict:
    rows = cookies(db_path)
    active = [row for row in rows if row["enabled"]]
    consent = [row for row in active if not row["essential"] and row["storageKind"] != "none"]
    # Fingerprint of everything a visitor consents to: a stored choice made for
    # another list of trackers is no longer valid (audit R-02).
    material = json.dumps(
        sorted(
            [row["key"], row["provider"], row["purpose"], row["category"], row["durationDays"], row["storageKind"]]
            for row in consent
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "registry": rows,
        "activeCount": len(active),
        "consentRequired": bool(consent),
        "consentKeys": [row["key"] for row in consent],
        "defaultNonEssential": "denied",
        "policyVersion": hashlib.sha256(material.encode("utf-8")).hexdigest()[:16],
    }


def create_rights_request(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("demande invalide")
    request_type = str(payload.get("type") or "").strip()
    if request_type not in RIGHT_TYPES:
        raise ValueError("type de droit invalide")
    subject_ref = _text(payload.get("subjectRef"), "subjectRef", 240, required=True)
    notes = _text(payload.get("notes"), "notes", 2000)
    received = _now()
    request_id = uuid.uuid4().hex
    subject_hash = hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()
    due = _calendar_month_later(received)
    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO rights_requests(request_id,request_type,status,subject_ref_hash,received_at,due_at,notes)
               VALUES(?,?,'open',?,?,?,?)""",
            (request_id, request_type, subject_hash, received.isoformat(timespec="seconds"), due.isoformat(timespec="seconds"), notes),
        )
    return next(row for row in rights_requests(db_path) if row["id"] == request_id)


def set_rights_request_status(request_id: str, status: str, db_path: Path | str | None = None) -> dict:
    request_id = _text(request_id, "requestId", 64, required=True)
    status = str(status or "").strip()
    if status not in RIGHT_STATES:
        raise ValueError("statut demande invalide")
    closed = _now_iso() if status in {"closed", "rejected"} else ""
    init_db(db_path)
    with connect(db_path) as db:
        cur = db.execute(
            "UPDATE rights_requests SET status=?,closed_at=? WHERE request_id=?",
            (status, closed, request_id),
        )
        if not cur.rowcount:
            raise LookupError("demande inconnue")
    return next(row for row in rights_requests(db_path) if row["id"] == request_id)


def rights_requests(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT * FROM rights_requests ORDER BY received_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    now = _now()
    result = []
    for row in rows:
        due = datetime.datetime.fromisoformat(row["due_at"])
        result.append(
            {
                "id": row["request_id"],
                "type": row["request_type"],
                "status": row["status"],
                "subjectRefHash": row["subject_ref_hash"][:16],
                "receivedAt": row["received_at"],
                "dueAt": row["due_at"],
                "closedAt": row["closed_at"],
                "notes": row["notes"],
                "overdue": row["status"] not in {"closed", "rejected"} and due < now,
            }
        )
    return result


def create_incident(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("incident invalide")
    risk = str(payload.get("riskLevel") or "").strip()
    if risk not in INCIDENT_RISKS:
        raise ValueError("niveau de risque invalide")
    summary = _text(payload.get("summary"), "summary", 500, required=True)
    notes = _text(payload.get("notes"), "notes", 3000)
    detected = _now()
    due = detected + datetime.timedelta(hours=72) if risk in {"risk", "high_risk"} else None
    incident_id = uuid.uuid4().hex
    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO data_incidents(incident_id,risk_level,status,detected_at,cnil_due_at,summary,notes)
               VALUES(?,?,'open',?,?,?,?)""",
            (incident_id, risk, detected.isoformat(timespec="seconds"), due.isoformat(timespec="seconds") if due else "", summary, notes),
        )
    return next(row for row in incidents(db_path) if row["id"] == incident_id)


def set_incident_status(incident_id: str, status: str, db_path: Path | str | None = None) -> dict:
    incident_id = _text(incident_id, "incidentId", 64, required=True)
    status = str(status or "").strip()
    if status not in INCIDENT_STATES:
        raise ValueError("statut incident invalide")
    notified = _now_iso() if status == "notified" else ""
    init_db(db_path)
    with connect(db_path) as db:
        cur = db.execute(
            """UPDATE data_incidents SET status=?,
               notified_at=CASE WHEN ?<>'' THEN ? ELSE notified_at END
               WHERE incident_id=?""",
            (status, notified, notified, incident_id),
        )
        if not cur.rowcount:
            raise LookupError("incident inconnu")
    return next(row for row in incidents(db_path) if row["id"] == incident_id)


def incidents(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT * FROM data_incidents ORDER BY detected_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    now = _now()
    result = []
    for row in rows:
        due = datetime.datetime.fromisoformat(row["cnil_due_at"]) if row["cnil_due_at"] else None
        result.append(
            {
                "id": row["incident_id"],
                "riskLevel": row["risk_level"],
                "status": row["status"],
                "detectedAt": row["detected_at"],
                "cnilDueAt": row["cnil_due_at"],
                "notifiedAt": row["notified_at"],
                "summary": row["summary"],
                "notes": row["notes"],
                "notificationOverdue": bool(due and row["status"] not in {"notified", "closed"} and due < now),
            }
        )
    return result


def record_acceptance(
    contract_ref: str,
    *,
    document_type: str = "terms",
    purpose: str = "contract_terms",
    immediate_performance: bool = False,
    source: str = "checkout",
    db_path: Path | str | None = None,
) -> dict:
    contract_ref = _text(contract_ref, "contractRef", 200, required=True)
    purpose = _text(purpose, "purpose", 100, required=True)
    source = _text(source, "source", 80, required=True)
    document = published_document(document_type, db_path)
    if not document:
        raise RuntimeError("aucune version publiée du document")
    receipt_id = uuid.uuid4().hex
    stamp = _now_iso()
    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO consent_receipts(
              receipt_id,contract_ref,purpose,document_type,document_version,content_hash,
              accepted_at,immediate_performance,source
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                receipt_id,
                contract_ref,
                purpose,
                document_type,
                document["version"],
                document["contentHash"],
                stamp,
                int(bool(immediate_performance)),
                source,
            ),
        )
    return {
        "id": receipt_id,
        "contractRef": contract_ref,
        "purpose": purpose,
        "documentType": document_type,
        "documentVersion": document["version"],
        "contentHash": document["contentHash"],
        "acceptedAt": stamp,
        "immediatePerformance": bool(immediate_performance),
        "source": source,
    }


def consent_receipts(db_path: Path | str | None = None, limit: int = 50) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT receipt_id,contract_ref,purpose,document_type,document_version,content_hash,
                      accepted_at,immediate_performance,source
               FROM consent_receipts ORDER BY accepted_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [
        {
            "id": row["receipt_id"],
            "contractRef": row["contract_ref"],
            "purpose": row["purpose"],
            "documentType": row["document_type"],
            "documentVersion": row["document_version"],
            "contentHash": row["content_hash"],
            "acceptedAt": row["accepted_at"],
            "immediatePerformance": bool(row["immediate_performance"]),
            "source": row["source"],
        }
        for row in rows
    ]


def contract_acceptance_receipt(
    contract_ref: str,
    *,
    db_path: Path | str | None = None,
) -> dict | None:
    contract_ref = _text(contract_ref, "contractRef", 200, required=True)
    init_db(db_path)
    with connect(db_path) as db:
        row = db.execute(
            """SELECT receipt_id,contract_ref,purpose,document_type,document_version,content_hash,
                      accepted_at,immediate_performance,source
               FROM consent_receipts
               WHERE contract_ref=? AND purpose='contract_terms' AND document_type='terms'
               ORDER BY accepted_at DESC LIMIT 1""",
            (contract_ref,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["receipt_id"],
        "contractRef": row["contract_ref"],
        "purpose": row["purpose"],
        "documentType": row["document_type"],
        "documentVersion": row["document_version"],
        "contentHash": row["content_hash"],
        "acceptedAt": row["accepted_at"],
        "immediatePerformance": bool(row["immediate_performance"]),
        "source": row["source"],
    }


def _checkout_token_hash(booking_token: str) -> str:
    token = _text(booking_token, "bookingToken", 256, required=True)
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _checkout_acceptance_row(row: sqlite3.Row) -> dict:
    return {
        "bookingTokenHash": row["booking_token_hash"],
        "termsVersion": row["terms_version"],
        "termsContentHash": row["terms_content_hash"],
        "acceptedAt": row["accepted_at"],
        "reviewed": bool(row["reviewed"]),
        "immediatePerformance": bool(row["immediate_performance"]),
        "source": row["source"],
        "finalizedContractRef": row["finalized_contract_ref"],
        "finalizedAt": row["finalized_at"],
    }


def record_checkout_acceptance(
    booking_token: str,
    *,
    terms_version: str,
    terms_content_hash: str,
    accepted: bool,
    reviewed: bool,
    immediate_performance: bool = False,
    source: str = "checkout_review",
    db_path: Path | str | None = None,
) -> dict:
    if accepted is not True:
        raise ValueError("acceptation explicite des CGV requise")
    if reviewed is not True:
        raise ValueError("revue de commande requise")
    terms_version = _text(terms_version, "termsVersion", 32, required=True)
    terms_content_hash = _text(terms_content_hash, "termsContentHash", 64, required=True).lower()
    source = _text(source, "source", 80, required=True)
    document = published_document("terms", db_path)
    if not document:
        raise RuntimeError("aucune CGV publiée")
    if terms_version != document["version"] or terms_content_hash != document["contentHash"].lower():
        raise ValueError("version CGV périmée ou invalide")

    token_hash = _checkout_token_hash(booking_token)
    stamp = _now_iso()
    init_db(db_path)
    with connect(db_path) as db:
        existing = db.execute(
            "SELECT * FROM checkout_acceptance_intents WHERE booking_token_hash=?",
            (token_hash,),
        ).fetchone()
        if existing:
            if (
                existing["terms_version"] != terms_version
                or existing["terms_content_hash"].lower() != terms_content_hash
            ):
                raise ValueError("une acceptation différente existe déjà pour cette réservation")
            return _checkout_acceptance_row(existing)
        db.execute(
            """INSERT INTO checkout_acceptance_intents(
              booking_token_hash,terms_version,terms_content_hash,accepted_at,reviewed,
              immediate_performance,source,finalized_contract_ref,finalized_at
            ) VALUES(?,?,?,?,?,?,?,'','')""",
            (
                token_hash,
                terms_version,
                terms_content_hash,
                stamp,
                1,
                int(bool(immediate_performance)),
                source,
            ),
        )
        row = db.execute(
            "SELECT * FROM checkout_acceptance_intents WHERE booking_token_hash=?",
            (token_hash,),
        ).fetchone()
    return _checkout_acceptance_row(row)


CONTRACT_ACCEPTANCE_SOURCES = {
    "mercure_contract_confirmation",
    "staging_synthetic_mercure_contract_confirmation",
}


def finalize_checkout_acceptance(
    booking_token: str,
    contract_ref: str,
    *,
    source: str = "mercure_contract_confirmation",
    db_path: Path | str | None = None,
) -> dict:
    token_hash = _checkout_token_hash(booking_token)
    contract_ref = _text(contract_ref, "contractRef", 200, required=True)
    source = _text(source, "source", 80, required=True)
    if source not in CONTRACT_ACCEPTANCE_SOURCES:
        raise ValueError("source de finalisation contrat invalide")
    init_db(db_path)
    with connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM checkout_acceptance_intents WHERE booking_token_hash=?",
            (token_hash,),
        ).fetchone()
        if not row or not bool(row["reviewed"]):
            raise PermissionError("acceptation CGV manquante")
        previous_ref = str(row["finalized_contract_ref"] or "")
        if previous_ref and previous_ref != contract_ref:
            # Either side of the provider/browser race may arrive first. A
            # provider reference is authoritative: upgrade a browser placeholder
            # to it, or reuse it when the later browser callback arrives.
            if previous_ref.startswith("browser-") and not contract_ref.startswith("browser-"):
                pass
            elif not previous_ref.startswith("browser-") and contract_ref.startswith("browser-"):
                contract_ref = previous_ref
            else:
                raise ValueError("acceptation déjà liée à une autre référence contrat")

        existing = db.execute(
            """SELECT * FROM consent_receipts
               WHERE contract_ref=? AND purpose='contract_terms' AND document_type='terms'
                 AND document_version=? AND content_hash=?
               ORDER BY accepted_at DESC LIMIT 1""",
            (contract_ref, row["terms_version"], row["terms_content_hash"]),
        ).fetchone()
        if existing:
            if str(existing["source"] or "") != source:
                raise ValueError("provenance de reçu contrat incohérente")
            receipt_id = existing["receipt_id"]
        else:
            receipt_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO consent_receipts(
                  receipt_id,contract_ref,purpose,document_type,document_version,content_hash,
                  accepted_at,immediate_performance,source
                ) VALUES(?,?,'contract_terms','terms',?,?,?,?,?)""",
                (
                    receipt_id,
                    contract_ref,
                    row["terms_version"],
                    row["terms_content_hash"],
                    row["accepted_at"],
                    row["immediate_performance"],
                    source,
                ),
            )
        finalized_at = _now_iso()
        db.execute(
            """UPDATE checkout_acceptance_intents
               SET finalized_contract_ref=?,finalized_at=?
               WHERE booking_token_hash=?""",
            (contract_ref, finalized_at, token_hash),
        )
    return {
        "id": receipt_id,
        "contractRef": contract_ref,
        "purpose": "contract_terms",
        "documentType": "terms",
        "documentVersion": row["terms_version"],
        "contentHash": row["terms_content_hash"],
        "acceptedAt": row["accepted_at"],
        "immediatePerformance": bool(row["immediate_performance"]),
        "source": source,
        "finalizedAt": finalized_at,
    }


def checkout_acceptance_capability() -> dict:
    return {
        "bound": True,
        "explicitUntickedAcceptance": True,
        "orderReviewBeforeProvider": True,
        "versionAndHashBound": True,
        "finalizedOnMercureConfirmation": True,
        "immediatePerformanceCapturedSeparately": True,
    }


def summary(db_path: Path | str | None = None) -> dict:
    cfg = settings(db_path)
    docs = documents(db_path)
    published = {
        row["type"]
        for row in docs
        if row["status"] == "published" and not _test_or_placeholder_document(row)
    }
    missing_identity = [key for key in REQUIRED_IDENTITY_FIELDS if not str(cfg.get(key) or "").strip()]
    rights = rights_requests(db_path)
    incident_rows = incidents(db_path)
    cookie_state = cookie_policy(db_path)
    published_count = sum(1 for key in DOCUMENT_TYPES if key in published)
    return {
        "identityComplete": not missing_identity,
        "missingIdentityFields": missing_identity,
        "publishedDocuments": published_count,
        "requiredDocuments": len(DOCUMENT_TYPES),
        "missingDocuments": [key for key in DOCUMENT_TYPES if key not in published],
        "cookieConsentRequired": cookie_state["consentRequired"],
        "cookieDefaultNonEssential": cookie_state["defaultNonEssential"],
        "openRightsRequests": sum(1 for row in rights if row["status"] not in {"closed", "rejected"}),
        "overdueRightsRequests": sum(1 for row in rights if row["overdue"]),
        "openIncidents": sum(1 for row in incident_rows if row["status"] != "closed"),
        "overdueIncidentNotifications": sum(1 for row in incident_rows if row["notificationOverdue"]),
        "checkoutAcceptanceBound": checkout_acceptance_capability()["bound"],
        "withdrawalFunctionBound": False,
        "readyForPublicContracting": bool(
            not missing_identity
            and published_count == len(DOCUMENT_TYPES)
            and not any(row["overdue"] for row in rights)
            and not any(row["notificationOverdue"] for row in incident_rows)
            and checkout_acceptance_capability()["bound"]
            and False
        ),
    }


def admin_snapshot(db_path: Path | str | None = None) -> dict:
    return {
        "ok": True,
        "summary": summary(db_path),
        "settings": settings(db_path),
        "documents": documents(db_path),
        "documentTypes": DOCUMENT_TYPES,
        "cookies": cookie_policy(db_path),
        "rightsRequests": rights_requests(db_path),
        "incidents": incidents(db_path),
        "retentionPolicies": list(RETENTION_POLICIES),
        "consentReceipts": consent_receipts(db_path),
        "checkoutAcceptance": checkout_acceptance_capability(),
        "principles": {
            "analytics": "first-party cookieless",
            "nonEssentialDefault": "denied",
            "privacyByDefault": True,
            "rawIpRetention": False,
        },
    }
