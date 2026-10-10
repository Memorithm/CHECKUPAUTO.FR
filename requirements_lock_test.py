"""Le verrou haché reste aligné sur requirements.txt (audit D-01)."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _entries(text: str) -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;\\]+)", line)
        if match:
            current = match.group(1).lower().replace("_", "-")
            entries[current] = [match.group(2)]
        elif line.startswith("--hash=sha256:") and current:
            entries[current].append(line.split()[0])
    return entries


class RequirementsLockTest(unittest.TestCase):
    def setUp(self):
        self.direct = _entries((ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.lock = _entries((ROOT / "requirements.lock").read_text(encoding="utf-8"))

    def test_every_direct_pin_is_locked_at_the_same_version(self):
        self.assertTrue(self.direct)
        for name, (version, *_hashes) in self.direct.items():
            self.assertIn(name, self.lock, name)
            self.assertEqual(self.lock[name][0], version, name)

    def test_every_locked_package_carries_sha256_hashes(self):
        self.assertGreater(len(self.lock), len(self.direct))
        for name, (_version, *hashes) in self.lock.items():
            self.assertTrue(hashes, name)
            for value in hashes:
                self.assertRegex(value, r"^--hash=sha256:[0-9a-f]{64}$")

    def test_dockerfile_installs_the_lock_with_hash_checking(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt requirements.lock ./", text)
        self.assertIn("--require-hashes -r requirements.lock", text)
        self.assertNotIn("-r requirements.txt", text)

    def test_security_ci_installs_the_lock_with_hash_checking(self):
        text = (ROOT / ".github" / "workflows" / "security-ci.yml").read_text(encoding="utf-8")
        self.assertIn("--require-hashes -r requirements.lock", text)


if __name__ == "__main__":
    unittest.main()
