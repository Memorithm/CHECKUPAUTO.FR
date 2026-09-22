from __future__ import annotations

import json
import sys
from typing import TextIO

import referral_wallet_claims as claims


MAX_STDIN_BYTES = 16 * 1024
_COMMANDS = {"issue", "status"}


def _read_payload(stream: TextIO) -> dict:
    raw = stream.read(MAX_STDIN_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError("payload_too_large")
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(parsed, dict):
        raise ValueError("invalid_payload")
    return parsed


def _write(stream: TextIO, value: dict) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


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
        _write(output_stream, {"ok": False, "error": "usage_error"})
        return 2
    command = args[0]
    try:
        if command == "status":
            _write(output_stream, {"ok": True, "capability": claims.capability()})
            return 0
        payload = _read_payload(input_stream)
        if set(payload) - {"code", "ttlSeconds"} or not payload.get("code"):
            raise ValueError("invalid_payload")
        result = claims.issue(payload.get("code"), payload.get("ttlSeconds", 1800))
        _write(output_stream, {"ok": True, "claim": result})
        return 0
    except (ValueError, LookupError, PermissionError):
        _write(output_stream, {"ok": False, "error": "invalid_or_unauthorized_request"})
        return 2
    except Exception:
        _write(output_stream, {"ok": False, "error": "internal_error"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
