#!/usr/bin/env python3
"""Build a public-only static asset bundle for Cloudflare Pages Free.

This exporter is intentionally an allowlist, never a repository mirror:
admin/, databases, secrets, Python runtime and customer data are prohibited.
The entire bundle can be published on static.checkupauto.fr without migrating
CheckupAuto's authoritative DNS or affecting PlanetHoster / Mercure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".cloudflare-pages-public"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 90 * 1024 * 1024
MAX_FILES = 250

ROOT_FILES = (
    "style.css", "app.js", "consent.js",
    "assets/action-controls.css", "assets/booking-date-reference.css",
    "assets/booking-journey.css", "assets/booking-journey.js",
    "assets/checkupauto-centre-map-osm.webp", "assets/vehicle.png",
    "assets/cybercheck-glb-hero.js", "assets/cybercheck-hero-3d.js",
    "assets/public-asset-cache.js",
    "assets/3d/CyberCheckVehicle_Photo3D.glb",
)
PUBLIC_DIRS = (
    "assets/illustrations", "assets/guides", "assets/premium", "assets/app",
)
ALLOWED_SUFFIXES = {
    ".css", ".js", ".webp", ".png", ".jpg", ".jpeg", ".svg",
    ".ico", ".mp4", ".webm", ".glb", ".gltf", ".bin", ".wasm", ".ktx2",
}
# These two optional root paths may be absent on an intermediate release.
OPTIONAL_FILES = ("favicon.ico", "favicon.png")


def selected_files(root: Path = ROOT) -> list[Path]:
    result = []
    for literal in ROOT_FILES:
        p = root / literal
        if not p.is_file() or p.is_symlink():
            raise ValueError("missing_public_asset")
        result.append(p)
    for name in OPTIONAL_FILES:
        p = root / name
        if p.exists():
            if not p.is_file() or p.is_symlink():
                raise ValueError("invalid_public_asset")
            result.append(p)
    for directory in PUBLIC_DIRS:
        base = root / directory
        if not base.is_dir() or base.is_symlink():
            raise ValueError("missing_public_directory")
        for p in sorted(base.rglob("*")):
            if p.is_symlink():
                raise ValueError("public_asset_symlink")
            if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES:
                result.append(p)
    selected = sorted(set(result))
    if not selected or len(selected) > MAX_FILES:
        raise ValueError("public_asset_count_invalid")
    total = 0
    for p in selected:
        relative = p.relative_to(root)
        if ("admin" in relative.parts or "private" in relative.parts
                or "data" in relative.parts or p.suffix.lower() not in ALLOWED_SUFFIXES):
            raise ValueError("private_asset_forbidden")
        size = p.stat().st_size
        if not (0 < size <= MAX_FILE_BYTES):
            raise ValueError("public_asset_size_invalid")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("public_asset_total_size_invalid")
    return selected


def build(root: Path = ROOT, output: Path = OUTPUT) -> dict:
    root = root.resolve()
    expected = (root / ".cloudflare-pages-public").resolve()
    if output.resolve() != expected or output.is_symlink():
        raise ValueError("unapproved_pages_output")
    selected = selected_files(root)
    if output.exists():
        if not (output / "_headers").is_file():
            raise ValueError("unmanaged_pages_output")
        shutil.rmtree(output)
    output.mkdir(parents=True)
    manifest = []
    for p in selected:
        rel = p.relative_to(root)
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        manifest.append({"path": rel.as_posix(),
                         "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                         "bytes": target.stat().st_size})
    # The static host is not indexed; Pages already sends ETags and Brotli.
    # No service worker or Pages Function ever receives customer requests.
    header_lines = (
        "/*",
        "  X-Robots-Tag: noindex, nofollow",
        "  X-Content-Type-Options: nosniff",
        "  Referrer-Policy: strict-origin-when-cross-origin",
    )
    (output / "_headers").write_text(
        "\\n".join(header_lines).replace("\\\\n", "\\n") + "\\n",
        encoding="utf-8",
    )
    (output / "public-assets-manifest.json").write_text(
        json.dumps({"schemaVersion": 1, "assets": manifest},
                   sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {"files": len(manifest), "bytes": sum(x["bytes"] for x in manifest)}


if __name__ == "__main__":
    result = build()
    print(f"CHECKUPAUTO_CLOUDFLARE_PAGES_BUNDLE_OK files={result['files']} bytes={result['bytes']}")
