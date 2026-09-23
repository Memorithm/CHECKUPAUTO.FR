from __future__ import annotations

import compliance_admin
import compliance_operations


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


def upsert_processing_activity(payload: object) -> tuple[int, dict]:
    """Persist one operator-supplied Article 30 activity through core validation.

    This boundary deliberately performs no inference about legal bases, risk,
    retention, systems, DPIA state or review dates. Those facts must be supplied
    by the authenticated operator and are validated/audited by
    ``compliance_operations``.
    """
    try:
        activity = compliance_operations.upsert_processing_activity(payload)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "compliance_processing_activity_invalid"}
    except Exception:
        return 500, {"ok": False, "error": "compliance_processing_activity_failed"}
    return 201, {"ok": True, "activity": activity}


def upsert_processor(payload: object) -> tuple[int, dict]:
    """Persist one operator-supplied processor record through core validation.

    Provider identity, DPA state, hosting location, transfers and subprocessors
    remain explicit operator facts. The HTTP adapter only sanitizes failures and
    delegates validation plus audit evidence to the core register.
    """
    try:
        processor = compliance_operations.upsert_processor(payload)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "compliance_processor_invalid"}
    except Exception:
        return 500, {"ok": False, "error": "compliance_processor_failed"}
    return 201, {"ok": True, "processor": processor}
