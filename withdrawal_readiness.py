from __future__ import annotations

from pathlib import Path

import retention_enforcement
import withdrawal_rights


def capability(db_path: Path | str | None = None) -> dict:
    """Expose whether withdrawal erasure is executable in the current runtime.

    The withdrawal adapter is implemented, but physical erasure is deliberately
    gated by the configured `withdrawal_evidence` retention policy. This view
    keeps implementation capability separate from runtime executability so an
    operator cannot mistake "supported" for "safe to execute".
    """
    base = dict(withdrawal_rights.capability())
    try:
        policy = retention_enforcement.policy(withdrawal_rights.RETENTION_RULE, db_path)
    except Exception:
        base.update(
            {
                "erasureExecutable": False,
                "retentionPolicy": {
                    "id": withdrawal_rights.RETENTION_RULE,
                    "configured": False,
                    "enabled": False,
                    "implemented": True,
                    "ready": False,
                    "legalReviewConfirmed": False,
                    "activeDays": None,
                    "blocker": "retention_policy_unavailable",
                },
            }
        )
        return base

    legal_review = policy.get("legalReviewConfirmed") is True
    policy_ready = policy.get("ready") is True and legal_review
    blocker = str(policy.get("blocker") or "")
    if policy.get("ready") is True and not legal_review:
        blocker = "legal_review_required"

    active_days = policy.get("activeDays")
    if isinstance(active_days, bool):
        active_days = None
    elif active_days is not None:
        try:
            active_days = int(active_days)
        except (TypeError, ValueError):
            active_days = None

    base.update(
        {
            "erasureExecutable": policy_ready,
            "retentionPolicy": {
                "id": withdrawal_rights.RETENTION_RULE,
                "configured": policy.get("configured") is True,
                "enabled": policy.get("enabled") is True,
                "implemented": policy.get("implemented") is True,
                "ready": policy_ready,
                "legalReviewConfirmed": legal_review,
                "activeDays": active_days,
                "blocker": blocker,
            },
        }
    )
    return base
