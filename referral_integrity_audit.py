from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals

_ALLOWED_REWARD_STATUS = {"pending", "earned", "cancelled", "reversed"}
_ALLOWED_LEDGER_KIND = {"earn", "reverse", "redeem"}


class ReferralAuditUnavailable(RuntimeError):
    pass


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.is_file():
        raise ReferralAuditUnavailable("referral_ledger_unavailable")
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise ReferralAuditUnavailable("referral_ledger_unavailable") from exc
    db.row_factory = sqlite3.Row
    return db


def _required_schema(db: sqlite3.Connection) -> None:
    existing = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('referral_accounts','referral_rewards','referral_ledger')"
        )
    }
    if existing != {"referral_accounts", "referral_rewards", "referral_ledger"}:
        raise ReferralAuditUnavailable("referral_schema_unavailable")


def status(db_path: Path | None = None) -> dict:
    path = Path(db_path) if db_path is not None else Path(analytics.DB)
    with closing(_connect_readonly(path)) as db:
        _required_schema(db)
        rewards = [
            dict(row)
            for row in db.execute(
                "SELECT provider,external_id,account_id,status,reward_cents FROM referral_rewards"
            )
        ]
        ledger = [
            dict(row)
            for row in db.execute(
                "SELECT account_id,kind,amount_cents,reference FROM referral_ledger"
            )
        ]
        account_count = int(
            db.execute("SELECT COUNT(*) n FROM referral_accounts").fetchone()["n"]
        )
        debt_accounts = int(
            db.execute(
                """SELECT COUNT(*) n FROM (
                   SELECT account_id,SUM(amount_cents) balance
                   FROM referral_ledger GROUP BY account_id HAVING balance < 0
                   )"""
            ).fetchone()["n"]
        )

    ledger_map = {
        (str(row["account_id"]), str(row["kind"]), str(row["reference"])): int(row["amount_cents"])
        for row in ledger
    }
    active = [row for row in rewards if str(row["status"]) in {"earned", "reversed"}]
    legacy_groups: dict[tuple[str, str], list[dict]] = {}
    for row in active:
        legacy = referrals._legacy_reward_ledger_reference(row["provider"], row["external_id"])
        legacy_groups.setdefault((str(row["account_id"]), legacy), []).append(row)

    metrics = {
        "accounts": account_count,
        "rewards": len(rewards),
        "earnedRewards": sum(1 for row in rewards if str(row["status"]) == "earned"),
        "reversedRewards": sum(1 for row in rewards if str(row["status"]) == "reversed"),
        "modernEarns": 0,
        "legacyEarns": 0,
        "ambiguousLegacyReferences": 0,
        "missingEarns": 0,
        "orphanEarns": 0,
        "duplicateEarnReferences": 0,
        "amountMismatches": 0,
        "missingReversals": 0,
        "unexpectedReversals": 0,
        "orphanReversals": 0,
        "invalidRewardStatuses": sum(1 for row in rewards if str(row["status"]) not in _ALLOWED_REWARD_STATUS),
        "unexpectedLedgerKinds": sum(1 for row in ledger if str(row["kind"]) not in _ALLOWED_LEDGER_KIND),
        "accountsInDebt": debt_accounts,
    }
    ambiguous_seen: set[tuple[str, str]] = set()
    recognized_earn_keys: set[tuple[str, str, str]] = set()

    for row in active:
        account = str(row["account_id"])
        reward_cents = int(row["reward_cents"])
        modern = referrals._reward_ledger_reference(row["provider"], row["external_id"])
        legacy = referrals._legacy_reward_ledger_reference(row["provider"], row["external_id"])
        modern_key = (account, "earn", modern)
        legacy_key = (account, "earn", legacy)
        modern_amount = ledger_map.get(modern_key)
        legacy_amount = ledger_map.get(legacy_key)
        chosen_reference = ""

        if modern_amount is not None:
            metrics["modernEarns"] += 1
            recognized_earn_keys.add(modern_key)
            chosen_reference = modern
            if modern_amount != reward_cents:
                metrics["amountMismatches"] += 1
            if legacy_amount is not None:
                metrics["duplicateEarnReferences"] += 1
                recognized_earn_keys.add(legacy_key)
        elif legacy_amount is not None:
            metrics["legacyEarns"] += 1
            recognized_earn_keys.add(legacy_key)
            group_key = (account, legacy)
            if len(legacy_groups.get(group_key, [])) != 1:
                if group_key not in ambiguous_seen:
                    metrics["ambiguousLegacyReferences"] += 1
                    ambiguous_seen.add(group_key)
            else:
                chosen_reference = legacy
            if legacy_amount != reward_cents:
                metrics["amountMismatches"] += 1
        else:
            metrics["missingEarns"] += 1

        reverse_candidates = []
        for reference in {modern, legacy}:
            key = (account, "reverse", reference)
            if key in ledger_map:
                reverse_candidates.append((reference, ledger_map[key]))
        if str(row["status"]) == "reversed":
            if not chosen_reference:
                metrics["missingReversals"] += 1
            else:
                amount = ledger_map.get((account, "reverse", chosen_reference))
                if amount is None:
                    metrics["missingReversals"] += 1
                elif amount != -reward_cents:
                    metrics["amountMismatches"] += 1
        elif reverse_candidates:
            metrics["unexpectedReversals"] += 1

    for row in ledger:
        key = (str(row["account_id"]), str(row["kind"]), str(row["reference"]))
        if str(row["kind"]) == "earn" and key not in recognized_earn_keys:
            metrics["orphanEarns"] += 1
        if str(row["kind"]) != "reverse":
            continue
        earn_amount = ledger_map.get((str(row["account_id"]), "earn", str(row["reference"])))
        if earn_amount is None or int(row["amount_cents"]) != -int(earn_amount):
            metrics["orphanReversals"] += 1

    issue_keys = (
        "ambiguousLegacyReferences",
        "missingEarns",
        "orphanEarns",
        "duplicateEarnReferences",
        "amountMismatches",
        "missingReversals",
        "unexpectedReversals",
        "orphanReversals",
        "invalidRewardStatuses",
        "unexpectedLedgerKinds",
    )
    issue_count = sum(int(metrics[key]) for key in issue_keys)
    return {
        "ok": issue_count == 0,
        "state": "ready" if issue_count == 0 else "degraded",
        "issues": issue_count,
        "metrics": metrics,
    }


def main() -> int:
    try:
        report = status()
    except ReferralAuditUnavailable:
        report = {"ok": False, "state": "unavailable", "error": "referral_ledger_unavailable"}
        print(json.dumps(report, sort_keys=True))
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
