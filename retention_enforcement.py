from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import analytics_store
import booking_bridge
import compliance_store
import mobile_devices
import privacy_suppression
import site_config_store


MAX_RETENTION_DAYS = 36500
CNIL_OPPOSITION_MIN_DAYS = 1095

# Rules that can be enforced without inventing a business/legal duration.
AUTO_RULES = {
    "analytics_events": {
        "label": "Événements analytics first-party",
        "mode": "site_config",
        "source": "analytics.retentionDays",
        "store": "analytics.events",
        "trigger": "occurred_at",
    },
    "booking_intents": {
        "label": "Intentions de réservation / attribution",
        "mode": "site_config",
        "source": "analytics.retentionDays",
        "store": "analytics.booking_intents",
        "trigger": "created_at",
    },
    "mobile_vehicle_claims": {
        "label": "Claims mobiles temporaires",
        "mode": "event",
        "source": "claim expiry / consumption",
        "store": "mobile.mobile_vehicle_claim",
        "trigger": "expires_at / consumed_at",
    },
    "inactive_privacy_suppressions": {
        "label": "Liste repoussoir désactivée",
        "mode": "fixed_minimum",
        "activeDays": CNIL_OPPOSITION_MIN_DAYS,
        "source": "CNIL opposition minimum 3 ans",
        "store": "compliance.privacy_suppression",
        "trigger": "updated_at after deactivation",
    },
}

