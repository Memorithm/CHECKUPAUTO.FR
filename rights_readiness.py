from __future__ import annotations

from pathlib import Path

import data_subject_rights
import rights_subject_bindings


SUPPORTED_BINDING_PROVENANCE = (
    rights_subject_bindings.MOBILE_BINDING_PROVENANCE,
    rights_subject_bindings.MERCURE_APPOINTMENT_PROVENANCE,
)


def capability(db_path: Path | str | None = None) -> dict:
    """Compose DSAR capability with the binding paths implemented in the repo.

    ``data_subject_rights`` owns execution capability while
    ``rights_subject_bindings`` owns cross-store proof provenance. Keeping the
    composition here prevents the admin/readiness payload from lagging behind
    newly introduced proof paths.
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
    return result
