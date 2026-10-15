#!/usr/bin/env python3
"""Read-only Cloudflare Pages public bundle live preflight (no credentials)."""
import hashlib
import json
import sys
import urllib.error
import urllib.request

BASE = "https://checkupauto-fr.pages.dev"
SAMPLE = (
    "assets/illustrations/checkupauto-lavis-option2-1020.webp",
    "assets/illustrations/checkupauto-lavis-option2-765.webp",
    "style.css",
    "app.js",
    "assets/3d/CyberCheckVehicle_Photo3D.glb",
)
DENIED = ("admin/index.html", "api/customer/vehicles", "private/oidc.json", "data/site-config.json")
LIMIT = 3 * 1024 * 1024


def get(path: str) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(
        BASE + "/" + path, headers={"User-Agent": "CheckupAuto-Pages-Public-Preflight/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.url != BASE + "/" + path:
                raise ValueError("unexpected_redirect")
            body = res.read(LIMIT + 1)
            return res.status, dict(res.headers.items()), body
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), b""


def main() -> int:
    status, headers, raw = get("public-assets-manifest.json")
    if status != 200 or len(raw) > LIMIT:
        raise ValueError("manifest_unavailable")
    manifest = json.loads(raw)
    by_name = {entry["path"]: entry for entry in manifest["assets"]}
    if len(by_name) != len(manifest["assets"]):
        raise ValueError("manifest_duplicate_entry")
    for name in SAMPLE:
        if name not in by_name:
            raise ValueError("missing_manifest_entry")
        status, headers, data = get(name)
        if status != 200 or len(data) != by_name[name]["bytes"]:
            raise ValueError("static_origin_response_invalid_" + name.rsplit("/", 1)[-1])
        if hashlib.sha256(data).hexdigest() != by_name[name]["sha256"]:
            raise ValueError("static_origin_hash_mismatch_" + name.rsplit("/", 1)[-1])
        if "set-cookie" in {k.lower() for k in headers}:
            raise ValueError("unexpected_static_cookie")
        print("CLOUDFLARE_PAGES_PUBLIC_ASSET_OK " + name)
    for name in DENIED:
        code, _, _ = get(name)
        if code != 404:
            raise ValueError("private_path_exposed_" + name.rsplit("/", 1)[-1])
    print(f"CLOUDFLARE_PAGES_PUBLIC_ORIGIN_PASS sha256_count={len(SAMPLE)} private_paths={len(DENIED)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write("CLOUDFLARE_PAGES_PUBLIC_ORIGIN_BLOCKED " + type(exc).__name__ +
                         " " + str(exc)[:120] + "\n")
        sys.exit(1)
