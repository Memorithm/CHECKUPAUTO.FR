from __future__ import annotations

import analytics_store as analytics
import referral_engine
import referral_wallet_claims


_REQUIRED_KEYS = {"installationId", "registrationSecret"}


def status(payload: dict) -> dict:
    """Return the referral-wallet state owned by one authenticated installation.

    The mobile installation secret is the authentication factor. Wallet ownership
    must already have been established through the one-time ``rw_`` claim flow.
    The response deliberately omits internal account IDs, reward appointment IDs,
    and ledger references. The referral code is returned because it is the public,
    shareable product code and is never accepted as ownership evidence.

    Legacy or corrupted ownership state that exceeds the mobile contract bound is
    rejected instead of being truncated. Silent truncation could make the app
    display an incomplete balance while presenting it as server-verified state.
    """
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_KEYS:
        raise ValueError("payload invalide")

    installation = referral_wallet_claims._authenticate_installation(
        payload.get("installationId"),
        payload.get("registrationSecret"),
    )
    account_ids = referral_wallet_claims.owned_account_ids(installation)
    if len(account_ids) > referral_wallet_claims._MAX_WALLETS_PER_INSTALLATION:
        raise RuntimeError("état de cagnotte mobile hors limite")
    referral_engine.init_db()

    wallets: list[dict] = []
    with analytics.connect() as db:
        for account_id in account_ids:
            account = db.execute(
                """SELECT code,active,reward_cents,currency
                   FROM referral_accounts WHERE id=? AND active=1""",
                (account_id,),
            ).fetchone()
            if not account:
                continue
            counts = {
                str(row["status"]): int(row["n"])
                for row in db.execute(
                    """SELECT status,COUNT(*) n
                       FROM referral_rewards
                       WHERE account_id=? GROUP BY status""",
                    (account_id,),
                )
            }
            pending_cents = int(
                db.execute(
                    """SELECT COALESCE(SUM(reward_cents),0) total
                       FROM referral_rewards
                       WHERE account_id=? AND status='pending'""",
                    (account_id,),
                ).fetchone()["total"]
            )
            wallets.append(
                {
                    "referralCode": str(account["code"]),
                    "active": bool(account["active"]),
                    "currency": str(account["currency"]),
                    "rewardCents": int(account["reward_cents"]),
                    "balanceCents": referral_engine._wallet_balance_locked(db, account_id),
                    "pendingCents": pending_cents,
                    "earnedReferrals": counts.get("earned", 0),
                    "pendingReferrals": counts.get("pending", 0),
                    "cancelledReferrals": counts.get("cancelled", 0),
                    "reversedReferrals": counts.get("reversed", 0),
                }
            )

    wallets.sort(key=lambda item: item["referralCode"])
    return {
        "ok": True,
        "walletCount": len(wallets),
        "wallets": wallets,
        "ownershipProvenance": "authenticated_mobile_wallet_claim",
        "shareCodeIsOwnershipProof": False,
        "accountIdentifiersExposed": False,
        "thirdPartyAppointmentIdentifiersExposed": False,
        "ledgerReferencesExposed": False,
    }
