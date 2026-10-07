import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mercure_provider_coverage as coverage


class MercureProviderCoveragePrivateConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        values = {
            "CYBERCHECK_PRIVATE_DIR": self.tmp.name,
            coverage.HISTORY_START_ENV: "",
            coverage.FUTURE_DAYS_ENV: "",
            coverage.EVIDENCE_SHA256_ENV: "",
            coverage.APPOINTMENT_SOURCE_ENV: "",
            coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: "",
            coverage.VEHICLE_SOURCE_ENV: "",
            coverage.VEHICLE_EVIDENCE_SHA256_ENV: "",
        }
        self.env = mock.patch.dict(os.environ, values, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    @staticmethod
    def payload(**overrides):
        data = {
            "historyStart": "2020-01-01",
            "futureDays": 730,
            "evidenceSha256": "a" * 64,
            "appointmentEvidenceSha256": "b" * 64,
            "vehicleEvidenceSha256": "c" * 64,
            "confirmBoundary": coverage.CONFIRM_BOUNDARY,
            "confirmAppointment": coverage.CONFIRM_APPOINTMENT,
            "confirmVehicle": coverage.CONFIRM_VEHICLE,
        }
        data.update(overrides)
        return data

    def test_private_configuration_is_atomic_private_and_bounded(self):
        info = coverage.save_private_configuration(self.payload())
        path = coverage._private_path()
        self.assertTrue(path.is_file())
        self.assertFalse(path.is_symlink())
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema"], coverage.PRIVATE_SCHEMA)
        self.assertEqual(
            raw["appointmentSource"],
            coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
        )
        self.assertEqual(
            raw["vehicleSource"],
            coverage.AUTHORITATIVE_APPOINTMENT_SOURCE,
        )
        self.assertEqual(info["source"], "private")
        self.assertTrue(info["editable"])
        self.assertFalse(info["rawEvidenceStored"])
        self.assertEqual(info["boundary"]["state"], "attested")
        self.assertTrue(info["boundary"]["attested"])
        self.assertTrue(info["boundary"]["appointmentInventory"]["attested"])
        self.assertTrue(info["boundary"]["vehicleInventory"]["attested"])
        self.assertNotIn("provider contract body", repr(info))

    def test_vehicle_evidence_is_optional_and_does_not_block_temporal_boundary(self):
        info = coverage.save_private_configuration(
            self.payload(vehicleEvidenceSha256="", confirmVehicle="")
        )
        self.assertTrue(info["boundary"]["attested"])
        self.assertEqual(
            info["boundary"]["vehicleInventory"]["state"],
            "unconfigured",
        )
        raw = json.loads(coverage._private_path().read_text(encoding="utf-8"))
        self.assertEqual(raw["vehicleSource"], "")
        self.assertEqual(raw["vehicleEvidenceSha256"], "")

    def test_confirmations_are_required(self):
        with self.assertRaises(PermissionError):
            coverage.save_private_configuration(
                self.payload(confirmBoundary="")
            )
        with self.assertRaises(PermissionError):
            coverage.save_private_configuration(
                self.payload(confirmAppointment="")
            )
        with self.assertRaises(PermissionError):
            coverage.save_private_configuration(
                self.payload(confirmVehicle="")
            )
        self.assertFalse(coverage._private_path().exists())

    def test_environment_configuration_has_priority_and_blocks_private_mutation(self):
        coverage.save_private_configuration(self.payload())
        with mock.patch.dict(
            os.environ,
            {
                coverage.HISTORY_START_ENV: "2019-01-01",
                coverage.FUTURE_DAYS_ENV: "365",
                coverage.EVIDENCE_SHA256_ENV: "d" * 64,
                coverage.APPOINTMENT_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
                coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: "e" * 64,
            },
            clear=False,
        ):
            info = coverage.configuration_info()
            self.assertEqual(info["source"], "environment")
            self.assertFalse(info["editable"])
            self.assertEqual(info["boundary"]["historyStart"], "2019-01-01")
            with self.assertRaises(RuntimeError):
                coverage.save_private_configuration(self.payload())
            with self.assertRaises(RuntimeError):
                coverage.delete_private_configuration()

    def test_invalid_private_file_fails_closed_without_reflecting_contents(self):
        path = coverage._private_path()
        path.parent.mkdir(parents=True)
        path.write_text('{"schema":"wrong","secret":"do-not-reflect"}', encoding="utf-8")
        result = coverage.boundary(datetime.date(2026, 10, 7))
        self.assertEqual(result["state"], "invalid")
        self.assertFalse(result["attested"])
        self.assertEqual(result["reason"], "provider_private_configuration_invalid")
        self.assertNotIn("do-not-reflect", repr(result))

    def test_symlink_private_configuration_is_rejected_fail_closed(self):
        path = coverage._private_path()
        path.parent.mkdir(parents=True)
        target = Path(self.tmp.name) / "outside.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
        info = coverage.configuration_info()
        self.assertEqual(info["source"], "private")
        self.assertFalse(info["configured"])
        self.assertEqual(info["boundary"]["state"], "invalid")
        with self.assertRaises(RuntimeError):
            coverage.save_private_configuration(self.payload())

    def test_delete_removes_private_configuration_only(self):
        coverage.save_private_configuration(self.payload())
        result = coverage.delete_private_configuration()
        self.assertFalse(coverage._private_path().exists())
        self.assertFalse(result["configured"])
        self.assertEqual(result["source"], "none")
        self.assertEqual(result["boundary"]["state"], "unconfigured")


if __name__ == "__main__":
    unittest.main()
