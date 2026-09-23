from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

import referral_wallet_rights as rights


MAX_STDIN_BYTES = 32 * 1024


def _read(stream: TextIO) -> dict:
    raw = stream.read(MAX_STDIN_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_STDIN_BYTES:
        raise ValueError("payload_too_large")
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid_payload")
    return value


def _write(stream: TextIO, value: dict) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    db_path: Path | str | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    if len(args) != 1 or args[0] not in {"execute", "continue", "status"}:
        _write(output_stream, {"ok": False, "error": "usage_error"})
        return 2
    try:
        if args[0] == "status":
            _write(output_stream, {"ok": True, "capability": rights.capability(db_path)})
            return 0
        payload = _read(input_stream)
        if args[0] == "execute":
            if set(payload) != {"requestId", "installationId", "accountId"}:
                raise ValueError("invalid_payload")
            result = rights.execute(
                payload.get("requestId"),
                payload.get("installationId"),
                payload.get("accountId"),
                db_path,
            )
        else:
            if set(payload) != {
                "requestId",
                "installationId",
                "accountId",
                "sessionId",
            }:
                raise ValueError("invalid_payload")
            result = rights.continue_export(
                payload.get("requestId"),
                payload.get("installationId"),
                payload.get("accountId"),
                payload.get("sessionId"),
                db_path,
            )
        _write(output_stream, result)
        return 0
    except (ValueError, LookupError, PermissionError, NotImplementedError, RuntimeError):
        _write(output_stream, {"ok": False, "error": "invalid_or_unauthorized_request"})
        return 2
    except Exception:
        _write(output_stream, {"ok": False, "error": "internal_error"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
