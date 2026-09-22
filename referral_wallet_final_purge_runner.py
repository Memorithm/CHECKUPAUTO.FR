from __future__ import annotations

from pathlib import Path

import referral_wallet_final_purge
import retention_enforcement


RULE_ID = referral_wallet_final_purge.RULE_ID


def process_once(
    *,
    dry_run: bool = False,
    db_path: Path | str | None = None,
) -> dict:
    """Run the final wallet purge only when the reviewed retention rule is ready.

    The shared operational tick must stay healthy when an operator has not yet
    configured a legally reviewed duration. In that case this boundary reports a
    blocked state instead of converting an expected compliance gate into a runtime
    failure.
    """
    state = retention_enforcement.policy(RULE_ID, db_path)
    if not bool(state.get("ready")):
        return {
            "ok": True,
            "state": "blocked",
            "ruleId": RULE_ID,
            "reason": str(state.get("blocker") or "retention_policy_not_ready"),
            "purgedAccounts": 0,
            "purgedRows": 0,
        }
    if not bool(state.get("legalReviewConfirmed")):
        return {
            "ok": True,
            "state": "blocked",
            "ruleId": RULE_ID,
            "reason": "legal_review_required",
            "purgedAccounts": 0,
            "purgedRows": 0,
        }

    result = referral_wallet_final_purge.purge_retired_wallets(
        int(state["activeDays"]),
        dry_run=dry_run,
        db_path=db_path,
    )
    if not bool(result.get("ok")):
        raise RuntimeError("purge finale cagnotte non confirmée")
    return {
        **result,
        "state": "ready",
        "ruleId": RULE_ID,
        "retentionDays": int(state["activeDays"]),
        "legalReviewConfirmed": True,
    }
