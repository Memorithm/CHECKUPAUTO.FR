from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

MAX_GLB_BYTES = 4 * 1024 * 1024


def inspect_glb(path: Path, max_bytes: int = MAX_GLB_BYTES) -> dict:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError("glb_size_budget_exceeded")
    raw = path.read_bytes()
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise ValueError("invalid_glb_magic")
    version, declared = struct.unpack("<II", raw[4:12])
    if version != 2:
        raise ValueError("invalid_glb_version")
    if declared != len(raw):
        raise ValueError("invalid_glb_length")
    chunk_length, chunk_type = struct.unpack("<II", raw[12:20])
    if chunk_type != 0x4E4F534A:
        raise ValueError("glb_json_chunk_missing")
    end = 20 + chunk_length
    if end > len(raw):
        raise ValueError("glb_json_chunk_truncated")
    try:
        document = json.loads(raw[20:end].decode("utf-8").rstrip(" \t\r\n\x00"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("glb_json_invalid") from exc

    asset = document.get("asset") if isinstance(document, dict) else {}
    if str((asset or {}).get("version") or "") != "2.0":
        raise ValueError("glb_asset_version_invalid")
    meshes = document.get("meshes") or []
    nodes = document.get("nodes") or []
    if not meshes or not nodes:
        raise ValueError("glb_scene_empty")

    materials = document.get("materials") or []
    vehicle_material = next(
        (item for item in materials if str(item.get("name") or "") == "VehiclePhotoMaterial"),
        None,
    )
    if vehicle_material is None:
        raise ValueError("glb_vehicle_material_missing")
    if vehicle_material.get("alphaMode") != "BLEND":
        raise ValueError("glb_vehicle_alpha_mode_invalid")
    if not (document.get("images") or []):
        raise ValueError("glb_vehicle_texture_missing")

    return {
        "bytes": len(raw),
        "version": version,
        "meshes": len(meshes),
        "nodes": len(nodes),
        "animations": len(document.get("animations") or []),
        "vehicleAlphaMode": vehicle_material.get("alphaMode"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-bytes", type=int, default=MAX_GLB_BYTES)
    args = parser.parse_args()
    result = inspect_glb(args.path, args.max_bytes)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
