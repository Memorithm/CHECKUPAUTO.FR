import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


ROOT=Path(__file__).resolve().parent
SCRIPT=ROOT/"scripts/checkupauto-migration-state.py"


def load_module():
    spec=importlib.util.spec_from_file_location("checkupauto_migration_state",SCRIPT)
    module=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def create_sqlite(path: Path,value: str) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE state(value TEXT NOT NULL)")
        con.execute("INSERT INTO state(value) VALUES(?)",(value,))
        con.commit()
    finally:
        con.close()


def read_value(path: Path) -> str:
    con=sqlite3.connect(path)
    try:
        return con.execute("SELECT value FROM state").fetchone()[0]
    finally:
        con.close()


class MigrationStateSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.mod=load_module()
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.shared=self.root/"shared"
        for group in self.mod.GROUPS:
            (self.shared/group).mkdir(parents=True,mode=0o700)
        (self.shared/"data"/".migration-write-freeze.json").write_text(json.dumps({
            "schemaVersion":1,
            "state":"frozen",
            "createdAt":"2026-10-06T04:00:00+00:00",
            "reason":"hostinger_cutover",
        }),encoding="utf-8")
        create_sqlite(self.shared/"data"/"customer-accounts.sqlite3","source")
        create_sqlite(self.shared/"security"/"events.sqlite3","security")
        (self.shared/"data"/"site-config.json").write_text('{"version":5}\n',encoding="utf-8")
        customer=self.shared/"private"/"customer"
        customer.mkdir()
        (customer/"accounts.key").write_bytes(b"customer-key")
        (self.shared/"private"/"gsc-service-account.json").write_text('{"client_email":"x@example.test"}\n',encoding="utf-8")

    def export(self) -> Path:
        snapshot=self.root/"snapshot"
        result=self.mod.export_snapshot(self.shared,snapshot)
        self.assertTrue(result["ok"])
        return snapshot

    def test_export_uses_consistent_sqlite_copies_and_manifest(self):
        snapshot=self.export()
        result=self.mod.verify_snapshot(snapshot)
        self.assertGreaterEqual(result["sqliteCount"],2)
        self.assertEqual(read_value(snapshot/"data"/"customer-accounts.sqlite3"),"source")
        manifest=json.loads((snapshot/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["purpose"],self.mod.PURPOSE)
        self.assertEqual(manifest["sourceFreezeCreatedAt"],"2026-10-06T04:00:00+00:00")
        self.assertNotIn(str(self.shared),json.dumps(manifest))
        for path in snapshot.rglob("*"):
            if path.is_file():
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
            elif path.is_dir():
                self.assertEqual(path.stat().st_mode & 0o777,0o700)

    def test_export_refuses_state_without_active_freeze(self):
        (self.shared/"data"/".migration-write-freeze.json").unlink()
        with self.assertRaisesRegex(RuntimeError,"freeze marker"):
            self.mod.export_snapshot(self.shared,self.root/"snapshot")

    def test_export_refuses_symlinks(self):
        target=self.shared/"private"/"customer"/"accounts.key"
        link=self.shared/"private"/"customer"/"alias.key"
        link.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError,"symlink"):
            self.mod.export_snapshot(self.shared,self.root/"snapshot")

    def test_verify_detects_tampering_and_unmanifested_files(self):
        snapshot=self.export()
        (snapshot/"data"/"site-config.json").write_text("tampered",encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"digest"):
            self.mod.verify_snapshot(snapshot)

        snapshot2=self.root/"snapshot2"
        self.mod.export_snapshot(self.shared,snapshot2)
        (snapshot2/"private"/"extra.secret").write_text("x",encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"unmanifested"):
            self.mod.verify_snapshot(snapshot2)

    def test_import_atomically_replaces_state_and_preserves_previous(self):
        snapshot=self.export()
        target=self.root/"target"
        target.mkdir()
        for group in self.mod.GROUPS:
            (target/group).mkdir()
        (target/"data"/"old.txt").write_text("old",encoding="utf-8")
        (target/"private"/"old.secret").write_text("old",encoding="utf-8")
        integrity=target/"integrity"
        integrity.mkdir()
        (integrity/"baseline.json").write_text("keep",encoding="utf-8")

        result=self.mod.import_snapshot(snapshot,target)
        self.assertEqual(result["state"],"imported_frozen")
        self.assertEqual(read_value(target/"data"/"customer-accounts.sqlite3"),"source")
        self.assertEqual((target/"private"/"customer"/"accounts.key").read_bytes(),b"customer-key")
        self.assertFalse((target/"private"/"gsc-service-account.json").exists())
        self.assertTrue((target/"private"/"integrations"/"gsc-service-account.json").is_file())
        self.assertEqual((target/"integrity"/"baseline.json").read_text(encoding="utf-8"),"keep")
        self.assertTrue((target/"data"/".migration-write-freeze.json").is_file())

        previous=target/result["previousState"]
        self.assertEqual((previous/"data"/"old.txt").read_text(encoding="utf-8"),"old")
        self.assertEqual((previous/"private"/"old.secret").read_text(encoding="utf-8"),"old")

    def test_export_aborts_if_source_is_unfrozen_during_copy(self):
        snapshot=self.root/"snapshot"
        real_copy=self.mod._copy_file
        changed={"done":False}

        def copy_then_unfreeze(source,destination):
            result=real_copy(source,destination)
            if not changed["done"]:
                changed["done"]=True
                (self.shared/"data"/".migration-write-freeze.json").unlink()
            return result

        with mock.patch.object(self.mod,"_copy_file",side_effect=copy_then_unfreeze):
            with self.assertRaisesRegex(RuntimeError,"freeze marker"):
                self.mod.export_snapshot(self.shared,snapshot)
        self.assertFalse(snapshot.exists())

    def test_import_rolls_back_all_groups_if_swap_fails_midway(self):
        (self.shared/"private"/"gsc-service-account.json").unlink()
        snapshot=self.export()
        target=self.root/"target"
        target.mkdir()
        for group in self.mod.GROUPS:
            (target/group).mkdir()
        (target/"data"/"old.txt").write_text("old-data",encoding="utf-8")
        (target/"private"/"old.secret").write_text("old-private",encoding="utf-8")
        (target/"security"/"old.log").write_text("old-security",encoding="utf-8")

        real_replace=self.mod.os.replace

        def fail_private_swap(source,destination):
            src=Path(source)
            dst=Path(destination)
            if (
                src.name=="private"
                and src.parent.name.startswith(".migration-incoming-")
                and dst==target/"private"
            ):
                raise OSError("injected swap failure")
            return real_replace(source,destination)

        with mock.patch.object(self.mod.os,"replace",side_effect=fail_private_swap):
            with self.assertRaisesRegex(OSError,"injected swap failure"):
                self.mod.import_snapshot(snapshot,target)

        self.assertEqual((target/"data"/"old.txt").read_text(encoding="utf-8"),"old-data")
        self.assertEqual((target/"private"/"old.secret").read_text(encoding="utf-8"),"old-private")
        self.assertEqual((target/"security"/"old.log").read_text(encoding="utf-8"),"old-security")
        self.assertFalse((target/"data"/"customer-accounts.sqlite3").exists())

    def test_gsc_migration_refuses_conflicting_dual_credentials(self):
        integrations=self.shared/"private"/"integrations"
        integrations.mkdir()
        (integrations/"gsc-service-account.json").write_text('{"different":true}\n',encoding="utf-8")
        snapshot=self.export()
        target=self.root/"target"
        target.mkdir()
        for group in self.mod.GROUPS:
            (target/group).mkdir()
        with self.assertRaisesRegex(RuntimeError,"credential migration conflict"):
            self.mod.import_snapshot(snapshot,target)
        self.assertTrue((target/"data").is_dir())
        self.assertFalse((target/"data"/"customer-accounts.sqlite3").exists())


if __name__=="__main__":
    unittest.main()
