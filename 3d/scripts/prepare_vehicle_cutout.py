from __future__ import annotations

import argparse
import binascii
import struct
import zlib
from pathlib import Path

MAX_REFERENCE_PNG_BYTES = 32 * 1024 * 1024
MAX_REFERENCE_DIMENSION = 8192
MAX_REFERENCE_PIXELS = 16 * 1024 * 1024


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    return up if up_distance <= upper_left_distance else upper_left


def _decode_rgba_png(path: Path) -> tuple[int, int, bytearray]:
    if path.stat().st_size > MAX_REFERENCE_PNG_BYTES:
        raise RuntimeError("vehicle_reference_png_oversized")
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


def write_cutout(source: Path, destination: Path) -> None:
    width, height, pixels = _decode_rgba_png(source)
    if min(pixels[3::4]) < 255:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return

    corners = (0, width - 1, (height - 1) * width, width * height - 1)
    background = tuple(
        sum(pixels[index * 4 + channel] for index in corners) // len(corners)
        for channel in range(3)
    )

    def distance(index: int) -> int:
        offset = index * 4
        return max(abs(pixels[offset + channel] - background[channel]) for channel in range(3))

    background_distance = 46
    transparent_distance = 8
    visited = bytearray(width * height)
    stack: list[int] = []

    def enqueue(index: int) -> None:
        if not visited[index] and distance(index) <= background_distance:
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
        offset = index * 4
        if connected:
            alpha = max(
                0,
                min(
                    254,
                    (distance(index) - transparent_distance)
                    * 255
                    // (background_distance - transparent_distance + 1),
                ),
            )
            for channel in range(3):
                if alpha == 0:
                    pixels[offset + channel] = 0
                else:
                    straight = (
                        pixels[offset + channel] * 255
                        - background[channel] * (255 - alpha)
                    )
                    pixels[offset + channel] = max(
                        0, min(255, (straight + alpha // 2) // alpha)
                    )
            pixels[offset + 3] = alpha
        else:
            pixels[offset + 3] = 255
    if min(pixels[3::4]) == 255:
        raise RuntimeError("vehicle_reference_alpha_not_generated")

    scanlines = b"".join(
        b"\x00" + bytes(pixels[y * width * 4:(y + 1) * width * 4])
        for y in range(height)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _png_chunk(b"IEND", b"")
    )



def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the tracked vehicle cutout outside Blender")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_cutout(args.source.expanduser().resolve(), args.output.expanduser().resolve())
    print(f"CHECKUPAUTO_CUTOUT_OK path={args.output.expanduser().resolve()}")


if __name__ == "__main__":
    main()
