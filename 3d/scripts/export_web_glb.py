from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
SOURCE_BLEND = ROOT / "3d" / "blend" / "CyberCheckVehicle_Photo3D.blend"
SAFE_COLLECTIONS = ("CYBERCHECK_PHOTO_3D", "CYBERCHECK_STAGE")
MAX_GLB_BYTES = 4 * 1024 * 1024
REFERENCE_TEXTURE = ROOT / "assets" / "vehicle.png"


def arguments() -> argparse.Namespace:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Export the CheckupAuto web vehicle GLB")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=MAX_GLB_BYTES)
    return parser.parse_args(script_args)


def selected_export_objects() -> list[bpy.types.Object]:
    selected: list[bpy.types.Object] = []
    seen: set[str] = set()
    for collection_name in SAFE_COLLECTIONS:
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            continue
        for obj in collection.all_objects:
            if obj.name == "SOURCE_REFERENCE_EDITING_ONLY" or obj.type in {"CAMERA", "LIGHT"}:
                continue
            if obj.name not in seen:
                selected.append(obj)
                seen.add(obj.name)
    if not selected:
        raise RuntimeError("web_export_selection_empty")
    vehicle = bpy.data.objects.get("VehiclePhoto3D")
    if vehicle is None or vehicle.type != "MESH" or vehicle not in selected:
        raise RuntimeError("web_export_vehicle_missing")
    return selected


def cutout_with_repository_alpha(image: bpy.types.Image) -> bpy.types.Image:
    """Return an RGBA image whose border-matched background is transparent."""
    width, height = image.size
    pixels = list(image.pixels[:])
    if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
        raise RuntimeError("vehicle_reference_texture_unreadable")
    alpha_values = pixels[3::4]
    if min(alpha_values) < 0.999:
        return image

    corner_offsets = (
        0,
        (width - 1) * 4,
        (height - 1) * width * 4,
        ((height * width) - 1) * 4,
    )
    background = tuple(
        sum(pixels[offset + channel] for offset in corner_offsets) / len(corner_offsets)
        for channel in range(3)
    )
    def distance(index: int) -> float:
        offset = index * 4
        return max(abs(pixels[offset + channel] - background[channel]) for channel in range(3))

    visited = bytearray(width * height)
    stack: list[int] = []

    def enqueue(index: int) -> None:
        if not visited[index] and distance(index) <= 0.18:
            visited[index] = 1
            stack.append(index)

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(height):
        enqueue(y * width)
        enqueue(y * width + width - 1)

    while stack:
        index = stack.pop()
        x, y = index % width, index // width
        if x:
            enqueue(index - 1)
        if x + 1 < width:
            enqueue(index + 1)
        if y:
            enqueue(index - width)
        if y + 1 < height:
            enqueue(index + width)

    for index, connected in enumerate(visited):
        pixels[index * 4 + 3] = (
            max(0.0, min(1.0, (distance(index) - 0.03) / 0.12))
            if connected else 1.0
        )

    derived = bpy.data.images.new(
        "vehicle_cutout_repository_alpha",
        width=width,
        height=height,
        alpha=True,
    )
    derived.file_format = "PNG"
    derived.pixels.foreach_set(pixels)
    derived.update()
    derived.pack()

    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image == image:
                node.image = derived
    if min(pixels[3::4]) >= 0.999:
        raise RuntimeError("vehicle_reference_alpha_not_generated")
    return derived


def bind_repository_images() -> None:
    """Resolve every external Blender image from tracked repository assets."""
    for image in bpy.data.images:
        if image.source != "FILE" or image.packed_file is not None:
            continue
        if Path(image.filepath).name == "vehicle_cutout.png":
            if not REFERENCE_TEXTURE.is_file():
                raise RuntimeError("vehicle_reference_texture_missing")
            image.filepath = str(REFERENCE_TEXTURE)
            image.reload()
            cutout_with_repository_alpha(image)
            continue
        current = Path(bpy.path.abspath(image.filepath)).resolve()
        if not current.is_file():
            raise RuntimeError(f"external_image_missing:{Path(image.filepath).name}")


def validate_glb(path: Path, max_bytes: int) -> dict:
    raw = path.read_bytes()
    if len(raw) < 12 or raw[:4] != b"glTF":
        raise RuntimeError("invalid_glb_magic")
    version, declared = struct.unpack("<II", raw[4:12])
    if version != 2:
        raise RuntimeError(f"invalid_glb_version:{version}")
    if declared != len(raw):
        raise RuntimeError(f"invalid_glb_length:{declared}:{len(raw)}")
    if len(raw) > max_bytes:
        raise RuntimeError(f"glb_too_large:{len(raw)}:{max_bytes}")
    return {"bytes": len(raw), "version": version}


def main() -> None:
    args = arguments()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if not SOURCE_BLEND.is_file():
        raise RuntimeError("source_blend_missing")

    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if current != SOURCE_BLEND.resolve():
        bpy.ops.wm.open_mainfile(filepath=str(SOURCE_BLEND))

    bind_repository_images()

    bpy.ops.object.select_all(action="DESELECT")
    export_objects = selected_export_objects()
    for obj in export_objects:
        obj.hide_set(False)
        obj.hide_render = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = export_objects[0]

    kwargs = {
        "filepath": str(output),
        "export_format": "GLB",
        "use_selection": True,
        "export_animations": True,
        "export_cameras": False,
        "export_lights": False,
        "export_yup": True,
    }
    bpy.ops.export_scene.gltf(**kwargs)
    result = validate_glb(output, max(1024, int(args.max_bytes)))
    print(
        "CHECKUPAUTO_GLB_OK",
        f"path={output}",
        f"bytes={result['bytes']}",
        f"objects={len(export_objects)}",
    )


if __name__ == "__main__":
    main()
