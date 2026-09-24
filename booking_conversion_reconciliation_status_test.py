import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import booking_bridge as booking
import booking_conversion_reconciliation as reconciliation
import compliance_admin


class BookingConversionReconciliationStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "analytics.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.execute(
                """CREATE TABLE booking_conversions(
                     provider TEXT NOT NULL,
                     external_id TEXT NOT NULL,
                     attribution_token TEXT NOT NULL DEFAULT '',
                     PRIMARY KEY(provider, external_id)
                   )"""
            )

    def tearDown(self):
        self.tmp.cleanup()

    def insert(self, external_id: str, attribution_token: str) -> None:
        with sqlite3.connect(self.db) as db:
            db.execute(
                "INSERT INTO booking_conversions(provider,external_id,attribution_token) VALUES(?,?,?)",
                (booking.PROVIDER, external_id, attribution_token),
            )

    def test_status_counts_only_unresolved_local_synthetic_rows_without_mutating(self):
        self.insert("browser-unresolved", "sha256-v1:" + "a" * 64)
        self.insert("browser-matched", "sha256-v1:" + "b" * 64)
        self.insert("mercure-real", "sha256-v1:" + "b" * 64)
        self.insert("browser-no-attribution", "")

        state = reconciliation.status(self.db)

        self.assertTrue(state["available"])
        self.assertEqual(state["state"], "residual")
        self.assertEqual(state["unresolvedSyntheticRows"], 1)
        self.assertEqual(state["syntheticRowsWithoutAttribution"], 1)
        self.assertEqual(state["localResidualRows"], 2)
        self.assertFalse(state["providerIdInferenceUsed"])
        self.assertFalse(state["providerCoverageProven"])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM booking_conversions").fetchone()[0],
                4,
            )

    def test_status_reports_clear_without_claiming_provider_coverage(self):
        self.insert("mercure-real", "sha256-v1:" + "c" * 64)

        state = reconciliation.status(self.db)

        self.assertEqual(state["state"], "clear")
        self.assertEqual(state["localResidualRows"], 0)
        self.assertFalse(state["providerCoverageProven"])

    def test_status_is_unavailable_for_missing_or_uninitialized_store(self):
        missing = Path(self.tmp.name) / "missing.sqlite3"
        self.assertEqual(reconciliation.status(missing)["state"], "unavailable")
        self.assertFalse(missing.exists())

        empty = Path(self.tmp.name) / "empty.sqlite3"
        sqlite3.connect(empty).close()
        state = reconciliation.status(empty)
        self.assertFalse(state["available"])
        self.assertEqual(state["localResidualRows"], 0)

    def test_compliance_snapshot_surfaces_local_residuals_without_phase2_claim(self):
        compliance_db = Path(self.tmp.name) / "compliance.sqlite3"
        observed = {
            "schemaVersion": 1,
            "available": True,
            "state": "residual",
            "unresolvedSyntheticRows": 3,
            "syntheticRowsWithoutAttribution": 2,
            "localResidualRows": 5,
            "providerIdInferenceUsed": False,
            "providerCoverageProven": False,
        }
        with mock.patch.object(
            compliance_admin.booking_conversion_reconciliation,
            "status",
            return_value=observed,
        ):
            state = compliance_admin.snapshot(compliance_db)

        self.assertEqual(state["bookingConversionReconciliation"], observed)
        self.assertTrue(state["summary"]["bookingSyntheticObservabilityAvailable"])
        self.assertEqual(state["summary"]["bookingSyntheticResidualRows"], 5)
        self.assertEqual(state["summary"]["bookingSyntheticRowsWithoutAttribution"], 2)
        self.assertNotIn(
            "booking_synthetic_rows_present",
            state["summary"]["phase2Blockers"],
        )


if __name__ == "__main__":
    unittest.main()
