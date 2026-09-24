import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import provider_erasure_plan as plan


class ProviderErasurePlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.private = Path(self.tmp.name) / "private"
        self.env = mock.patch.dict(
            os.environ,
            {"CYBERCHECK_PRIVATE_DIR": str(self.private)},
        )
        self.env.start()
        self.request_id = "a" * 32
        self.subject_ref = "account:42"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_plan_is_encrypted_at_rest_and_round_trips(self):
        stored = plan.stage(
            self.request_id,
            self.subject_ref,
            ["apt-2", "apt-1"],
        )
        self.assertEqual(stored["appointmentIds"], ("apt-1", "apt-2"))
        raw = plan._plan_path(self.request_id).read_bytes()
        self.assertNotIn(b"apt-1", raw)
        self.assertNotIn(b"apt-2", raw)
        self.assertNotIn(self.subject_ref.encode(), raw)

        loaded = plan.load(self.request_id, self.subject_ref)
        self.assertEqual(loaded["appointmentIds"], ("apt-1", "apt-2"))
        self.assertEqual(
            loaded["appointmentSetHash"],
            stored["appointmentSetHash"],
        )

    def test_first_committed_plan_wins_across_provider_drift(self):
        first = plan.stage(
            self.request_id,
            self.subject_ref,
            ["apt-first"],
        )
        second = plan.stage(
            self.request_id,
            self.subject_ref,
            ["apt-first", "apt-late"],
        )
        self.assertEqual(second["appointmentIds"], ("apt-first",))
        self.assertEqual(
            second["appointmentSetHash"],
            first["appointmentSetHash"],
        )

    def test_plan_permissions_are_private(self):
        plan.stage(self.request_id, self.subject_ref, ["apt-1"])
        root = plan._root()
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(plan._key_path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            plan._plan_path(self.request_id).stat().st_mode & 0o777,
            0o600,
        )

    def test_wrong_subject_cannot_load_plan(self):
        plan.stage(self.request_id, self.subject_ref, ["apt-1"])
        with self.assertRaisesRegex(PermissionError, "autre sujet"):
            plan.load(self.request_id, "account:43")

    def test_clear_requires_exact_inventory_hash(self):
        stored = plan.stage(self.request_id, self.subject_ref, ["apt-1"])
        with self.assertRaisesRegex(RuntimeError, "empreinte"):
            plan.clear(
                self.request_id,
                self.subject_ref,
                "b" * 64,
            )
        self.assertTrue(plan._plan_path(self.request_id).exists())
        self.assertTrue(
            plan.clear(
                self.request_id,
                self.subject_ref,
                stored["appointmentSetHash"],
            )
        )
        self.assertIsNone(plan.load(self.request_id, self.subject_ref))

    def test_corrupted_ciphertext_fails_closed(self):
        plan.stage(self.request_id, self.subject_ref, ["apt-1"])
        path = plan._plan_path(self.request_id)
        path.write_text('{"schemaVersion":1,"nonce":"AA==","ciphertext":"AA=="}\n')
        with self.assertRaisesRegex(RuntimeError, "illisible"):
            plan.load(self.request_id, self.subject_ref)


if __name__ == "__main__":
    unittest.main()
