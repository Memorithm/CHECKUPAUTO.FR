from __future__ import annotations

import json
import sys
from typing import TextIO

import data_subject_rights
import rights_rectification
import rights_subject_bindings


MAX_STDIN_BYTES = 64 * 1024
_COMMANDS = {"status", "prove-contract", "bindings", "rectify-mobile-deadline"}


def _read_payload(stream: TextIO) -> dict:
    raw = stream.read(MAX_STDIN_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError("payload_too_large")
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    return payload


def _emit(stream: TextIO, payload: dict) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    stream.write("\n")


def _binding_projection(row: dict) -> dict:
    return {
        "requestId": str(row.get("requestId") or ""),
        "adapter": str(row.get("adapter") or ""),
        "provenance": str(row.get("provenance") or ""),
        "evidenceHash": str(row.get("evidenceHash") or ""),
        "createdAt": str(row.get("createdAt") or ""),
    }


def _proof_projection(result: dict) -> dict:
    if result.get("bound") is not True:
        raise RuntimeError("preuve non établie")
    if result.get("rawSubjectReferencePersisted") is not False:
        raise RuntimeError("preuve de confidentialité absente")
    projected = {
        "adapter": str(result.get("adapter") or ""),
        "provenance": str(result.get("provenance") or ""),
        "rawSubjectReferencePersisted": False,
    }
    for key in ("bindingCount", "appointmentMatchCount", "checkoutAcceptanceCount"):
        if key in result:
            projected[key] = int(result[key])
    return projected


def _prove_contract(payload: dict) -> dict:
    request_id = payload.get("requestId")
    installation_id = payload.get("installationId")
    mercure_subject_ref = payload.get("mercureSubjectRef")
    contract_ref = payload.get("contractRef")
    mercure = data_subject_rights.bind_mercure_from_mobile(
        request_id,
        installation_id,
        mercure_subject_ref,
    )
    contract = rights_subject_bindings.bind_contract_from_mercure(
        request_id,
        mercure_subject_ref,
        contract_ref,
    )
    return {
        "ok": True,
        "proof": {
            "mercure": _proof_projection(mercure),
            "contract": _proof_projection(contract),
        },
    }


def _rectification_projection(result: dict) -> dict:
    return {
        "ok": result.get("ok") is True,
        "adapter": str(result.get("adapter") or ""),
        "field": str(result.get("field") or ""),
        "source": str(result.get("source") or ""),
        "updated": result.get("updated") is True,
        "executionId": str(result.get("executionId") or ""),
        "requestStatus": str(result.get("requestStatus") or ""),
        "requestComplete": result.get("requestComplete") is True,
    }


def _rectify_mobile_deadline(payload: dict) -> dict:
    result = rights_rectification.execute(
        payload.get("requestId"),
        payload.get("installationId"),
        payload.get("correction"),
    )
    return _rectification_projection(result)


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    if len(args) != 1 or args[0] not in _COMMANDS:
        _emit(output_stream, {"ok": False, "error": "usage"})
        return 2

    command = args[0]
    try:
        if command == "status":
            result = {
                "ok": True,
                "capability": {
                    "sensitiveInput": "stdin",
                    "directBindingAllowed": False,
                    "contractProofChain": [
                        "mobile_vehicle_binding",
                        "mercure_appointment",
                        "local_checkout_acceptance",
                    ],
                    "rectification": rights_rectification.capability(),
                },
            }
        elif command == "bindings":
            result = {
                "ok": True,
                "bindings": [
                    _binding_projection(row)
                    for row in rights_subject_bindings.rows(limit=50)
                ],
            }
        elif command == "prove-contract":
            result = _prove_contract(_read_payload(input_stream))
        else:
            result = _rectify_mobile_deadline(_read_payload(input_stream))
    except (ValueError, LookupError, PermissionError, RuntimeError, NotImplementedError):
        _emit(output_stream, {"ok": False, "error": "invalid_or_unauthorized_request"})
        return 2
    except Exception:
        _emit(output_stream, {"ok": False, "error": "internal_error"})
        return 1

    _emit(output_stream, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
