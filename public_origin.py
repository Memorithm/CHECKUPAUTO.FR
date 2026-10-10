"""Canonical public origin used for links sent outside the current request.

Links delivered by e-mail (account verification, password reset) and other
out-of-band URLs must never be derived from the client-controlled ``Host``
header. They come from ``CYBERCHECK_PUBLIC_ORIGINS`` (comma separated, first
entry is canonical) or, by default, the first-party checkupauto.fr origins.
A request Host is reused only when its origin is in that allow-list.
"""
from __future__ import annotations

import os
import re

DEFAULT_PUBLIC_ORIGIN = "https://www.checkupauto.fr"
# First-party origins accepted by default; the first one is canonical.
DEFAULT_ALLOWED_ORIGINS = (
    DEFAULT_PUBLIC_ORIGIN,
    "https://checkupauto.fr",
    "https://test.checkupauto.fr",
)
PUBLIC_ORIGINS_ENV = "CYBERCHECK_PUBLIC_ORIGINS"
_ORIGIN_RE = re.compile(r"https://[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[0-9]{1,5})?")


def _clean(value: object) -> str:
    raw = str(value or "").strip().lower().rstrip("/")
    return raw if _ORIGIN_RE.fullmatch(raw) else ""


def allowed_origins() -> tuple[str, ...]:
    configured = []
    for item in str(os.environ.get(PUBLIC_ORIGINS_ENV, "")).split(","):
        clean = _clean(item)
        if clean and clean not in configured:
            configured.append(clean)
    return tuple(configured) or DEFAULT_ALLOWED_ORIGINS


def canonical_origin() -> str:
    return allowed_origins()[0]


def origin_for_host(host: object) -> str:
    """Return the request origin only when it is explicitly allow-listed."""
    candidate = _clean("https://" + str(host or "").strip())
    allowed = allowed_origins()
    return candidate if candidate and candidate in allowed else allowed[0]
