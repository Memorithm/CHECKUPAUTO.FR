from __future__ import annotations

import referral_engine as referrals
import referral_integrity_audit as integrity_audit


def _bounded_integrity_status() -> dict:
    try:
        return integrity_audit.status()
    except integrity_audit.ReferralAuditUnavailable:
        return {
            "ok": False,
            "state": "unavailable",
            "issues": 0,
            "error": "referral_ledger_unavailable",
            "metrics": {},
        }
    except Exception as exc:
        return {
            "ok": False,
            "state": "unavailable",
            "issues": 0,
            "error": type(exc).__name__,
            "metrics": {},
        }


def status(limit: int = 100) -> dict:
    requested = int(limit)
    bounded_limit = max(1, min(requested, 500))
    return {
        "ok": True,
        "accounts": referrals.list_accounts(bounded_limit),
        "rewardCents": referrals.configured_reward_cents(),
        "integrity": _bounded_integrity_status(),
    }
