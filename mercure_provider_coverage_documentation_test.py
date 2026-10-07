import pathlib
import unittest

import mercure_provider_coverage as coverage


ROOT = pathlib.Path(__file__).resolve().parent
RUNBOOK = (ROOT / "docs" / "mercure-dsar-evidence.md").read_text(encoding="utf-8")


class MercureProviderCoverageDocumentationTest(unittest.TestCase):
    def test_runbook_names_every_provider_evidence_environment_variable(self):
        expected = {
            coverage.HISTORY_START_ENV,
            coverage.FUTURE_DAYS_ENV,
            coverage.EVIDENCE_SHA256_ENV,
            coverage.APPOINTMENT_SOURCE_ENV,
            coverage.APPOINTMENT_EVIDENCE_SHA256_ENV,
            coverage.VEHICLE_SOURCE_ENV,
            coverage.VEHICLE_EVIDENCE_SHA256_ENV,
        }
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", RUNBOOK)

    def test_runbook_uses_exact_supported_inventory_source_identifiers(self):
        self.assertIn(
            f"`{coverage.AUTHORITATIVE_APPOINTMENT_INVENTORY_SOURCE}`",
            RUNBOOK,
        )
        self.assertIn(
            f"`{coverage.AUTHORITATIVE_APPOINTMENT_SOURCE}`",
            RUNBOOK,
        )

    def test_runbook_documents_private_admin_path_and_environment_precedence(self):
        self.assertIn("Compliance Center → Frontière DSAR Mercure", RUNBOOK)
        self.assertIn("integrations/mercure-provider-coverage.json", RUNBOOK)
        self.assertIn("Environment variables remain authoritative", RUNBOOK)
        self.assertIn("hashed locally with Web Crypto", RUNBOOK)
        self.assertIn("raw bytes are never uploaded", RUNBOOK)
        self.assertIn("MFA-protected Compliance Center form", RUNBOOK)

    def test_runbook_preserves_fail_closed_evidence_semantics(self):
        required_statements = [
            "do not prove that the observed appointment calendar is the provider's exhaustive inventory",
            "A valid temporal boundary without this independent appointment-inventory evidence remains **unattested**",
            "Observing vehicle IDs on appointments does not, by itself, prove that every vehicle",
            "Do not add it to this repository",
            "does not make `GLOBAL_COVERAGE_COMPLETE` true",
        ]
        for statement in required_statements:
            with self.subTest(statement=statement):
                self.assertIn(statement, RUNBOOK)

    def test_operator_self_check_calls_only_bounded_state_functions(self):
        self.assertIn("coverage.boundary()", RUNBOOK)
        self.assertIn("coverage.capability()", RUNBOOK)
        self.assertNotIn("registrationSecret", RUNBOOK)
        self.assertNotIn("MERCURE_PASSWORD", RUNBOOK)
        self.assertNotIn("MERCURE_TOKEN", RUNBOOK)


if __name__ == "__main__":
    unittest.main()
