from __future__ import annotations

import datetime
import os
import re


HISTORY_START_ENV = "CYBERCHECK_MERCURE_DSAR_HISTORY_START"
FUTURE_DAYS_ENV = "CYBERCHECK_MERCURE_DSAR_FUTURE_DAYS"
EVIDENCE_SHA256_ENV = "CYBERCHECK_MERCURE_DSAR_COVERAGE_EVIDENCE_SHA256"
MAX_FUTURE_DAYS = 3650
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _invalid(reason: str) -> dict:
    return {
        "state": "invalid",
        "attested": False,
        "historyStart": "",
        "futureDays": 0,
        "evidenceSha256": "",
        "reason": reason,
    }


def boundary(today: datetime.date | None = None) -> dict:
    """Return a non-secret provider coverage boundary attestation.

    CheckupAuto must not infer Mercure's historical or future data boundary from
    an empty query result. Completeness may only be considered after an operator
    configures a provider/contract-backed boundary and the SHA-256 of the
    external evidence supporting it. The evidence itself remains outside Git.
    """
    current = today or datetime.date.today()
    history_raw = os.environ.get(HISTORY_START_ENV, "").strip()
    future_raw = os.environ.get(FUTURE_DAYS_ENV, "").strip()
    evidence_raw = os.environ.get(EVIDENCE_SHA256_ENV, "").strip().lower()

    if not history_raw and not future_raw and not evidence_raw:
        return {
            "state": "unconfigured",
            "attested": False,
            "historyStart": "",
            "futureDays": 0,
            "evidenceSha256": "",
            "reason": "provider_boundary_not_attested",
        }
    if not history_raw or not future_raw or not evidence_raw:
        return _invalid("provider_boundary_configuration_incomplete")

    try:
        history_start = datetime.date.fromisoformat(history_raw)
    except ValueError:
        return _invalid("provider_history_start_invalid")
    if history_start > current:
        return _invalid("provider_history_start_in_future")

    try:
        future_days = int(future_raw)
    except ValueError:
        return _invalid("provider_future_horizon_invalid")
    if future_days < 0 or future_days > MAX_FUTURE_DAYS:
        return _invalid("provider_future_horizon_out_of_range")
    if not _SHA256_RE.fullmatch(evidence_raw):
        return _invalid("provider_evidence_hash_invalid")

    return {
        "state": "attested",
        "attested": True,
        "historyStart": history_start.isoformat(),
        "futureDays": future_days,
        "evidenceSha256": evidence_raw,
        "reason": "",
    }


def capability() -> dict:
    return {
        "requiresExplicitProviderBoundary": True,
        "requiresExternalEvidenceSha256": True,
        "rawEvidenceStoredInRepository": False,
        "emptyResultProvesHistoricalExhaustion": False,
        "maxConfiguredFutureDays": MAX_FUTURE_DAYS,
    }
