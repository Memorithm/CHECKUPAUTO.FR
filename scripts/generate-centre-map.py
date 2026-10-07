#!/usr/bin/env python3
"""Generate the locally served OpenStreetMap image for the Checkup Auto centre.

The generated asset is intentionally stored in the repository so the public page
loads no third-party map resources. Regeneration is manual and must keep visible
OpenStreetMap attribution in the HTML that embeds the image.
"""
from __future__ import annotations

import io
import math
import sys
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "checkupauto-centre-map-osm.webp"
LATITUDE = 48.980120
LONGITUDE = 1.890251
ZOOM = 17
WIDTH = 1200
HEIGHT = 720
TILE_SIZE = 256
TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
USER_AGENT = "CheckupAuto-centre-map/1.0 (contact@checkupauto.fr)"
MAX_TILE_BYTES = 512_000


def world_pixel(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    latitude = max(min(latitude, 85.05112878), -85.05112878)
    scale = TILE_SIZE * (2**zoom)
    x = (longitude + 180.0) / 360.0 * scale
    sine = math.sin(math.radians(latitude))
    y = (0.5 - math.log((1 + sine) / (1 - sine)) / (4 * math.pi)) * scale
    return x, y


def fetch_tile(x: int, y: int) -> Image.Image:
    url = TILE_URL.format(zoom=ZOOM, x=x, y=y)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200 or response.headers.get_content_type() != "image/png":
            raise RuntimeError(f"unexpected OSM tile response: {response.status} {url}")
        raw = response.read(MAX_TILE_BYTES + 1)
    if len(raw) > MAX_TILE_BYTES:
        raise RuntimeError(f"OSM tile too large: {url}")
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    if image.size != (TILE_SIZE, TILE_SIZE):
        raise RuntimeError(f"unexpected OSM tile dimensions: {image.size} {url}")
    return image


def generate() -> Path:
    center_x, center_y = world_pixel(LATITUDE, LONGITUDE, ZOOM)
    left = int(round(center_x - WIDTH / 2))
    top = int(round(center_y - HEIGHT / 2))
    right = left + WIDTH
    bottom = top + HEIGHT

    min_tile_x = math.floor(left / TILE_SIZE)
    max_tile_x = math.floor((right - 1) / TILE_SIZE)
    min_tile_y = math.floor(top / TILE_SIZE)
    max_tile_y = math.floor((bottom - 1) / TILE_SIZE)

    sheet_width = (max_tile_x - min_tile_x + 1) * TILE_SIZE
    sheet_height = (max_tile_y - min_tile_y + 1) * TILE_SIZE
    sheet = Image.new("RGB", (sheet_width, sheet_height), "white")

    for tile_y in range(min_tile_y, max_tile_y + 1):
        for tile_x in range(min_tile_x, max_tile_x + 1):
            tile = fetch_tile(tile_x, tile_y)
            sheet.paste(
                tile,
                ((tile_x - min_tile_x) * TILE_SIZE, (tile_y - min_tile_y) * TILE_SIZE),
            )

    crop_left = left - min_tile_x * TILE_SIZE
    crop_top = top - min_tile_y * TILE_SIZE
    output = sheet.crop((crop_left, crop_top, crop_left + WIDTH, crop_top + HEIGHT))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.save(OUTPUT, "WEBP", quality=88, method=6)
    return OUTPUT


if __name__ == "__main__":
    try:
        path = generate()
    except Exception as exc:
        print(f"centre map generation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(path)
