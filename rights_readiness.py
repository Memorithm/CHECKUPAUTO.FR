from __future__ import annotations

from pathlib import Path

import data_subject_rights
import rights_rectification
import rights_subject_bindings


SUPPORTED_BINDING_PROVENANCE = (
    rights_subject_bindings.MOBILE_BINDING_PROVENANCE,
    rights_subject_bindings.MERCURE_APPOINTMENT_PROVENANCE,
)


def capability(db_path: Path | str | None = None) -> dict:
    """Compose DSAR capability with cross-store proof and rectification state.

    ``data_subject_rights`` owns the multi-store execution capability,
    ``rights_subject_bindings`` owns cross-store proof provenance, and
    ``rights_rectification`` exposes the deliberately bounded local correction
    path. Keeping the composition here prevents admin/readiness from claiming
    that one local rectification path completes the global right.
    """
    result = dict(data_subject_rights.capability(db_path))
    recent = rights_subject_bindings.rows(db_path, limit=500)
    observed = sorted({
        str(row.get("provenance") or "")
        for row in recent
        if str(row.get("provenance") or "")
    })
    result["subjectBindingProvenance"] = list(SUPPORTED_BINDING_PROVENANCE)
    result["observedSubjectBindingProvenance"] = observed
    result["subjectBindingEvidenceObserved"] = bool(observed)
    result["rectificationExecution"] = rights_rectification.capability()
    return result
