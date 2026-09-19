import unittest
from unittest.mock import Mock, patch

import mercure_admin_client as mercure


class MercureSchemaTest(unittest.TestCase):
    @patch.object(mercure, "_session")
    @patch.object(mercure, "_appointments")
    @patch.object(mercure, "_calendar_events")
    def test_review_email_comes_from_calendar_extended_props(self, events, appointments, session):
        session.return_value = Mock()
        appointments.return_value = [{"id": 42, "date_rdv": "2026-09-19 10:00:00", "est_honore": 1, "name": "Client"}]
        events.return_value = [{
            "id": 42,
            "backgroundColor": "#cccccc",
            "extendedProps": {"rendezVousId": 42, "email": "client@example.fr"},
        }]
        rows = mercure.review_followup_rows(2)
        self.assertEqual(rows[0]["email"], "client@example.fr")
        self.assertTrue(rows[0]["finished"])

    @patch.object(mercure, "_session")
    @patch.object(mercure, "_calendar_events")
    @patch.object(mercure, "vehicle_details")
    def test_reminder_source_uses_verified_vehicle_due_date(self, vehicle, events, session):
        session.return_value = Mock()
        events.return_value = [{
            "extendedProps": {
                "rendezVousId": 77,
                "clientCompteId": "12",
                "clientLibreId": "",
                "vehiculeId": ["99"],
            },
        }]
        vehicle.return_value = {"date_echeance": "2026-11-18"}
        rows = mercure.reminder_source_rows("2026-09-01", "2026-09-20")
        self.assertEqual(rows, [{
            "vehicleId": "99", "clientKind": "account", "clientId": "12",
            "dueDate": "2026-11-18", "appointmentId": "77",
        }])


if __name__ == "__main__":
    unittest.main()
