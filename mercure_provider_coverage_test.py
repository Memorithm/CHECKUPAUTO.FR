import datetime
import os
import unittest
from unittest.mock import patch

import mercure_provider_coverage as coverage


class MercureProviderCoverageTest(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 9, 23)

    def _env(self, **values):
        base = {
            coverage.HISTORY_START_ENV: "",
            coverage.FUTURE_DAYS_ENV: "",
            coverage.EVIDENCE_SHA256_ENV: "",
            coverage.APPOINTMENT_SOURCE_ENV: "",
            coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: "",
            coverage.VEHICLE_SOURCE_ENV: "",
            coverage.VEHICLE_EVIDENCE_SHA256_ENV: "",
        }
        base.update(values)
        return patch.dict(os.environ, base, clear=False)

    def test_unconfigured_boundary_never_claims_attestation(self):
        with self._env():
            result = coverage.boundary(self.today)
        self.assertEqual(result["state"], "unconfigured")
        self.assertFalse(result["attested"])
        self.assertEqual(result["reason"], "provider_boundary_not_attested")
        self.assertEqual(result["appointmentInventory"]["state"], "unconfigured")
        self.assertFalse(result["appointmentInventory"]["attested"])
        self.assertEqual(result["vehicleInventory"]["state"], "unconfigured")
        self.assertFalse(result["vehicleInventory"]["attested"])

    def test_temporal_boundary_alone_never_proves_appointment_source_authority(self):
        digest = "a" * 64
        with self._env(**{
            coverage.HISTORY_START_ENV: "2018-04-12",
            coverage.FUTURE_DAYS_ENV: "180",
            coverage.EVIDENCE_SHA256_ENV: digest,
        }):
            result = coverage.boundary(self.today)
        self.assertEqual(result["state"], "unconfigured")
        self.assertFalse(result["attested"])
        self.assertEqual(result["historyStart"], "2018-04-12")
        self.assertEqual(result["futureDays"], 180)
        self.assertEqual(result["evidenceSha256"], digest)
        self.assertEqual(result["reason"], "provider_appointment_inventory_not_attested")
        self.assertEqual(result["appointmentInventory"]["state"], "unconfigured")

    def test_complete_evidence_backed_boundary_is_attested(self):
        digest = "a" * 64
        appointment_digest = "d" * 64
        with self._env(**{
            coverage.HISTORY_START_ENV: "2018-04-12",
            coverage.FUTURE_DAYS_ENV: "180",
            coverage.EVIDENCE_SHA256_ENV: digest,
            coverage.APPOINTMENT_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
            coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: appointment_digest,
        }):
            result = coverage.boundary(self.today)
        self.assertEqual(result, {
            "state": "attested",
            "attested": True,
            "historyStart": "2018-04-12",
            "futureDays": 180,
            "evidenceSha256": digest,
            "reason": "",
            "appointmentInventory": {
                "state": "attested",
                "attested": True,
                "source": coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
                "evidenceSha256": appointment_digest,
                "reason": "",
            },
            "vehicleInventory": {
                "state": "unconfigured",
                "attested": False,
                "source": "",
                "evidenceSha256": "",
                "reason": "provider_vehicle_inventory_not_attested",
            },
        })

    def test_appointment_inventory_requires_separate_authoritative_evidence(self):
        digest = "e" * 64
        with self._env(**{
            coverage.APPOINTMENT_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
            coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: digest,
        }):
            result = coverage.appointment_inventory_attestation()
        self.assertEqual(result, {
            "state": "attested",
            "attested": True,
            "source": coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
            "evidenceSha256": digest,
            "reason": "",
        })

    def test_appointment_inventory_partial_or_unsupported_configuration_fails_closed(self):
        cases = [
            (
                {coverage.APPOINTMENT_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE},
                "provider_appointment_inventory_configuration_incomplete",
            ),
            (
                {
                    coverage.APPOINTMENT_SOURCE_ENV: "invented-provider-endpoint",
                    coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: "f" * 64,
                },
                "provider_appointment_inventory_source_unsupported",
            ),
            (
                {
                    coverage.APPOINTMENT_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
                    coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: "raw-provider-secret",
                },
                "provider_appointment_inventory_evidence_hash_invalid",
            ),
        ]
        for values, reason in cases:
            with self.subTest(reason=reason), self._env(**values):
                result = coverage.appointment_inventory_attestation()
                self.assertEqual(result["state"], "invalid")
                self.assertFalse(result["attested"])
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["source"], "")
                self.assertEqual(result["evidenceSha256"], "")
                self.assertNotIn("raw-provider-secret", repr(result))

    def test_invalid_appointment_inventory_invalidates_temporal_boundary(self):
        with self._env(**{
            coverage.HISTORY_START_ENV: "2020-01-01",
            coverage.FUTURE_DAYS_ENV: "30",
            coverage.EVIDENCE_SHA256_ENV: "a" * 64,
            coverage.APPOINTMENT_SOURCE_ENV: "invented-provider-endpoint",
            coverage.APPOINTMENT_EVIDENCE_SHA256_ENV: "b" * 64,
        }):
            result = coverage.boundary(self.today)
        self.assertEqual(result["state"], "invalid")
        self.assertFalse(result["attested"])
        self.assertEqual(result["reason"], "provider_appointment_inventory_source_unsupported")

    def test_vehicle_inventory_requires_separate_authoritative_evidence(self):
        digest = "b" * 64
        with self._env(**{
            coverage.VEHICLE_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_SOURCE,
            coverage.VEHICLE_EVIDENCE_SHA256_ENV: digest,
        }):
            result = coverage.vehicle_inventory_attestation()
        self.assertEqual(result, {
            "state": "attested",
            "attested": True,
            "source": coverage.AUTHORITATIVE_APPOINTMENT_SOURCE,
            "evidenceSha256": digest,
            "reason": "",
        })

    def test_vehicle_inventory_partial_or_unsupported_configuration_fails_closed(self):
        cases = [
            (
                {coverage.VEHICLE_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_SOURCE},
                "provider_vehicle_inventory_configuration_incomplete",
            ),
            (
                {
                    coverage.VEHICLE_SOURCE_ENV: "invented-provider-endpoint",
                    coverage.VEHICLE_EVIDENCE_SHA256_ENV: "c" * 64,
                },
                "provider_vehicle_inventory_source_unsupported",
            ),
            (
                {
                    coverage.VEHICLE_SOURCE_ENV: coverage.AUTHORITATIVE_APPOINTMENT_SOURCE,
                    coverage.VEHICLE_EVIDENCE_SHA256_ENV: "raw-provider-secret",
                },
                "provider_vehicle_inventory_evidence_hash_invalid",
            ),
        ]
        for values, reason in cases:
            with self.subTest(reason=reason), self._env(**values):
                result = coverage.vehicle_inventory_attestation()
                self.assertEqual(result["state"], "invalid")
                self.assertFalse(result["attested"])
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["source"], "")
                self.assertEqual(result["evidenceSha256"], "")
                self.assertNotIn("raw-provider-secret", repr(result))

    def test_partial_configuration_fails_closed_without_reflecting_values(self):
        with self._env(**{coverage.HISTORY_START_ENV: "2018-04-12"}):
            result = coverage.boundary(self.today)
        self.assertEqual(result["state"], "invalid")
        self.assertFalse(result["attested"])
        self.assertEqual(result["historyStart"], "")
        self.assertEqual(result["evidenceSha256"], "")

    def test_invalid_dates_horizon_and_evidence_fail_closed(self):
        cases = [
            ("not-a-date", "1", "a" * 64, "provider_history_start_invalid"),
            ("2027-01-01", "1", "a" * 64, "provider_history_start_in_future"),
            ("2020-01-01", "nope", "a" * 64, "provider_future_horizon_invalid"),
            ("2020-01-01", "3651", "a" * 64, "provider_future_horizon_out_of_range"),
            ("2020-01-01", "30", "secret-not-a-digest", "provider_evidence_hash_invalid"),
        ]
        for start, future, evidence, reason in cases:
            with self.subTest(reason=reason), self._env(**{
                coverage.HISTORY_START_ENV: start,
                coverage.FUTURE_DAYS_ENV: future,
                coverage.EVIDENCE_SHA256_ENV: evidence,
            }):
                result = coverage.boundary(self.today)
                self.assertEqual(result["state"], "invalid")
                self.assertFalse(result["attested"])
                self.assertEqual(result["reason"], reason)
                self.assertNotIn("secret-not-a-digest", repr(result))

    def test_capability_refuses_observation_as_exhaustion_proof(self):
        result = coverage.capability()
        self.assertTrue(result["requiresExplicitProviderBoundary"])
        self.assertTrue(result["requiresExternalEvidenceSha256"])
        self.assertTrue(result["requiresIndependentAppointmentInventoryEvidence"])
        self.assertEqual(
            result["appointmentInventoryAuthoritativeSource"],
            coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE,
        )
        self.assertTrue(result["requiresIndependentVehicleInventoryEvidence"])
        self.assertFalse(result["rawEvidenceStoredInRepository"])
        self.assertFalse(result["emptyResultProvesHistoricalExhaustion"])
        self.assertFalse(result["calendarObservationProvesAppointmentExhaustion"])
        self.assertFalse(result["appointmentVehicleObservationProvesVehicleExhaustion"])


if __name__ == "__main__":
    unittest.main()
