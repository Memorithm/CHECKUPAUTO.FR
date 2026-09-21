from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "checkupauto-update-safety.py"
SPEC = importlib.util.spec_from_file_location("checkupauto_update_safety", SCRIPT)
assert SPEC and SPEC.loader
safety = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(safety)

SHA1 = "1" * 40
SHA2 = "2" * 40
SHA3 = "3" * 40
SHA4 = "4" * 40
SHA5 = "5" * 40
SHA6 = "6" * 40


class DeploymentUpdateSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".checkupauto"
        for path in (
            self.root / "releases",
            self.root / "shared" / "data",
            self.root / "shared" / "security",
            self.root / "shared" / "private",
            self.root / "shared" / "integrity",
            self.root / "shared" / "logs",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def sqlite(self, path: Path, value: str):
        db = sqlite3.connect(path)
        try:
            db.execute("CREATE TABLE sample(value TEXT NOT NULL)")
            db.execute("INSERT INTO sample(value) VALUES(?)", (value,))
            db.commit()
        finally:
            db.close()

    def release(self, sha: str, mtime: int):
        path = self.root / "releases" / sha
        path.mkdir()
        (path / ".checkupauto-release.json").write_text(
            json.dumps({
                "schemaVersion": 1,
                "sha": sha,
                "archiveSha256": "a" * 64,
                "verified": True,
            }) + "\n",
            encoding="utf-8",
        )
        os.utime(path, (mtime, mtime))
        return path

    def test_backup_snapshots_sqlite_and_site_config(self):
        data_db = self.root / "shared" / "data" / "reminders.sqlite3"
        sec_db = self.root / "shared" / "security" / "security.db"
        self.sqlite(data_db, "alpha")
        self.sqlite(sec_db, "beta")
        config = self.root / "shared" / "data" / "site-config.json"
        config.write_text('{"version":5}\n', encoding="utf-8")

        result = safety.backup_shared_state(
            self.root,
            SHA1,
            SHA2,
            now=dt.datetime(2026, 9, 21, 18, 0, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["databaseCount"], 2)
        self.assertEqual(result["fileCount"], 1)

        snapshot = self.root / "shared" / "backups" / result["snapshot"]
        manifest = json.loads((snapshot / "manifest.json").read_text())
        self.assertEqual(manifest["fromSha"], SHA1)
        self.assertEqual(manifest["toSha"], SHA2)
        self.assertEqual(len(manifest["databases"]), 2)

        backup_db = snapshot / "data" / "reminders.sqlite3"
        db = sqlite3.connect(backup_db)
        try:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], "alpha")
        finally:
            db.close()
        self.assertEqual(backup_db.stat().st_mode & 0o777, 0o600)

    def test_failed_backup_removes_partial_snapshot(self):
        source = self.root / "shared" / "data" / "broken.sqlite3"
        source.write_bytes(b"SQLite format 3\x00" + b"broken")
        with self.assertRaises(Exception):
            safety.backup_shared_state(
                self.root,
                SHA1,
                SHA2,
                now=dt.datetime(2026, 9, 21, 18, 0, tzinfo=dt.timezone.utc),
            )
        backup_root = self.root / "shared" / "backups"
        self.assertTrue(backup_root.is_dir())
        self.assertEqual(list(backup_root.iterdir()), [])

    def test_cleanup_keeps_current_previous_and_newest_verified(self):
        now = int(time.time())
        paths = [
            self.release(SHA1, now - 600),
            self.release(SHA2, now - 500),
            self.release(SHA3, now - 400),
            self.release(SHA4, now - 300),
            self.release(SHA5, now - 200),
            self.release(SHA6, now - 100),
        ]
        result = safety.cleanup_after_activation(
            self.root,
            SHA6,
            SHA2,
            release_keep=4,
            backup_keep=12,
            now_ts=now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["prunedReleaseCount"], 2)
        remaining = {
            p.name for p in (self.root / "releases").iterdir()
            if p.is_dir() and not p.name.startswith(".")
        }
        self.assertEqual(remaining, {SHA2, SHA4, SHA5, SHA6})

    def test_cleanup_never_deletes_unverified_release_directory(self):
        now = int(time.time())
        self.release(SHA1, now - 500)
        self.release(SHA2, now - 400)
        self.release(SHA3, now - 300)
        weird = self.root / "releases" / SHA4
        weird.mkdir()
        (weird / "manual.txt").write_text("keep", encoding="utf-8")

        safety.cleanup_after_activation(
            self.root,
            SHA3,
            SHA2,
            release_keep=2,
            backup_keep=12,
            now_ts=now,
        )
        self.assertTrue(weird.is_dir())
        self.assertTrue((weird / "manual.txt").is_file())

    def test_cleanup_prunes_stale_incoming_only_after_24_hours(self):
        now = int(time.time())
        self.release(SHA1, now - 100)
        old = self.root / "releases" / f".incoming-{SHA2}-111"
        fresh = self.root / "releases" / f".incoming-{SHA3}-222"
        old.mkdir()
        fresh.mkdir()
        os.utime(old, (now - safety.STALE_INCOMING_SECONDS - 10, now - safety.STALE_INCOMING_SECONDS - 10))
        os.utime(fresh, (now - 60, now - 60))

        result = safety.cleanup_after_activation(
            self.root,
            SHA1,
            "none",
            release_keep=2,
            backup_keep=12,
            now_ts=now,
        )
        self.assertEqual(result["prunedIncomingCount"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_cleanup_prunes_oldest_verified_backups(self):
        now = int(time.time())
        self.release(SHA1, now)
        backup_root = self.root / "shared" / "backups"
        backup_root.mkdir()
        for index in range(4):
            path = backup_root / f"2026092{index}T000000Z-{SHA1[:12]}-to-{SHA2[:12]}"
            path.mkdir()
            (path / "manifest.json").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "createdAt": f"2026-09-2{index}T00:00:00+00:00",
                }),
                encoding="utf-8",
            )
            os.utime(path, (100 + index, 100 + index))

        result = safety.cleanup_after_activation(
            self.root,
            SHA1,
            "none",
            release_keep=2,
            backup_keep=2,
            now_ts=now,
        )
        self.assertEqual(result["prunedBackupCount"], 2)
        self.assertEqual(len(list(backup_root.iterdir())), 2)

    def test_invalid_retention_is_rejected(self):
        self.release(SHA1, int(time.time()))
        with self.assertRaises(ValueError):
            safety.cleanup_after_activation(
                self.root,
                SHA1,
                "none",
                release_keep=1,
            )
        with self.assertRaises(ValueError):
            safety.cleanup_after_activation(
                self.root,
                SHA1,
                "none",
                backup_keep=0,
            )


if __name__ == "__main__":
    unittest.main()
