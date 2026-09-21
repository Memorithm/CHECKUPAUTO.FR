from __future__ import annotations

from pathlib import Path

import compliance_operations
import compliance_store


def snapshot(db_path: Path | str | None = None) -> dict:
    """Return the Compliance Center payload with operational-register evidence.

    The historical compliance store owns legal identity, published documents,
    rights requests, incidents and consent receipts. Operational GDPR registers
    are intentionally kept in their dedicated module but are surfaced through
    the same admin snapshot so the UI and activation gates have one source of
    truth.
    """
    result = compliance_store.admin_snapshot(db_path)
    operations = compliance_operations.snapshot(db_path)
    operations_summary = dict(operations.get("summary") or {})
    blockers = list(operations_summary.get("blockers") or [])

    # An empty processing register is not evidence of operational readiness.
    # Fail closed until at least one active processing activity has been
    # documented and reviewed.
    if int(operations_summary.get("activeActivityCount") or 0) == 0:
        blockers.insert(
            0,
            {
                "type": "processing_register_missing",
                "id": "processing_activities",
                "name": "Registre des activités de traitement",
            },
        )

    operations_ready = not blockers
    operations_summary["blockers"] = blockers
    operations_summary["blockerCount"] = len(blockers)
    operations_summary["operationalRegistersReady"] = operations_ready
    operations["summary"] = operations_summary

    summary = dict(result.get("summary") or {})
    summary["operationalRegistersReady"] = operations_ready
    summary["operationalBlockers"] = blockers
    # Never make the existing public-contracting gate less strict. The legacy
    # gate remains authoritative for CGV binding, withdrawal and legal data;
    # operational registers can only keep it blocked, never turn it green.
    summary["readyForPublicContracting"] = bool(summary.get("readyForPublicContracting")) and operations_ready
    result["summary"] = summary
    result["operations"] = operations
    return result
