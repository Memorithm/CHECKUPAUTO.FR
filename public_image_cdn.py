"""Optional image-only Cloudflare Pages CDN for the anonymous homepage.

Staging-only automatic pilot uses the verified public Pages asset domain.
Production is OFF by default. Explicit override via
CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN=off immediately disables the pilot once
Passenger reloads. Only anonymous homepage image attributes are rewritten;
account, API, OAuth, Mercure, cookies, JS and stylesheets stay same origin.
"""
from __future__ import annotations

import os
import re

_ALLOWED_ORIGINS = frozenset((
    "https://checkupauto-fr.pages.dev",
    "https://static.checkupauto.fr",
))
_STAGING_HOST = "test.checkupauto.fr"
_STAGING_PAGES_ORIGIN = "https://checkupauto-fr.pages.dev"
_ENV = "CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN"

_ATTR = re.compile(
    r"""\b(?P<key>src|srcset|imagesrcset|href)=(?P<quote>["'])(?P<value>[^"']*)(?P=quote)"""
)
_PUBLIC_IMAGE = re.compile(
    r"/assets/(?:(?:illustrations|premium|guides|app)/[A-Za-z0-9._/-]+"
    r"\.(?:webp|png|jpe?g|svg|gif|ico)|checkupauto-centre-map-osm\.webp)"
)


def rewrite_homepage_images(
    html: str, *, origin: str | None = None, host: str = ""
) -> str:
    """Use Pages on verified test host only, unless an approved operator flag overrides.

    The explicit env value `off` disables the CDN without a code rollback.
    Production never uses Pages by default; host is an exact comparison.
    """
    if origin is None:
        flag = os.environ.get(_ENV)
        if flag is None:
            chosen = _STAGING_PAGES_ORIGIN if host == _STAGING_HOST else ""
        else:
            chosen = flag
    else:
        chosen = origin
    if chosen not in _ALLOWED_ORIGINS:
        return html

    def rewrite_attr(match: re.Match) -> str:
        value = match.group("value")
        changed = _PUBLIC_IMAGE.sub(lambda image: chosen + image.group(0), value)
        return match.group("key") + "=" + match.group("quote") + changed + match.group("quote")

    return _ATTR.sub(rewrite_attr, html)
