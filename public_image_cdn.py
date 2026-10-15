"""Optional image-only Cloudflare Pages CDN for the anonymous homepage.

The flag is OFF by default. The only accepted CDN host is the dedicated
static CheckupAuto domain, and only static image attributes in the checked-in
homepage template are rewritten. This never redirects accounts, APIs, OAuth,
Mercure, cookies, JavaScript, or stylesheets to Cloudflare.
"""
from __future__ import annotations

import os
import re

_ALLOWED_ORIGIN = "https://static.checkupauto.fr"
_ENV = "CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN"

_ATTR = re.compile(
    r"""\b(?P<key>src|srcset|imagesrcset|href)=(?P<quote>["'])(?P<value>[^"']*)(?P=quote)"""
)
_PUBLIC_IMAGE = re.compile(
    r"/assets/(?:(?:illustrations|premium|guides|app)/[A-Za-z0-9._/-]+"
    r"\.(?:webp|png|jpe?g|svg|gif|ico)|checkupauto-centre-map-osm\.webp)"
)


def rewrite_homepage_images(html: str, *, origin: str | None = None) -> str:
    chosen = os.environ.get(_ENV, "") if origin is None else origin
    if str(chosen).strip() != _ALLOWED_ORIGIN:
        return html

    def rewrite_attr(match: re.Match) -> str:
        value = match.group("value")
        changed = _PUBLIC_IMAGE.sub(lambda image: _ALLOWED_ORIGIN + image.group(0), value)
        return match.group("key") + "=" + match.group("quote") + changed + match.group("quote")

    return _ATTR.sub(rewrite_attr, html)
