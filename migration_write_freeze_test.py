import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import migration_write_freeze as freeze


class MigrationWriteFreezeTest(unittest.TestCase):
    def test_absent_marker_keeps_writes_enabled(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            self.assertFalse(freeze.active())
            self.assertEqual(freeze.status()["state"], "inactive")

    def test_valid_marker_freezes_writes(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            path=Path(tmp)/freeze.MARKER_NAME
            path.write_text(json.dumps({
                "schemaVersion":1,
                "state":"frozen",
                "createdAt":"2026-10-05T16:00:00+00:00",
                "reason":"hostinger_cutover",
            }))
            state=freeze.status()
            self.assertTrue(state["active"])
            self.assertTrue(state["valid"])
            self.assertEqual(state["state"],"frozen")
            self.assertEqual(state["reason"],"hostinger_cutover")

    def test_malformed_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            path=Path(tmp)/freeze.MARKER_NAME
            path.write_text("{bad")
            state=freeze.status()
            self.assertTrue(state["active"])
            self.assertFalse(state["valid"])
            self.assertEqual(state["state"],"invalid_marker")

    def test_request_policy_blocks_transactional_gets(self):
        for path in (
            "/go/booking",
            "/go/app",
            "/compte",
            "/contact",
            "/auth/customer/google/callback",
            "/api/integrations/google/oauth/callback",
            "/payment/payline/callback",
        ):
            with self.subTest(path=path):
                self.assertFalse(freeze.request_allowed("GET",path))

    def test_request_policy_keeps_bounded_read_only_surface(self):
        for method,path in (
            ("GET","/"),
            ("HEAD","/cgv"),
            ("GET","/assets/cybercheck-deployment-provenance.bin"),
            ("GET","/style.css"),
            ("OPTIONS","/contact"),
        ):
            with self.subTest(method=method,path=path):
                self.assertTrue(freeze.request_allowed(method,path))
        self.assertFalse(freeze.request_allowed("POST","/"))
        self.assertFalse(freeze.request_allowed("GET","/api/admin/readiness"))

    def test_engage_is_atomic_private_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            first=freeze.engage(
                "hostinger_cutover",
                now=dt.datetime(2026,10,6,4,30,tzinfo=dt.timezone.utc),
            )
            path=Path(tmp)/freeze.MARKER_NAME
            self.assertTrue(first["active"])
            self.assertTrue(first["valid"])
            self.assertEqual(first["createdAt"],"2026-10-06T04:30:00+00:00")
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

            second=freeze.engage(
                "different_reason",
                now=dt.datetime(2026,10,6,5,0,tzinfo=dt.timezone.utc),
            )
            self.assertEqual(second["createdAt"],first["createdAt"])
            self.assertEqual(second["reason"],"hostinger_cutover")

    def test_release_requires_explicit_confirmation_and_valid_marker(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            freeze.engage("hostinger_cutover")
            with self.assertRaises(PermissionError):
                freeze.release("yes")
            self.assertTrue(freeze.active())

            result=freeze.release("UNFREEZE")
            self.assertFalse(result["active"])
            self.assertFalse((Path(tmp)/freeze.MARKER_NAME).exists())

    def test_engage_refuses_to_overwrite_invalid_marker(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            path=Path(tmp)/freeze.MARKER_NAME
            path.write_text("{bad",encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"invalid migration marker"):
                freeze.engage("hostinger_cutover")
            self.assertEqual(path.read_text(encoding="utf-8"),"{bad")

    def test_release_refuses_invalid_marker_even_with_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            path=Path(tmp)/freeze.MARKER_NAME
            path.write_text("{bad",encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"cannot be removed automatically"):
                freeze.release("UNFREEZE")
            self.assertTrue(path.exists())

    def test_engage_requires_real_private_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            real=root/"real"
            real.mkdir()
            link=root/"link"
            link.symlink_to(real,target_is_directory=True)
            with mock.patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":str(link)}):
                with self.assertRaisesRegex(RuntimeError,"data directory invalid"):
                    freeze.engage("hostinger_cutover")

    def test_shared_tick_checks_freeze_before_runtime_initialization(self):
        script=(Path(__file__).parent/"scripts/checkupauto-shared-tick.py").read_text()
        freeze_check=script.index("freeze=migration_write_freeze.status()")
        runtime_init=script.index("admin_server.initialize_runtime(background=False)")
        self.assertLess(freeze_check,runtime_init)
        self.assertIn('"state":"write_frozen"',script)
        self.assertIn('"tasks":[]',script)

    def test_symlink_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"CYBERCHECK_DATA_DIR": tmp}
        ):
            root=Path(tmp)
            target=root/"target.json"
            target.write_text("{}")
            (root/freeze.MARKER_NAME).symlink_to(target)
            state=freeze.status()
            self.assertTrue(state["active"])
            self.assertFalse(state["valid"])
            self.assertEqual(state["reason"],"symlink")


if __name__=="__main__":
    unittest.main()
