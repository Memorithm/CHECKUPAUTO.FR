from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "admin_server.py"


class GLBStaticContractTest(unittest.TestCase):
    def test_server_declares_gltf_binary_mime(self):
        text = SERVER.read_text(encoding="utf-8")
        self.assertIn("'.glb':'model/gltf-binary'", text)

    def test_versioned_3d_assets_receive_immutable_cache(self):
        text = SERVER.read_text(encoding="utf-8")
        self.assertIn("response_path.startswith('/assets/3d/')", text)
        self.assertIn("response_path.endswith('.glb')", text)
        self.assertIn("public, max-age=31536000, immutable", text)


if __name__ == "__main__":
    unittest.main()
