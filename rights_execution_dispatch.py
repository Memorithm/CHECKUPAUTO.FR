from __future__ import annotations

from pathlib import Path

import booking_conversion_erasure
import contract_subject_rights
import data_subject_rights
import mobile_dsar_erasure
import mercure_rights
import provider_erasure_completion
import provider_erasure_plan
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


def _shared_mercure_erasure_inventory(subject_ref: object) -> tuple[tuple[str, ...] | None, str]:
    """Resolve one complete provider appointment set for all dependent erasure stores."""
    raw_ref = str(subject_ref or "").strip()
    try:
        mercure_rights.parse_subject_ref(raw_ref)
    except ValueError:
        return None, "mercure_subject_reference_required"

    try:
        snapshot = mercure_rights.contact_snapshot(raw_ref)
    except Exception:
        return None, "mercure_appointment_inventory_unavailable"

    coverage = snapshot.get("coverage") or {}
    if not bool(coverage.get("appointments")):
        return None, "mercure_appointment_inventory_incomplete"

    inventory = snapshot.get("operationalInventory") or {}
    rows = inventory.get("appointments") or []
    if not isinstance(rows, list):
        raise RuntimeError("inventaire Mercure des rendez-vous invalide")

    appointment_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("inventaire Mercure des rendez-vous invalide")
        appointment_id = str(row.get("appointmentId") or "").strip()
        if not appointment_id or len(appointment_id) > 128:
            raise RuntimeError("preuve Mercure de rendez-vous incomplète")
        appointment_ids.append(appointment_id)

    clean = tuple(sorted(set(appointment_ids)))
    limit = min(
        review_followup_privacy.MAX_APPOINTMENT_IDS,
        booking_conversion_erasure.MAX_APPOINTMENT_IDS,
    )
    if len(clean) > limit:
        raise RuntimeError("inventaire Mercure des rendez-vous trop volumineux")
    provider_count = int(inventory.get("appointmentCountInWindow") or 0)
    if provider_count != len(clean):
        raise RuntimeError("inventaire Mercure des rendez-vous incohérent")
    return clean, ""


def _provider_erasure_unavailable(store: str, reason: str) -> dict:
    return {
        "store": store,
        "executed": False,
        "coverageComplete": False,
        "reason": reason,
    }


def _provider_erasure_recovery_needed(
    body: dict,
    db_path: Path | str | None = None,
) -> bool:
    """Resume only a direct Mercure erasure whose provider tail is incomplete."""
    raw_ref = str(body.get("subjectRef") or "").strip()
    try:
        mercure_rights.parse_subject_ref(raw_ref)
        rid = data_subject_rights._request_id(body.get("id"))
    except ValueError:
        return False
    plan = provider_erasure_plan.load(rid, raw_ref)
    review_receipt = review_followup_privacy.receipt(rid)
    booking_receipt = booking_conversion_erasure.receipt(rid)
    completion = provider_erasure_completion.status(rid, db_path)
    return bool(
        plan is not None
        or review_receipt is None
        or booking_receipt is None
        or completion is None
    )


