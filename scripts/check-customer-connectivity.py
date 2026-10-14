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
import subprocess
from urllib.parse import urlsplit


def cases():
    challenge = base64.urlsafe_b64encode(hashlib.sha256(os.urandom(32)).digest()).decode().rstrip("=")
    return [
        ("home", "/", "GET", None, {200}),
        ("account-login", "/compte", "GET", None, {200}),
        ("google-web", "/auth/customer/google", "GET", None, {302}),
        ("google-mobile", "/auth/customer/google?mobile=1&code_challenge=" + challenge, "GET", None, {302}),
        ("apple-web", "/auth/customer/apple", "GET", None, {302}),
        ("providers", "/api/customer/providers", "GET", None, {200}),
        ("bootstrap", "/api/mobile/bootstrap", "GET", None, {200}),
        ("web-session-no-bearer", "/api/mobile/auth/web-session", "POST", b"{}", {401}),
    ]


def probe(origin, repeat=2, timeout=15):
    # curl is the supported HTTP client for the staging edge. macOS and Linux
    # curl receive 200/302 while Python urllib receives a uniform 403, likely
    # from edge client filtering. Never follow or print OAuth redirect URLs.
    failed = []
    for iteration in range(1, repeat + 1):
        for name, path, method, body, expected in cases():
            args = [
                "curl", "--silent", "--show-error", "--output", "/dev/null",
                "--max-time", str(timeout), "--connect-timeout", "5",
                "--request", method,
                "--write-out", "%{http_code} %{time_total} %{redirect_url}",
            ]
            if body is not None:
                args += ["--header", "Content-Type: application/json",
                         "--data-binary", body.decode("ascii")]
            args.append(origin + path)
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=timeout + 3,
                    check=False,
                )
                code, seconds, redirect = result.stdout.rstrip("\n").split(" ", 2)
                status = int(code)
                duration = float(seconds)
                host = urlsplit(redirect).hostname
                if status == 302 and name.startswith("google"):
                    valid_redirect = host == "accounts.google.com"
                elif status == 302 and name == "apple-web":
                    valid_redirect = host == "appleid.apple.com"
                else:
                    valid_redirect = True
                # 8s is a guardrail, not a claim about real iPhone latency.
                good = result.returncode == 0 and status in expected and valid_redirect and duration <= 8
                print(f"ACCOUNT_CONNECTIVITY case={name} iteration={iteration} "
                      f"http={status} elapsed={duration:.3f}s valid={good}",
                      flush=True)
                if not good:
                    failed.append((name, iteration, status))
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                print(f"ACCOUNT_CONNECTIVITY case={name} iteration={iteration} "
                      f"error_class={type(exc).__name__} valid=False", flush=True)
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
