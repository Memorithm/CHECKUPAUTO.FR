import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import site_config_store


class SiteConfigStoreTest(unittest.TestCase):
    def test_load_falls_back_to_tracked_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default.json"
            runtime = root / "runtime.json"
            default.write_text(json.dumps({"source": "default"}))
            self.assertEqual(
                site_config_store.load(runtime_path=runtime, default_path=default),
                {"source": "default"},
            )

    def test_runtime_override_has_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default.json"
            runtime = root / "runtime.json"
            default.write_text(json.dumps({"source": "default"}))
            runtime.write_text(json.dumps({"source": "runtime"}))
            self.assertEqual(
                site_config_store.load(runtime_path=runtime, default_path=default),
                {"source": "runtime"},
            )

    def test_save_is_runtime_only_and_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "data" / "site-config.json"
            result = site_config_store.save({"version": 9}, runtime_path=target)
            self.assertEqual(result, target)
            self.assertEqual(json.loads(target.read_text()), {"version": 9})
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(target.parent.glob("site-config.*.json")), [])

    def test_save_accepts_exact_mercureweb_delegation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"site-config.json"
            config={
                "seo":{"canonicalUrl":"https://www.checkupauto.fr/"},
                "business":{
                    "bookingMode":"mercureweb-delegated",
                    "bookingUrl":"https://rdv.checkupauto.fr/",
                },
            }
            site_config_store.save(config,runtime_path=target)
            self.assertEqual(site_config_store.load(runtime_path=target)["business"]["bookingMode"],"mercureweb-delegated")

    def test_save_rejects_foreign_or_insecure_delegated_booking_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"site-config.json"
            for url in (
                "http://rdv.checkupauto.fr/",
                "https://example.com/",
                "https://rdv.checkupauto.fr.evil.test/",
                "https://user@rdv.checkupauto.fr/",
                "https://rdv.checkupauto.fr/?x=1",
            ):
                with self.subTest(url=url):
                    config={
                        "seo":{"canonicalUrl":"https://www.checkupauto.fr/"},
                        "business":{"bookingMode":"mercureweb-delegated","bookingUrl":url},
                    }
                    with self.assertRaisesRegex(ValueError,"MercureWeb"):
                        site_config_store.save(config,runtime_path=target)

    def test_save_accepts_production_canonical_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "site-config.json"
            config = {"seo": {"canonicalUrl": "https://www.checkupauto.fr/"}}
            site_config_store.save(config, runtime_path=target)
            self.assertEqual(json.loads(target.read_text()), config)

    def test_save_rejects_foreign_or_insecure_canonical_origin(self):
        invalid = (
            "http://www.checkupauto.fr/",
            "https://example.invalid/",
            "https://www.checkupauto.fr.evil.invalid/",
            "https://user@www.checkupauto.fr/",
            "https://www.checkupauto.fr:444/",
            "https://www.checkupauto.fr/other",
            "https://www.checkupauto.fr/?redirect=1",
            "https://www.checkupauto.fr/#fragment",
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "site-config.json"
            for value in invalid:
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        site_config_store.save(
                            {"seo": {"canonicalUrl": value}},
                            runtime_path=target,
                        )
            self.assertFalse(target.exists())

    def test_environment_can_relocate_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "custom.json"
            with mock.patch.dict(os.environ, {"CYBERCHECK_SITE_CONFIG_PATH": str(target)}):
                self.assertEqual(site_config_store.runtime_config_path(), target)


if __name__ == "__main__":
    unittest.main()
