from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import compliance_contract_rights as contracts


class ComplianceContractSubjectCoverageTest(unittest.TestCase):
    def _env(self, source: str = "", evidence: str = "") -> dict[str, str]:
        return {
            contracts.SUBJECT_INVENTORY_SOURCE_ENV: source,
            contracts.SUBJECT_INVENTORY_EVIDENCE_SHA256_ENV: evidence,
        }

    @staticmethod
    def _complete_provider_snapshot() -> dict:
        return {
            "contact": {"email": "must-not-leak@example.test"},
            "coverage": {"appointments": True},
            "operationalInventory": {
                "state": "available",
                "appointments": [
                    {"appointmentId": "contract-1"},
                    {"appointmentId": "contract-2"},
                ],
                "appointmentCountInWindow": 2,
                "appointmentIdsMissing": 0,
                "appointmentsTruncated": False,
            },
        }

    def test_unconfigured_attestation_fails_closed(self):
        with patch.dict(os.environ, self._env(), clear=False):
            state = contracts.subject_inventory_attestation()
        self.assertEqual(state["state"], "unconfigured")
        self.assertFalse(state["attested"])
        self.assertEqual(state["evidenceSha256"], "")
        self.assertEqual(state["reason"], "contract_subject_inventory_not_attested")

    def test_incomplete_or_unsupported_configuration_is_invalid(self):
        with patch.dict(
            os.environ,
            self._env(contracts.AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE, ""),
            clear=False,
        ):
            incomplete = contracts.subject_inventory_attestation()
        self.assertEqual(incomplete["state"], "invalid")
        self.assertFalse(incomplete["attested"])
        self.assertEqual(
            incomplete["reason"], "contract_subject_inventory_configuration_incomplete"
        )

        with patch.dict(os.environ, self._env("manual_contract_list", "a" * 64), clear=False):
            unsupported = contracts.subject_inventory_attestation()
        self.assertEqual(unsupported["state"], "invalid")
        self.assertEqual(unsupported["reason"], "contract_subject_inventory_source_unsupported")

    def test_invalid_evidence_digest_is_rejected(self):
        with patch.dict(
            os.environ,
            self._env(contracts.AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE, "not-a-digest"),
            clear=False,
        ):
            state = contracts.subject_inventory_attestation()
        self.assertEqual(state["state"], "invalid")
        self.assertFalse(state["attested"])
        self.assertEqual(state["reason"], "contract_subject_inventory_evidence_hash_invalid")

    def test_attested_boundary_exposes_only_source_and_sha256(self):
        digest = "b" * 64
        raw_marker = "RAW-CONTRACT-EVIDENCE-MUST-NOT-BE-RETURNED"
        with patch.dict(
            os.environ,
            self._env(contracts.AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE, digest),
            clear=False,
        ):
            state = contracts.subject_inventory_attestation()
            capability = contracts.capability()

        self.assertEqual(state, {
            "state": "attested",
            "attested": True,
            "source": contracts.AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE,
            "evidenceSha256": digest,
            "reason": "",
        })
        self.assertNotIn(raw_marker, repr(state))
        self.assertTrue(capability["partial"])
        self.assertFalse(capability["crossIdentityBinding"])
        self.assertTrue(capability["subjectWideExportPrimitiveReady"])
        self.assertTrue(capability["requiresSubjectInventoryAttestation"])
        self.assertEqual(capability["subjectInventoryAttestation"], state)
        self.assertFalse(capability["rawEvidenceStoredInRepository"])
        self.assertFalse(capability["singleContractExportProvesSubjectExhaustion"])

    def test_subject_snapshot_becomes_complete_only_with_both_proofs(self):
        provider = self._complete_provider_snapshot()
        digest = "c" * 64
        with patch.dict(
            os.environ,
            self._env(contracts.AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE, digest),
            clear=False,
        ), patch.object(
            contracts,
            "snapshot",
            side_effect=lambda ref, db_path=None: {"contractRef": ref, "partial": True},
        ) as local_snapshot:
            result = contracts.subject_snapshot(provider)

        self.assertTrue(result["coverageComplete"])
        self.assertFalse(result["partial"])
        self.assertTrue(result["providerAppointmentsComplete"])
        self.assertEqual(result["contractCount"], 2)
        self.assertEqual(
            [row["contractRef"] for row in result["contracts"]],
            ["contract-1", "contract-2"],
        )
        self.assertEqual(local_snapshot.call_count, 2)
        self.assertEqual(result["subjectInventory"]["evidenceSha256"], digest)
        self.assertNotIn("must-not-leak@example.test", repr(result))

    def test_subject_snapshot_stays_partial_without_attestation_or_exact_inventory(self):
        provider = self._complete_provider_snapshot()
        with patch.dict(os.environ, self._env(), clear=False), patch.object(
            contracts,
            "snapshot",
            side_effect=lambda ref, db_path=None: {"contractRef": ref, "partial": True},
        ):
            unattested = contracts.subject_snapshot(provider)
        self.assertFalse(unattested["coverageComplete"])
        self.assertTrue(unattested["partial"])
        self.assertTrue(unattested["providerAppointmentsComplete"])

        provider["operationalInventory"]["appointmentCountInWindow"] = 3
        with patch.dict(
            os.environ,
            self._env(contracts.AUTHORITATIVE_SUBJECT_INVENTORY_SOURCE, "d" * 64),
            clear=False,
        ), patch.object(
            contracts,
            "snapshot",
            side_effect=lambda ref, db_path=None: {"contractRef": ref, "partial": True},
        ):
            mismatched = contracts.subject_snapshot(provider)
        self.assertFalse(mismatched["providerAppointmentsComplete"])
        self.assertFalse(mismatched["coverageComplete"])
        self.assertTrue(mismatched["partial"])


if __name__ == "__main__":
    unittest.main()
