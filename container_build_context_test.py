"""O-03 / O-04: image pinned by digest, secrets excluded from the build context, systemd ceilings."""
import configparser
import fnmatch
import re
import unittest
from pathlib import Path

import security_integrity as integrity

ROOT = Path(__file__).resolve().parent


def _patterns():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [line.strip().rstrip("/") for line in lines if line.strip() and not line.startswith("#")]


def _ignored(rel):
    parts = rel.split("/")
    for pattern in _patterns():
        for i in range(len(parts)):
            if fnmatch.fnmatch("/".join(parts[: i + 1]), pattern) or fnmatch.fnmatch(parts[i], pattern):
                return True
    return False


class ContainerBuildContextTest(unittest.TestCase):
    def test_base_image_is_pinned_by_digest(self):
        line = next(l for l in (ROOT / "Dockerfile").read_text().splitlines() if l.startswith("FROM "))
        self.assertRegex(line, r"@sha256:[0-9a-f]{64}$")

    def test_secret_material_is_excluded_from_context(self):
        for rel in (".admin-password", "private/admin.key", "deploy/tls.pem", "AuthKey_ABC.p8", "cert.p12",
                    ".env.production", "CyberCheckPrivate/x", ".ci-venv/bin/python", "node_modules/x/index.js"):
            with self.subTest(rel=rel):
                self.assertTrue(_ignored(rel))

    def test_runtime_critical_files_stay_in_context(self):
        for rel in integrity.CRITICAL_FILES:
            with self.subTest(rel=rel):
                self.assertFalse(_ignored(rel))

    def test_systemd_unit_has_resource_ceilings(self):
        unit = configparser.ConfigParser(strict=False, interpolation=None)
        unit.optionxform = str
        unit.read(ROOT / "deploy" / "cybercheck.service")
        service = unit["Service"]
        self.assertRegex(service.get("MemoryMax", ""), r"^\d+[MG]$")
        self.assertTrue(service.get("TasksMax", "").isdigit())
        self.assertEqual(service.get("SystemCallFilter"), "@system-service")


if __name__ == "__main__":
    unittest.main()
