import json
import struct
import tempfile
import unittest
from pathlib import Path

import glb_contract


class GLBContractTest(unittest.TestCase):
    def build_glb(self, document: dict, payload: bytes = b"") -> bytes:
        json_raw = json.dumps(document, separators=(",", ":")).encode()
        json_raw += b" " * ((4 - len(json_raw) % 4) % 4)
        chunks = struct.pack("<II", len(json_raw), 0x4E4F534A) + json_raw
        if payload:
            payload += b"\x00" * ((4 - len(payload) % 4) % 4)
            chunks += struct.pack("<II", len(payload), 0x004E4942) + payload
        return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks

    def test_accepts_bounded_nonempty_glb2(self):
        document = {
            "asset": {"version": "2.0"},
            "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": []}],
            "animations": [{"channels": [], "samplers": []}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vehicle.glb"
            path.write_bytes(self.build_glb(document))
            result = glb_contract.inspect_glb(path)
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["meshes"], 1)
        self.assertEqual(result["nodes"], 1)
        self.assertEqual(result["animations"], 1)

    def test_rejects_empty_or_oversized_asset(self):
        empty = {"asset": {"version": "2.0"}, "nodes": [], "meshes": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.glb"
            path.write_bytes(self.build_glb(empty))
            with self.assertRaisesRegex(ValueError, "scene_empty"):
                glb_contract.inspect_glb(path)
            path.write_bytes(self.build_glb({
                "asset": {"version": "2.0"},
                "nodes": [{"mesh": 0}],
                "meshes": [{"primitives": []}],
            }, b"x" * 200))
            with self.assertRaisesRegex(ValueError, "size_budget"):
                glb_contract.inspect_glb(path, max_bytes=64)


if __name__ == "__main__":
    unittest.main()
