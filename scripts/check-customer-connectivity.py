#!/usr/bin/env python3
"""Read-only and deliberately unauthorized account-route smoke probes.

Never follows OAuth redirects, never sends credentials or customer data, and
never logs Location, cookies, state, PKCE or response bodies. The authenticated
journey requires a separate, consented test account.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cases():
    challenge = base64.urlsafe_b64encode(hashlib.sha256(os.urandom(32)).digest()).decode().rstrip("=")
    return [
        ("home", "/", "GET", None, {200}),
        ("account-login", "/compte", "GET", None, {200}),
        ("google-web", "/auth/customer/google", "GET", None, {302}),
        ("google-mobile", "/auth/customer/google?mobile=1&code_challenge=" + challenge, "GET", None, {302}),
        ("apple-web", "/auth/customer/apple", "GET", None, {302}),
        ("providers", "/api/customer/auth/providers", "GET", None, {200}),
        ("bootstrap", "/api/mobile/bootstrap", "GET", None, {200}),
        ("web-session-no-bearer", "/api/mobile/auth/web-session", "POST", b"{}", {401}),
    ]


def probe(origin, repeat=2, timeout=15):
    opener = build_opener(NoRedirect())
    failed = []
    for iteration in range(1, repeat + 1):
        for name, path, method, body, expected in cases():
            request = Request(
                origin + path, data=body, method=method,
                headers={"Accept": "application/json, text/html",
                         "Content-Type": "application/json"},
            )
            started = time.monotonic()
            try:
                try:
                    response = opener.open(request, timeout=timeout)
                except HTTPError as exc:
                    response = exc
                with response:
                    status = response.status
                    location = response.headers.get("Location", "")
                    if status == 302 and name.startswith("google"):
                        valid_redirect = urlsplit(location).hostname == "accounts.google.com"
                    elif status == 302 and name == "apple-web":
                        valid_redirect = urlsplit(location).hostname == "appleid.apple.com"
                    else:
                        valid_redirect = True
                good = status in expected and valid_redirect
                duration = time.monotonic() - started
                print(f"ACCOUNT_CONNECTIVITY case={name} iteration={iteration} http={status} "
                      f"elapsed={duration:.3f}s valid={good}", flush=True)
                if not good:
                    failed.append((name, iteration, status))
            except (URLError, TimeoutError, OSError) as exc:
                duration = time.monotonic() - started
                print(f"ACCOUNT_CONNECTIVITY case={name} iteration={iteration} "
                      f"error_class={type(exc).__name__} elapsed={duration:.3f}s valid=False",
                      flush=True)
                failed.append((name, iteration, "network"))
    print(f"ACCOUNT_CONNECTIVITY_SUMMARY checks={repeat * len(cases())} failures={len(failed)}",
          flush=True)
    return not failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="https://test.checkupauto.fr")
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    if args.origin != "https://test.checkupauto.fr":
        parser.error("only the preproduction host is authorized")
    if not 1 <= args.repeat <= 3:
        parser.error("repeat must be between 1 and 3")
    raise SystemExit(0 if probe(args.origin, args.repeat) else 1)


if __name__ == "__main__":
    main()
