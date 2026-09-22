from __future__ import annotations

import compliance_admin


def review_high_risk_processing(payload: object) -> tuple[int, dict]:
    """Translate the bounded processing-review action into a sanitized HTTP result.

    The route layer can delegate to this adapter without reflecting validation,
    activity, or evidence details. Runtime state conflicts remain distinguishable
    from malformed input so stale reviewed digests fail closed with HTTP 409.
    """
    try:
        review = compliance_admin.review_high_risk_processing(payload)
    except LookupError:
        return 404, {"ok": False, "error": "compliance_processing_review_not_found"}
    except RuntimeError:
        return 409, {"ok": False, "error": "compliance_processing_review_conflict"}
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "compliance_processing_review_invalid"}
    except Exception:
        return 500, {"ok": False, "error": "compliance_processing_review_failed"}
    return 201, {"ok": True, "review": review}
