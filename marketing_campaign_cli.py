from __future__ import annotations

import json
import sys
from typing import TextIO

import marketing_campaigns


MAX_STDIN_BYTES = 256 * 1024
_COMMANDS = {"status", "email", "push"}


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
                "capability": marketing_campaigns.capability(),
                "recentRuns": marketing_campaigns.recent_runs(limit=50),
            }
        else:
            payload = _read_payload(input_stream)
            if command == "email":
                run = marketing_campaigns.run_email_campaign(
                    payload.get("recipients"),
                    payload.get("subject"),
                    payload.get("text"),
                    payload.get("html", ""),
                    reference=payload.get("reference"),
                )
            else:
                run = marketing_campaigns.run_push_campaign(
                    payload.get("installationIds"),
                    payload.get("title"),
                    payload.get("body"),
                    reference=payload.get("reference"),
                    data=payload.get("data"),
                )
            result = {"ok": True, "run": run}
    except (ValueError, PermissionError):
        _emit(output_stream, {"ok": False, "error": "invalid_or_unauthorized_request"})
        return 2
    except Exception:
        _emit(output_stream, {"ok": False, "error": "internal_error"})
        return 1
    _emit(output_stream, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