# These classes are deliberately not assigned an arbitrary retention period.
# Readiness remains blocked until an operator records a justified policy.
CONFIGURABLE_RULES = {
    "notification_delivery": {
        "label": "Journal NotificationBroker",
        "store": "notification_delivery",
        "trigger": "sent_at / created_at",
        "minimumDays": 1,
    },
    "review_followup": {
        "label": "Journal des demandes d'avis",
        "store": "review_followup",
        "trigger": "sent_at / first_seen_at",
        "minimumDays": 1,
    },
    "reminder_targets": {
        "label": "Cibles ReminderEngine",
        "store": "reminder_target",
        "trigger": "due_date",
        "minimumDays": 1,
    },
    "mobile_inactive_installations": {
        "label": "Installations mobiles désactivées",
        "store": "mobile_device",
        "trigger": "disabled_at",
        "minimumDays": 1,
    },
    "booking_conversions": {
        "label": "Conversions / rendez-vous attribués",
        "store": "booking_conversions",
        "trigger": "updated_at",
        "minimumDays": 1,
    },
    "checkout_acceptance_transient": {
        "label": "Liaison technique acceptation→Mercure",
        "store": "checkout_acceptance_intents",
        "trigger": "finalized_at",
        "minimumDays": 1,
    },
    "contract_consent_receipts": {
        "label": "Preuves d'acceptation contractuelle",
        "store": "consent_receipts",
        "trigger": "accepted_at",
        "minimumDays": 1,
        "legalReviewRequired": True,
    },
    "withdrawal_evidence": {
        "label": "Preuves de rétractation",
        "store": "withdrawal_requests",
        "trigger": "submitted_at",
        "minimumDays": 1,
        "legalReviewRequired": True,
    },
    "rights_requests_and_audit": {
        "label": "Demandes RGPD et preuves d'exécution",
        "store": "rights_requests / rights_execution_audit",
        "trigger": "closed_at / created_at",
        "minimumDays": 1,
        "legalReviewRequired": True,
    },
    "security_telemetry": {
        "label": "Télémétrie sécurité pseudonymisée",
        "store": "security telemetry",
        "trigger": "event timestamp",
        "minimumDays": 1,
        "implementationRequired": True,
    },
    "referral_ledger": {
        "label": "Parrainage / ledger",
        "store": "referral ledger",
        "trigger": "created_at",
        "minimumDays": 1,
        "legalReviewRequired": True,
        "implementationRequired": True,
    },
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _cutoff(days: int, now: datetime.datetime | None = None) -> str:
    current = now or _now()
    return (current - datetime.timedelta(days=int(days))).isoformat(timespec="seconds")


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS retention_policy_setting(
              rule_id TEXT PRIMARY KEY,
              active_days INTEGER NOT NULL,
              justification TEXT NOT NULL,
              legal_review_confirmed INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS retention_purge_audit(
              audit_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              rule_id TEXT NOT NULL,
              mode TEXT NOT NULL,
              removed_count INTEGER NOT NULL,
              cutoff_at TEXT NOT NULL DEFAULT '',
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_retention_audit_rule
              ON retention_purge_audit(rule_id,created_at);
            """
        )


def save_policy(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("politique de conservation invalide")
    rule_id = str(payload.get("ruleId") or "").strip()
    meta = CONFIGURABLE_RULES.get(rule_id)
    if not meta:
        raise ValueError("règle de conservation inconnue")
    try:
        days = int(payload.get("activeDays"))
    except (TypeError, ValueError) as exc:
        raise ValueError("durée de conservation invalide") from exc
    minimum = int(meta.get("minimumDays") or 1)
    if days < minimum or days > MAX_RETENTION_DAYS:
        raise ValueError("durée de conservation hors limites")
    justification = str(payload.get("justification") or "").strip()
    if len(justification) < 12 or len(justification) > 1000:
        raise ValueError("justification de conservation requise")
    legal_review = bool(payload.get("legalReviewConfirmed"))
    if meta.get("legalReviewRequired") and not legal_review:
        raise ValueError("validation juridique requise")
    enabled = bool(payload.get("enabled", True))
    stamp = _now_iso()
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO retention_policy_setting(
                 rule_id,active_days,justification,legal_review_confirmed,enabled,updated_at
               ) VALUES(?,?,?,?,?,?)
               ON CONFLICT(rule_id) DO UPDATE SET
                 active_days=excluded.active_days,justification=excluded.justification,
                 legal_review_confirmed=excluded.legal_review_confirmed,
                 enabled=excluded.enabled,updated_at=excluded.updated_at""",
            (rule_id, days, justification, int(legal_review), int(enabled), stamp),
        )
    return policy(rule_id, db_path)


def _settings(db_path: Path | str | None = None) -> dict[str, dict]:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute("SELECT * FROM retention_policy_setting").fetchall()
    return {
        str(row["rule_id"]): {
            "activeDays": int(row["active_days"]),
            "justification": str(row["justification"]),
            "legalReviewConfirmed": bool(row["legal_review_confirmed"]),
            "enabled": bool(row["enabled"]),
            "updatedAt": str(row["updated_at"]),
        }
        for row in rows
    }


def _analytics_days() -> int | None:
    try:
        cfg = site_config_store.load()
        days = int((cfg.get("analytics") or {}).get("retentionDays"))
    except Exception:
        return None
    return days if 1 <= days <= MAX_RETENTION_DAYS else None


def policy(rule_id: str, db_path: Path | str | None = None) -> dict:
    settings = _settings(db_path)
    if rule_id in AUTO_RULES:
        meta = dict(AUTO_RULES[rule_id])
        if meta["mode"] == "site_config":
            days = _analytics_days()
            ready = days is not None
            meta["activeDays"] = days
            meta["configured"] = ready
            meta["enabled"] = ready
        else:
            meta["configured"] = True
            meta["enabled"] = True
            ready = True
        meta.update({"id": rule_id, "ready": ready, "blocker": "" if ready else "site_config_missing"})
        return meta
    meta = CONFIGURABLE_RULES.get(rule_id)
    if not meta:
        raise KeyError(rule_id)
    setting = settings.get(rule_id)
    implemented = not bool(meta.get("implementationRequired"))
    ready = bool(setting and setting.get("enabled") and implemented)
    blocker = ""
    if not setting:
        blocker = "policy_configuration_required"
    elif not setting.get("enabled"):
        blocker = "policy_disabled"
    elif not implemented:
        blocker = "purger_implementation_required"
    return {
        "id": rule_id,
        **meta,
        **(setting or {}),
        "configured": bool(setting),
        "implemented": implemented,
        "ready": ready,
        "blocker": blocker,
    }


def policies(db_path: Path | str | None = None) -> list[dict]:
    ids = [*AUTO_RULES.keys(), *CONFIGURABLE_RULES.keys()]
    return [policy(rule_id, db_path) for rule_id in ids]


def _record_audit(
    run_id: str,
    rule_id: str,
    mode: str,
    removed: int,
    cutoff_at: str,
    *,
    db_path: Path | str | None = None,
) -> dict:
    evidence = {
        "runId": run_id,
        "ruleId": rule_id,
        "mode": mode,
        "removedCount": max(0, int(removed)),
        "cutoffAt": cutoff_at,
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    row = {
        "auditId": uuid.uuid4().hex,
        **evidence,
        "evidenceHash": digest,
        "createdAt": _now_iso(),
    }
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO retention_purge_audit(
                 audit_id,run_id,rule_id,mode,removed_count,cutoff_at,evidence_hash,created_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                row["auditId"], run_id, rule_id, mode, row["removedCount"],
                cutoff_at, digest, row["createdAt"],
            ),
        )
    return row


def _purge_analytics(days: int, *, dry_run: bool) -> int:
    analytics_store.init_db()
    cutoff = _cutoff(days)
    with analytics_store.connect() as db:
        count = int(db.execute(
            "SELECT COUNT(*) n FROM events WHERE occurred_at<?", (cutoff,)
        ).fetchone()["n"])
        if not dry_run:
            db.execute("DELETE FROM events WHERE occurred_at<?", (cutoff,))
    return count


def _purge_booking_intents(days: int, *, dry_run: bool) -> int:
    booking_bridge.init_db()
    cutoff = _cutoff(days)
    with analytics_store.connect() as db:
        count = int(db.execute(
            "SELECT COUNT(*) n FROM booking_intents WHERE created_at<?", (cutoff,)
        ).fetchone()["n"])
        if not dry_run:
            db.execute("DELETE FROM booking_intents WHERE created_at<?", (cutoff,))
    return count


def _purge_mobile_claims(*, dry_run: bool) -> int:
    mobile_devices.init_db()
    now = _now_iso()
    with mobile_devices.connect() as db:
        count = int(db.execute(
            """SELECT COUNT(*) n FROM mobile_vehicle_claim
               WHERE consumed_at<>'' OR expires_at<=?""", (now,)
        ).fetchone()["n"])
        if not dry_run:
            db.execute(
                "DELETE FROM mobile_vehicle_claim WHERE consumed_at<>'' OR expires_at<=?",
                (now,),
            )
    return count


def _purge_inactive_suppressions(*, dry_run: bool, db_path: Path | str | None = None) -> int:
    privacy_suppression.init_db(db_path)
    cutoff = _cutoff(CNIL_OPPOSITION_MIN_DAYS)
    with compliance_store.connect(db_path) as db:
        count = int(db.execute(
            """SELECT COUNT(*) n FROM privacy_suppression
               WHERE active=0 AND updated_at<?""", (cutoff,)
        ).fetchone()["n"])
        if not dry_run:
            db.execute(
                "DELETE FROM privacy_suppression WHERE active=0 AND updated_at<?",
                (cutoff,),
            )
    return count


def run_once(
    *,
    dry_run: bool = False,
    db_path: Path | str | None = None,
) -> dict:
    init_db(db_path)
    run_id = uuid.uuid4().hex
    rows = []
    for rule_id in AUTO_RULES:
        state = policy(rule_id, db_path)
        if not state.get("ready"):
            rows.append({"ruleId": rule_id, "state": "blocked", "removedCount": 0})
            continue
        mode = "dry_run" if dry_run else "purge"
        cutoff_at = ""
        if rule_id == "analytics_events":
            days = int(state["activeDays"])
            cutoff_at = _cutoff(days)
            removed = _purge_analytics(days, dry_run=dry_run)
        elif rule_id == "booking_intents":
            days = int(state["activeDays"])
            cutoff_at = _cutoff(days)
            removed = _purge_booking_intents(days, dry_run=dry_run)
        elif rule_id == "mobile_vehicle_claims":
            cutoff_at = _now_iso()
            removed = _purge_mobile_claims(dry_run=dry_run)
        elif rule_id == "inactive_privacy_suppressions":
            cutoff_at = _cutoff(CNIL_OPPOSITION_MIN_DAYS)
            removed = _purge_inactive_suppressions(dry_run=dry_run, db_path=db_path)
        else:  # pragma: no cover
            continue
        audit = _record_audit(
            run_id, rule_id, mode, removed, cutoff_at, db_path=db_path
        )
        rows.append({"ruleId": rule_id, "state": "ready", "removedCount": removed, "audit": audit})

    return {
        "ok": all(row["state"] == "ready" for row in rows),
        "runId": run_id,
        "dryRun": bool(dry_run),
        "rules": rows,
    }


def audit_rows(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT audit_id,run_id,rule_id,mode,removed_count,cutoff_at,evidence_hash,created_at
               FROM retention_purge_audit ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [
        {
            "auditId": str(row["audit_id"]),
            "runId": str(row["run_id"]),
            "ruleId": str(row["rule_id"]),
            "mode": str(row["mode"]),
            "removedCount": int(row["removed_count"]),
            "cutoffAt": str(row["cutoff_at"]),
            "evidenceHash": str(row["evidence_hash"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]


def status(db_path: Path | str | None = None) -> dict:
    rows = policies(db_path)
    blockers = [
        {"ruleId": row["id"], "reason": row.get("blocker") or "not_ready"}
        for row in rows if not row.get("ready")
    ]
    return {
        "bound": not blockers,
        "readyRuleCount": sum(1 for row in rows if row.get("ready")),
        "ruleCount": len(rows),
        "blockerCount": len(blockers),
        "blockers": blockers,
        "policies": rows,
        "audit": audit_rows(db_path, 50),
        "principles": {
            "noArbitraryDuration": True,
            "purposeLimitedRetention": True,
            "purgeEvidenceContainsPersonalData": False,
            "activeOppositionSuppressionAutoPurged": False,
        },
    }
