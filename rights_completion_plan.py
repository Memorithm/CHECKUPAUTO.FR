from __future__ import annotations

import hashlib
from pathlib import Path

import compliance_store
import data_subject_rights
import referral_wallet_rights
import rights_rectification


DISPOSITIONS = {"required", "not_applicable"}
# Issue #147 still records incomplete cross-store coverage. Keep request closure
# disabled until that gap is removed with evidence; a per-request plan must not
# be mistaken for proof that every CheckupAuto/Mercure store is implemented.
GLOBAL_COVERAGE_COMPLETE = False


def _init(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS rights_completion_plan(
              request_id TEXT NOT NULL,
              adapter TEXT NOT NULL,
              disposition TEXT NOT NULL,
              justification_hash TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(request_id,adapter)
            );
            CREATE INDEX IF NOT EXISTS idx_rights_completion_request
              ON rights_completion_plan(request_id,disposition);
            """
        )


def _known_adapters(request_type: str) -> list[str]:
    adapters = {
        name
        for name, rights in data_subject_rights.SUPPORTED_ADAPTERS.items()
        if request_type in rights
    }
    if request_type == rights_rectification.capability()["requestType"]:
        adapters.add(rights_rectification.ADAPTER)
    if request_type in referral_wallet_rights.SUPPORTED_RIGHTS:
        adapters.add(referral_wallet_rights.ADAPTER)
    return sorted(adapters)


def _executed_adapters(request_id: str, db_path: Path | str | None = None) -> set[str]:
    data_subject_rights._init_audit(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            "SELECT DISTINCT adapter FROM rights_execution_audit WHERE request_id=?",
            (request_id,),
        ).fetchall()
    return {str(row["adapter"]) for row in rows}


def _justification_hash(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("justification de non-applicabilité requise")
    if len(raw) > 2000:
        raise ValueError("justification de non-applicabilité trop longue")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def configure(
    request_id: object,
    entries: object,
    db_path: Path | str | None = None,
) -> dict:
    """Persist an exact applicability plan without retaining raw justification.

    Every currently implemented adapter for the request type must be classified
    as either required or not applicable. An adapter that already executed can
    never subsequently be labelled not applicable. This records operator scope
    decisions but deliberately does not close the DSAR while global store
    coverage remains incomplete.
    """
    rid = data_subject_rights._request_id(request_id)
    request = data_subject_rights._request(rid, db_path)
    if str(request["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non planifiable")
    if not isinstance(entries, list):
        raise ValueError("plan d'applicabilité invalide")

    request_type = str(request["request_type"])
    expected = _known_adapters(request_type)
    executed = _executed_adapters(rid, db_path)
    normalized: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("entrée de plan invalide")
        adapter = str(entry.get("adapter") or "").strip()
        disposition = str(entry.get("disposition") or "").strip()
        if adapter in seen or adapter not in expected:
            raise ValueError("adaptateur de plan invalide")
        if disposition not in DISPOSITIONS:
            raise ValueError("disposition de plan invalide")
        seen.add(adapter)
        if disposition == "required":
            if set(entry) != {"adapter", "disposition"}:
                raise ValueError("entrée requise de plan invalide")
            justification_hash = ""
        else:
            if set(entry) != {"adapter", "disposition", "justification"}:
                raise ValueError("entrée non applicable de plan invalide")
            if adapter in executed:
                raise ValueError("un adaptateur exécuté ne peut pas être non applicable")
            justification_hash = _justification_hash(entry.get("justification"))
        normalized.append((adapter, disposition, justification_hash))

    if sorted(seen) != expected:
        raise ValueError("le plan doit classifier tous les adaptateurs connus")

    _init(db_path)
    stamp = data_subject_rights._now_iso()
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM rights_completion_plan WHERE request_id=?", (rid,))
        db.executemany(
            """INSERT INTO rights_completion_plan(
                 request_id,adapter,disposition,justification_hash,created_at,updated_at
               ) VALUES(?,?,?,?,?,?)""",
            [
                (rid, adapter, disposition, digest, stamp, stamp)
                for adapter, disposition, digest in normalized
            ],
        )
    return status(rid, db_path)


def status(request_id: object, db_path: Path | str | None = None) -> dict:
    rid = data_subject_rights._request_id(request_id)
    request = data_subject_rights._request(rid, db_path)
    request_type = str(request["request_type"])
    expected = _known_adapters(request_type)
    executed = _executed_adapters(rid, db_path)
    _init(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT adapter,disposition,justification_hash,updated_at
               FROM rights_completion_plan WHERE request_id=? ORDER BY adapter""",
            (rid,),
        ).fetchall()
    planned = {str(row["adapter"]): row for row in rows}
    items = []
    for adapter in expected:
        row = planned.get(adapter)
        disposition = str(row["disposition"]) if row else "unplanned"
        was_executed = adapter in executed
        satisfied = (
            disposition == "required" and was_executed
        ) or (
            disposition == "not_applicable"
            and bool(row and str(row["justification_hash"]))
        )
        items.append(
            {
                "adapter": adapter,
                "disposition": disposition,
                "executed": was_executed,
                "satisfied": satisfied,
                "justificationHash": (
                    str(row["justification_hash"]) if row else ""
                ),
                "updatedAt": str(row["updated_at"]) if row else "",
            }
        )

    plan_complete = set(planned) == set(expected)
    known_scope_complete = plan_complete and all(item["satisfied"] for item in items)
    return {
        "requestId": rid,
        "requestType": request_type,
        "requestStatus": str(request["status"]),
        "coverageScope": "implemented_adapters",
        "knownAdapters": expected,
        "planComplete": plan_complete,
        "knownScopeComplete": known_scope_complete,
        "globalCoverageComplete": GLOBAL_COVERAGE_COMPLETE,
        "closureReady": known_scope_complete and GLOBAL_COVERAGE_COMPLETE,
        "requestComplete": str(request["status"]) == "closed",
        "rawJustificationPersisted": False,
        "items": items,
    }


def close(request_id: object, db_path: Path | str | None = None) -> dict:
    state = status(request_id, db_path)
    if not state["knownScopeComplete"]:
        raise RuntimeError("plan d'exécution incomplet")
    if not state["globalCoverageComplete"]:
        raise RuntimeError("couverture globale des systèmes incomplète")
    return compliance_store.set_rights_request_status(
        state["requestId"],
        "closed",
        db_path,
    )


def capability() -> dict:
    return {
        "planReady": True,
        "coverageScope": "implemented_adapters",
        "globalCoverageComplete": GLOBAL_COVERAGE_COMPLETE,
        "closureFailClosedOnGlobalCoverage": True,
        "notApplicableRequiresHashedJustification": True,
        "rawJustificationPersisted": False,
    }
