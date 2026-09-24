from __future__ import annotations

from pathlib import Path

import booking_conversion_erasure
import contract_subject_rights
import data_subject_rights
import mobile_dsar_erasure
import referral_wallet_rights
import review_followup_privacy
import rights_completion_plan
import rights_rectification
import withdrawal_rights


_BASE_FIELDS = {"id", "subjectRef", "adapter"}


def _payload(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("payload d'exécution de droit invalide")
    return value


def _exact_fields(payload: dict, fields: set[str]) -> None:
    if set(payload) != fields:
        raise ValueError("payload d'exécution de droit invalide")


def execute(payload: object, db_path: Path | str | None = None) -> dict:
    """Route one verified DSAR operation to its narrow store adapter.

    The wallet adapter supports a second exact shape for continuing a previously
    staged large-ledger export. No cursor contents are accepted from the client:
    the opaque session id resolves server-side bounded state only. Mobile erasure
    uses a dedicated crash-recoverable boundary so the mobile receipt is durable
    before the separate compliance audit write.

    Review follow-up and booking conversions are keyed only by provider
    appointment ids. After the central privacy-suppression adapter has verified
    the rights request, an erasure may therefore remove those local rows only
    when Mercure independently proves a complete appointment inventory for the
    submitted provider subject reference.
    """
    body = _payload(payload)
    adapter = str(body.get("adapter") or "").strip()

    if adapter == contract_subject_rights.ADAPTER:
        _exact_fields(body, _BASE_FIELDS)
        return contract_subject_rights.execute(
            body.get("id"),
            body.get("subjectRef"),
            db_path,
        )

    if adapter == withdrawal_rights.ADAPTER:
        _exact_fields(body, _BASE_FIELDS)
        return withdrawal_rights.execute(
            body.get("id"),
            body.get("subjectRef"),
            db_path,
        )

    if adapter in data_subject_rights.SUPPORTED_ADAPTERS:
        allowed = set(_BASE_FIELDS)
        if adapter == "privacy_suppression":
            allowed.add("purpose")
        _exact_fields(body, allowed if "purpose" in body else _BASE_FIELDS)
        if adapter == mobile_dsar_erasure.ADAPTER:
            rid = data_subject_rights._request_id(body.get("id"))
            request = data_subject_rights._request(rid, db_path)
            if str(request["request_type"]) == mobile_dsar_erasure.RIGHT:
                return mobile_dsar_erasure.execute(
                    rid,
                    body.get("subjectRef"),
                    db_path,
                )
        result = data_subject_rights.execute(
            body.get("id"),
            body.get("subjectRef"),
            adapter=adapter,
            purpose=str(body.get("purpose") or ""),
            db_path=db_path,
        )
        if adapter == "privacy_suppression" and str(result.get("requestType") or "") == "erasure":
            # The central adapter has already reverified the request/subject pair.
            # Reuse that verified result rather than performing a second request
            # lookup. Each provider-reference adapter remains independently
            # fail-closed when the Mercure inventory is incomplete.
            rid = data_subject_rights._request_id(body.get("id"))
            result = dict(result)
            result["reviewFollowupErasure"] = review_followup_privacy.erase_for_mercure_subject(
                rid,
                body.get("subjectRef"),
            )
            result["bookingConversionErasure"] = booking_conversion_erasure.erase_for_mercure_subject(
                rid,
                body.get("subjectRef"),
            )
        return result

    if adapter == rights_rectification.ADAPTER:
        _exact_fields(body, _BASE_FIELDS | {"correction"})
        return rights_rectification.execute(
            body.get("id"),
            body.get("subjectRef"),
            body.get("correction"),
            db_path,
        )

    if adapter == referral_wallet_rights.ADAPTER:
        continuation_fields = _BASE_FIELDS | {"accountId", "pagedExportSessionId"}
        if "pagedExportSessionId" in body:
            _exact_fields(body, continuation_fields)
            return referral_wallet_rights.continue_export(
                body.get("id"),
                body.get("subjectRef"),
                body.get("accountId"),
                body.get("pagedExportSessionId"),
                db_path,
            )
        _exact_fields(body, _BASE_FIELDS | {"accountId"})
        return referral_wallet_rights.execute(
            body.get("id"),
            body.get("subjectRef"),
            body.get("accountId"),
            db_path,
        )

    raise ValueError("adaptateur de droit non pris en charge")


def capability(db_path: Path | str | None = None) -> dict:
    central = {
        name: list(rights)
        for name, rights in sorted(data_subject_rights.SUPPORTED_ADAPTERS.items())
    }
    rectification = rights_rectification.capability()
    wallet = referral_wallet_rights.capability(db_path)
    contracts = contract_subject_rights.capability()
    withdrawal = withdrawal_rights.capability()
    adapters = dict(central)
    adapters[rights_rectification.ADAPTER] = [rectification["requestType"]]
    adapters[referral_wallet_rights.ADAPTER] = list(wallet.get("supportedRights") or [])
    adapters[withdrawal_rights.ADAPTER] = list(withdrawal.get("supportedRights") or [])
    return {
        "dispatchReady": True,
        "globalCoverageComplete": False,
        "supportedAdapters": adapters,
        "contractSubject": contracts,
        "withdrawalEvidence": withdrawal,
        "rectification": rectification,
        "referralWallet": wallet,
        "completionPlan": rights_completion_plan.capability(),
        "rawPayloadPersistedByDispatcher": False,
    }