def execute(payload: object, db_path: Path | str | None = None) -> dict:
    """Route one verified DSAR operation to its narrow store adapter.

    The wallet adapter supports a second exact shape for continuing a previously
    staged large-ledger export. No cursor contents are accepted from the client:
    the opaque session id resolves server-side bounded state only. Mobile erasure
    uses a dedicated crash-recoverable boundary so the mobile receipt is durable
    before the separate compliance audit write.

    Review follow-up and booking conversions are keyed only by provider
    appointment ids. The dispatcher may resume an erasure whose central
    privacy-suppression audit already completed, so an interruption after that
    audit cannot strand the two crash-recoverable local receipts. After the
    central adapter has verified the rights request, an erasure may remove those
    local rows only
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
        execute_kwargs = {
            "adapter": adapter,
            "purpose": str(body.get("purpose") or ""),
            "db_path": db_path,
        }
        if adapter == "privacy_suppression":
            execute_kwargs["resume_completed_erasure"] = _provider_erasure_recovery_needed(
                body,
                db_path,
            )
        result = data_subject_rights.execute(
            body.get("id"),
            body.get("subjectRef"),
            **execute_kwargs,
        )
        if adapter == "privacy_suppression" and str(result.get("requestType") or "") == "erasure":
            # The central adapter has already reverified the request/subject pair.
            # Reuse that verified result rather than performing a second request
            # lookup. Each provider-reference adapter remains independently
            # fail-closed when the Mercure inventory is incomplete.
            rid = data_subject_rights._request_id(body.get("id"))
            subject_ref = str(body.get("subjectRef") or "").strip()
            result = dict(result)

            try:
                mercure_rights.parse_subject_ref(subject_ref)
            except ValueError:
                result["reviewFollowupErasure"] = _provider_erasure_unavailable(
                    "review_followup",
                    "mercure_subject_reference_required",
                )
                result["bookingConversionErasure"] = _provider_erasure_unavailable(
                    "booking_conversions",
                    "mercure_subject_reference_required",
                )
                return result

            review_receipt = review_followup_privacy.receipt(rid)
            booking_receipt = booking_conversion_erasure.receipt(rid)
            completion = provider_erasure_completion.status(rid, db_path)
            plan = provider_erasure_plan.load(rid, subject_ref)

            if completion is not None and plan is None:
                result["providerErasurePlanCleared"] = True
                result["providerErasureCompletion"] = completion
                if review_receipt is not None:
                    result["reviewFollowupErasure"] = {
                        **review_receipt,
                        "executed": True,
                        "coverageComplete": True,
                        "reason": "",
                    }
                if booking_receipt is not None:
                    result["bookingConversionErasure"] = {
                        **booking_receipt,
                        "executed": True,
                        "coverageComplete": True,
                        "reason": "",
                    }
                return result

            if (
                plan is None
                and review_receipt is not None
                and booking_receipt is not None
            ):
                completion = provider_erasure_completion.record(
                    rid,
                    review_receipt,
                    booking_receipt,
                    db_path,
                )
                result["providerErasureCompletion"] = completion
                result["providerErasurePlanCleared"] = True
                result["reviewFollowupErasure"] = {
                    **review_receipt,
                    "executed": True,
                    "coverageComplete": True,
                    "reason": "",
                }
                result["bookingConversionErasure"] = {
                    **booking_receipt,
                    "executed": True,
                    "coverageComplete": True,
                    "reason": "",
                }
                return result

            if plan is None:
                appointment_ids, inventory_reason = _shared_mercure_erasure_inventory(
                    subject_ref
                )
                if inventory_reason:
                    result["reviewFollowupErasure"] = _provider_erasure_unavailable(
                        "review_followup",
                        inventory_reason,
                    )
                    result["bookingConversionErasure"] = _provider_erasure_unavailable(
                        "booking_conversions",
                        inventory_reason,
                    )
                    return result
                assert appointment_ids is not None
                plan = provider_erasure_plan.stage(
                    rid,
                    subject_ref,
                    appointment_ids,
                )

            appointment_ids = tuple(plan["appointmentIds"])
            review_mutation = review_followup_privacy.erase_appointments(
                rid,
                appointment_ids,
            )
            result["reviewFollowupErasure"] = {
                **review_mutation,
                "executed": True,
                "coverageComplete": True,
                "reason": "",
            }
            booking_mutation = booking_conversion_erasure.erase_appointments(
                rid,
                appointment_ids,
            )
            result["bookingConversionErasure"] = {
                **booking_mutation,
                "executed": True,
                "coverageComplete": True,
                "reason": "",
            }
            completion = provider_erasure_completion.record(
                rid,
                review_mutation,
                booking_mutation,
                db_path,
            )
            result["providerErasureCompletion"] = completion
            result["providerErasurePlanCleared"] = provider_erasure_plan.clear(
                rid,
                subject_ref,
                completion["appointmentSetHash"],
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
