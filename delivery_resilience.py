from __future__ import annotations

import datetime
import hashlib
from email.utils import parsedate_to_datetime

BASE_BACKOFF_SECONDS = 15
MAX_BACKOFF_SECONDS = 900
CIRCUIT_THRESHOLD = 3
CONFIGURATION_CIRCUIT_SECONDS = 300


def retry_after_seconds(
    value: object,
    *,
    now: datetime.datetime | None = None,
    cap: int = MAX_BACKOFF_SECONDS,
) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return min(max(0, int(raw)), cap)
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    current = now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    seconds = int((parsed.astimezone(datetime.timezone.utc) - current.astimezone(datetime.timezone.utc)).total_seconds())
    return min(max(0, seconds), cap)


def backoff_seconds(
    transport_key: str,
    attempt: int,
    *,
    retry_after: object = "",
    now: datetime.datetime | None = None,
) -> int:
    attempt = max(1, int(attempt))
    exponent = min(attempt - 1, 10)
    raw = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** exponent))
    seed = hashlib.sha256(f"{transport_key}:{attempt}".encode("utf-8")).digest()
    fraction = int.from_bytes(seed[:2], "big") / 65535
    jittered = max(1, int(round(raw * (0.75 + (fraction * 0.5)))))
    explicit = retry_after_seconds(retry_after, now=now)
    if explicit is not None:
        jittered = max(jittered, explicit)
    return min(MAX_BACKOFF_SECONDS, jittered)
