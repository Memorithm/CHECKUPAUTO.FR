from __future__ import annotations

import argparse
import binascii
import struct
import sys
import tempfile
import zlib
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
SOURCE_BLEND = ROOT / "3d" / "blend" / "CyberCheckVehicle_Photo3D.blend"
SAFE_COLLECTIONS = ("CYBERCHECK_PHOTO_3D", "CYBERCHECK_STAGE")
MAX_GLB_BYTES = 4 * 1024 * 1024
MAX_REFERENCE_DIMENSION = 8192
MAX_REFERENCE_PIXELS = 16 * 1024 * 1024
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


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    return up if up_distance <= upper_left_distance else upper_left


def _decode_rgba_png(path: Path) -> tuple[int, int, bytearray]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("vehicle_reference_not_png")
    offset = 8
    width = height = 0
    compressed = bytearray()
    while offset < len(raw):
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        payload = raw[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", raw[offset + 8 + length:offset + 12 + length])[0]
        if binascii.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            raise RuntimeError("vehicle_reference_png_crc")
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise RuntimeError("vehicle_reference_png_format")
            if (
                width == 0
                or height == 0
                or width > MAX_REFERENCE_DIMENSION
                or height > MAX_REFERENCE_DIMENSION
                or width * height > MAX_REFERENCE_PIXELS
            ):
                raise RuntimeError("vehicle_reference_png_dimensions")
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    stride = width * 4
    expected_length = height * (stride + 1)
    decompressor = zlib.decompressobj()
    encoded = decompressor.decompress(bytes(compressed), expected_length + 1)
    if (
        len(encoded) != expected_length
        or decompressor.unconsumed_tail
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise RuntimeError("vehicle_reference_png_length")
    pixels = bytearray()
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_kind = encoded[cursor]
        cursor += 1
        scanline = bytearray(encoded[cursor:cursor + stride])
        cursor += stride
        for index in range(stride):
            left = scanline[index - 4] if index >= 4 else 0
            up = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_kind == 1:
                scanline[index] = (scanline[index] + left) & 0xFF
            elif filter_kind == 2:
                scanline[index] = (scanline[index] + up) & 0xFF
            elif filter_kind == 3:
                scanline[index] = (scanline[index] + ((left + up) // 2)) & 0xFF
            elif filter_kind == 4:
                scanline[index] = (scanline[index] + _paeth(left, up, upper_left)) & 0xFF
            elif filter_kind != 0:
                raise RuntimeError("vehicle_reference_png_filter")
        pixels.extend(scanline)
        previous = scanline
    return width, height, pixels


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def repository_cutout_path(source: Path) -> Path:
    width, height, pixels = _decode_rgba_png(source)
    if min(pixels[3::4]) < 255:
        return source

    corners = (0, width - 1, (height - 1) * width, width * height - 1)
    background = tuple(
        sum(pixels[index * 4 + channel] for index in corners) // len(corners)
        for channel in range(3)
    )

    def distance(index: int) -> int:
        offset = index * 4
        return max(abs(pixels[offset + channel] - background[channel]) for channel in range(3))

    visited = bytearray(width * height)
    stack: list[int] = []

    def enqueue(index: int) -> None:
        if not visited[index] and distance(index) <= 46:
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
        if connected:
            pixels[index * 4 + 3] = max(0, min(255, (distance(index) - 8) * 255 // 31))
        else:
            pixels[index * 4 + 3] = 255
    if min(pixels[3::4]) == 255:
        raise RuntimeError("vehicle_reference_alpha_not_generated")

    scanlines = b"".join(
        b"\x00" + bytes(pixels[y * width * 4:(y + 1) * width * 4])
        for y in range(height)
    )
    destination = Path(tempfile.mkdtemp(prefix="checkupauto-glb-")) / "vehicle_cutout.png"
    destination.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _png_chunk(b"IEND", b"")
    )
    return destination


def bind_repository_images() -> None:
    """Resolve every external Blender image from tracked repository assets."""
    for image in bpy.data.images:
        if image.source != "FILE" or image.packed_file is not None:
            continue
        if Path(image.filepath).name == "vehicle_cutout.png":
            if not REFERENCE_TEXTURE.is_file():
                raise RuntimeError("vehicle_reference_texture_missing")
            image.filepath = str(repository_cutout_path(REFERENCE_TEXTURE))
            image.reload()
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
