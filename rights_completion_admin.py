from __future__ import annotations

from pathlib import Path

import rights_completion_plan


CONFIGURE_FIELDS = {"id", "entries"}
MAX_REQUESTS = 200


def _bounded(state: dict) -> dict:
    """Return only non-subject, non-justification completion-plan evidence."""
    return {
        "requestId": str(state.get("requestId") or ""),
        "requestType": str(state.get("requestType") or ""),
        "requestStatus": str(state.get("requestStatus") or ""),
        "coverageScope": str(state.get("coverageScope") or ""),
        "knownAdapters": [str(value) for value in state.get("knownAdapters", [])],
        "planComplete": bool(state.get("planComplete")),
        "knownScopeComplete": bool(state.get("knownScopeComplete")),
        "globalCoverageComplete": bool(state.get("globalCoverageComplete")),
        "closureReady": bool(state.get("closureReady")),
        "requestComplete": bool(state.get("requestComplete")),
        "rawJustificationPersisted": bool(state.get("rawJustificationPersisted")),
        "items": [
            {
                "adapter": str(item.get("adapter") or ""),
                "disposition": str(item.get("disposition") or ""),
                "executed": bool(item.get("executed")),
                "executionComplete": bool(item.get("executionComplete")),
                "executionLimitation": str(item.get("executionLimitation") or ""),
                "satisfied": bool(item.get("satisfied")),
                "justificationHash": str(item.get("justificationHash") or ""),
                "updatedAt": str(item.get("updatedAt") or ""),
            }
            for item in state.get("items", [])
            if isinstance(item, dict)
        ],
    }


def configure(payload: object, db_path: Path | str | None = None) -> dict:
    """Configure one exact DSAR applicability plan from the admin trust boundary.

    The payload is deliberately strict. Raw non-applicability justifications are
    accepted only long enough for the core planner to hash them; the returned
    admin representation contains only those hashes and execution state.
    """
    if not isinstance(payload, dict) or set(payload) != CONFIGURE_FIELDS:
        raise ValueError("payload de plan d'applicabilité invalide")
    request_id = str(payload.get("id") or "").strip()
    if not request_id:
        raise ValueError("identifiant de demande requis")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("entrées de plan invalides")
    return _bounded(rights_completion_plan.configure(request_id, entries, db_path))


def status(request_id: object, db_path: Path | str | None = None) -> dict:
    rid = str(request_id or "").strip()
    if not rid:
        raise ValueError("identifiant de demande requis")
    return _bounded(rights_completion_plan.status(rid, db_path))


def statuses(request_ids: object, db_path: Path | str | None = None) -> list[dict]:
    """Return bounded plan state for a finite set of requests.

    This helper is intended for the Compliance Center snapshot. It does not
    infer applicability and it does not expose a closure mutation while global
    coverage remains intentionally fail-closed.
    """
    if not isinstance(request_ids, list) or len(request_ids) > MAX_REQUESTS:
        raise ValueError("liste de demandes invalide")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in request_ids:
        rid = str(value or "").strip()
        if not rid or rid in seen:
            raise ValueError("identifiant de demande invalide")
        seen.add(rid)
        normalized.append(rid)
    return [status(rid, db_path) for rid in normalized]


def capability() -> dict:
    core = rights_completion_plan.capability()
    return {
        "configureReady": True,
        "statusReady": True,
        "bulkStatusLimit": MAX_REQUESTS,
        "closureMutationExposed": False,
        "coverageScope": str(core.get("coverageScope") or ""),
        "globalCoverageComplete": bool(core.get("globalCoverageComplete")),
        "partialExecutionDoesNotSatisfyRequiredPlan": bool(
            core.get("partialExecutionDoesNotSatisfyRequiredPlan")
        ),
        "rawJustificationPersisted": False,
    }
