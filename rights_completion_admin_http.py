from __future__ import annotations

from pathlib import Path

import rights_completion_admin


def configure(payload: object, db_path: Path | str | None = None) -> tuple[int, dict]:
    try:
        plan = rights_completion_admin.configure(payload, db_path)
        return 200, {"ok": True, "completionPlan": plan}
    except LookupError:
        return 404, {"ok": False, "error": "compliance_request_not_found"}
    except RuntimeError:
        return 409, {"ok": False, "error": "compliance_completion_plan_conflict"}
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "compliance_completion_plan_invalid"}
    except Exception:
        return 500, {"ok": False, "error": "compliance_completion_plan_unavailable"}


def status(request_id: object, db_path: Path | str | None = None) -> tuple[int, dict]:
    try:
        plan = rights_completion_admin.status(request_id, db_path)
        return 200, {"ok": True, "completionPlan": plan}
    except LookupError:
        return 404, {"ok": False, "error": "compliance_request_not_found"}
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "compliance_completion_plan_invalid"}
    except Exception:
        return 500, {"ok": False, "error": "compliance_completion_plan_unavailable"}
