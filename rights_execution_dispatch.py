from __future__ import annotations

from pathlib import Path

import data_subject_rights
import referral_wallet_rights
import rights_completion_plan
import rights_rectification


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

    This boundary intentionally accepts an exact payload per adapter. It keeps
    the existing admin request shape (``id``, ``subjectRef``, ``adapter``) while
    making the newer bounded rectification and referral-wallet executors
    reachable through the same operator surface. Each delegated adapter remains
    responsible for subject proof, request-type validation, duplicate execution
    prevention and evidence hashing.
    """
    body = _payload(payload)
    adapter = str(body.get("adapter") or "").strip()

    if adapter in data_subject_rights.SUPPORTED_ADAPTERS:
        allowed = set(_BASE_FIELDS)
        if adapter == "privacy_suppression":
            allowed.add("purpose")
        _exact_fields(body, allowed if "purpose" in body else _BASE_FIELDS)
        return data_subject_rights.execute(
            body.get("id"),
            body.get("subjectRef"),
            adapter=adapter,
            purpose=str(body.get("purpose") or ""),
            db_path=db_path,
        )

    if adapter == rights_rectification.ADAPTER:
        _exact_fields(body, _BASE_FIELDS | {"correction"})
        return rights_rectification.execute(
            body.get("id"),
            body.get("subjectRef"),
            body.get("correction"),
            db_path,
        )

    if adapter == referral_wallet_rights.ADAPTER:
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
    adapters = dict(central)
    adapters[rights_rectification.ADAPTER] = [rectification["requestType"]]
    adapters[referral_wallet_rights.ADAPTER] = list(wallet.get("supportedRights") or [])
    return {
        "dispatchReady": True,
        "globalCoverageComplete": False,
        "supportedAdapters": adapters,
        "rectification": rectification,
        "referralWallet": wallet,
        "completionPlan": rights_completion_plan.capability(),
        "rawPayloadPersistedByDispatcher": False,
    }
