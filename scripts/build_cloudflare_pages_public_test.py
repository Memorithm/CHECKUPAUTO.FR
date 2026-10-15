"""Strict Pages pilot exports public marketing files, never application state."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parent / "build_cloudflare_pages_public.py"
spec = importlib.util.spec_from_file_location("pages_public_export", SOURCE)
assert spec and spec.loader
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class PagesAssetsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in export.ROOT_FILES:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"safe-public-asset")
        for d in export.PUBLIC_DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)

    def test_export_is_restricted_and_does_not_publish_credentials(self):
        (self.root / "admin").mkdir()
        (self.root / "admin" / "index.html").write_text("PRIVATE ADMIN")
        (self.root / "data").mkdir()
        (self.root / "data" / "site-config.json").write_text("RUNTIME SETTINGS")
        (self.root / "private").mkdir()
        (self.root / "private" / "oidc.json").write_text("CLIENT SECRET")
        image = self.root / "assets/illustrations" / "hero.webp"
        image.write_bytes(b"safe-image")
        (self.root / "assets/illustrations" / "internal.json").write_text("SECRET")
        out = self.root / ".cloudflare-pages-public"
        result = export.build(self.root, out)
        self.assertGreater(result["files"], 10)
        self.assertTrue((out / "assets/illustrations/hero.webp").is_file())
        for forbidden in ("admin/index.html", "data/site-config.json",
                          "private/oidc.json", "assets/illustrations/internal.json"):
            self.assertFalse((out / forbidden).exists())
        headers = (out / "_headers").read_text()
        self.assertIn("X-Robots-Tag: noindex", headers)
        self.assertTrue(headers.startswith("/*\n"))
        self.assertNotIn("Access-Control-Allow-Credentials", headers)
        manifest = json.loads((out / "public-assets-manifest.json").read_text())
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(len(manifest["assets"]), result["files"])
        self.assertNotIn("SECRET", (out / "public-assets-manifest.json").read_text())

    def test_refuses_unapproved_output_and_unknown_directory(self):
        with self.assertRaisesRegex(ValueError, "unapproved_pages_output"):
            export.build(self.root, self.root / "admin")
        self.assertFalse((self.root / "admin").exists())

    def test_symlinks_and_file_size_fail_closed(self):
        source = self.root / "private-secret"
        source.write_bytes(b"private")
        hidden = self.root / "assets/illustrations" / "image.png"
        hidden.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "public_asset_symlink"):
            export.selected_files(self.root)
        hidden.unlink()
        large = self.root / "assets/illustrations" / "large.webp"
        with large.open("wb") as handle:
            handle.truncate(export.MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "public_asset_size_invalid"):
            export.selected_files(self.root)

    def test_missing_expected_public_asset_aborts(self):
        (self.root / "app.js").unlink()
        with self.assertRaisesRegex(ValueError, "missing_public_asset"):
            export.build(self.root, self.root / ".cloudflare-pages-public")

    def test_real_repository_contains_no_exported_dynamic_or_admin_paths(self):
        selected = export.selected_files(export.ROOT)
        paths = {p.relative_to(export.ROOT).as_posix() for p in selected}
        self.assertIn("style.css", paths)
        self.assertIn("app.js", paths)
        self.assertIn("assets/3d/CyberCheckVehicle_Photo3D.glb", paths)
        self.assertFalse(any(p.startswith(("admin/", "data/", "private/", "scripts/")) for p in paths))
        self.assertFalse(any(p.endswith((".json", ".py", ".sqlite3", ".key", ".pem", ".blend")) for p in paths))


if __name__ == "__main__":
    unittest.main()
