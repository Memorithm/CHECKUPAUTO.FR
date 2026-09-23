import datetime
import unittest
from unittest.mock import Mock, patch

import mercure_rights


class MercureRightsAttestedInventoryTest(unittest.TestCase):
    def test_provider_windows_are_bounded_and_exact(self):
        windows = mercure_rights._provider_windows(
            datetime.date(2025, 1, 1), datetime.date(2026, 9, 24)
        )
        self.assertEqual(windows, [
            ("2025-01-01", "2026-01-01"),
            ("2026-01-01", "2026-09-24"),
        ])

    def test_excessive_provider_span_fails_closed(self):
        with self.assertRaises(ValueError):
            mercure_rights._provider_windows(
                datetime.date(1700, 1, 1), datetime.date(2026, 9, 24)
            )

    @patch.object(mercure_rights.mercure, "vehicle_details")
    @patch.object(mercure_rights.mercure, "_appointments")
    @patch.object(mercure_rights.mercure, "_calendar_events")
    def test_attested_windows_merge_subject_rows_and_filter_other_clients(
        self, events, billing, vehicle_details
    ):
        session = Mock()
        events.side_effect = [
            [{
                "id": "rdv-1",
                "start": "2025-06-01T10:00:00+02:00",
                "extendedProps": {"clientCompteId": "12", "vehiculeId": ["veh-1"]},
            }],
            [
                {
                    "id": "rdv-2",
                    "start": "2026-06-01T10:00:00+02:00",
                    "extendedProps": {"clientCompteId": "12", "vehiculeId": ["veh-2"]},
                },
                {
                    "id": "rdv-other",
                    "extendedProps": {"clientCompteId": "99", "vehiculeId": ["veh-other"]},
                },
            ],
        ]
        billing.side_effect = [
            [{"id": "rdv-1", "etat_paiement": "payé", "prix_tcc": "80"}],
            [
                {"id": "rdv-2", "etat_paiement": "payé", "prix_tcc": "90"},
                {"id": "rdv-other", "etat_paiement": "payé", "prix_tcc": "999"},
            ],
        ]
        vehicle_details.side_effect = [
            {"date_echeance": "2027-01-01"},
            {"date_echeance": "2027-02-01"},
        ]

        result = mercure_rights._attested_operational_inventory(
            session,
            "account",
            "12",
            {
                "attested": True,
                "historyStart": "2025-01-01",
                "futureDays": 0,
            },
            datetime.date(2026, 9, 23),
        )

        self.assertEqual(result["sourceWindowCount"], 2)
        self.assertEqual(result["appointmentCountInWindow"], 2)
        self.assertEqual(result["billingCountInWindow"], 2)
        self.assertTrue(result["billingMatchesAppointments"])
        self.assertEqual(
            [row["appointmentId"] for row in result["appointments"]],
            ["rdv-1", "rdv-2"],
        )
        self.assertNotIn("rdv-other", repr(result))
        self.assertNotIn("999", repr(result))

    @patch.object(mercure_rights.mercure, "_appointments", return_value=[])
    @patch.object(mercure_rights.mercure, "_calendar_events")
    def test_missing_billing_row_prevents_billing_completeness(self, events, billing):
        events.return_value = [{
            "id": "rdv-1",
            "extendedProps": {"clientLibreId": "42", "vehiculeId": []},
        }]
        result = mercure_rights._attested_operational_inventory(
            Mock(),
            "free",
            "42",
            {"attested": True, "historyStart": "2026-09-01", "futureDays": 0},
            datetime.date(2026, 9, 23),
        )
        self.assertEqual(result["appointmentCountInWindow"], 1)
        self.assertFalse(result["billingMatchesAppointments"])


if __name__ == "__main__":
    unittest.main()
