import datetime
import unittest
from unittest.mock import Mock, patch

import mercure_rights


class MercureRightsTest(unittest.TestCase):
    def test_subject_reference_accepts_only_bounded_customer_identifiers(self):
        self.assertEqual(mercure_rights.parse_subject_ref("account:12"), ("account", "12"))
        self.assertEqual(
            mercure_rights.parse_subject_ref("ACCOUNT:Client-12_A"),
            ("account", "Client-12_A"),
        )
        self.assertEqual(mercure_rights.parse_subject_ref("free:client.34"), ("free", "client.34"))
        for value in (
            "",
            "account",
            "account:",
            "account:12/../../admin",
            "account:12?token=x",
            "account:12#fragment",
            "account:client id",
            "account:client:12",
            "other:12",
            "free:" + ("a" * 129),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mercure_rights.parse_subject_ref(value)

    @patch.object(mercure_rights.mercure, "vehicle_details")
    @patch.object(mercure_rights.mercure, "_calendar_events")
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_contact_snapshot_includes_only_exact_subject_bounded_inventory(
        self, session, contact, today, events, vehicle_details
    ):
        provider_session = Mock()
        session.return_value = provider_session
        today.return_value = datetime.date(2026, 9, 22)
        contact.return_value = {
            "email": "client@example.fr",
            "telephone": "+33102030405",
            "provider_secret": "must-not-leak",
        }
        events.return_value = [
            {
                "id": "rdv-1",
                "start": "2026-09-23T10:00:00+02:00",
                "end": "2026-09-23T10:30:00+02:00",
                "extendedProps": {
                    "clientCompteId": "12",
                    "vehiculeId": ["veh-1"],
                    "email": "must-not-leak-from-event@example.fr",
                },
            },
            {
                "id": "rdv-other",
                "start": "2026-09-24T10:00:00+02:00",
                "extendedProps": {"clientCompteId": "99", "vehiculeId": ["veh-other"]},
            },
        ]
        vehicle_details.return_value = {
            "date_echeance": "2027-05-12",
            "immatriculation": "AA-000-AA",
            "provider_secret": "vehicle-secret",
        }

        result = mercure_rights.contact_snapshot("account:12")

        session.assert_called_once_with()
        contact.assert_called_once_with(provider_session, "account", "12")
        events.assert_called_once_with(provider_session, "2025-09-22", "2027-09-23")
        vehicle_details.assert_called_once_with("veh-1", provider_session)
        self.assertEqual(result["provider"], "mercure")
        self.assertEqual(result["subject"], {"clientKind": "account", "clientId": "12"})
        self.assertEqual(result["contact"]["email"], "client@example.fr")
        self.assertEqual(result["contact"]["telephone"], "+33102030405")
        self.assertTrue(result["partial"])
        self.assertTrue(result["coverage"]["contact"])
        self.assertTrue(result["coverage"]["boundedOperationalInventory"])
        self.assertFalse(result["coverage"]["vehicles"])
        inventory = result["operationalInventory"]
        self.assertEqual(inventory["appointmentCountInWindow"], 1)
        self.assertEqual(len(inventory["appointments"]), 1)
        self.assertEqual(inventory["appointments"][0]["appointmentId"], "rdv-1")
        self.assertEqual(inventory["vehicles"], [
            {"vehicleId": "veh-1", "technicalInspectionDueDate": "2027-05-12"}
        ])
        rendered = repr(result)
        self.assertNotIn("must-not-leak", rendered)
        self.assertNotIn("AA-000-AA", rendered)
        self.assertNotIn("vehicle-secret", rendered)
        self.assertNotIn("rdv-other", rendered)
        self.assertNotIn("veh-other", rendered)

    @patch.object(mercure_rights.mercure, "vehicle_details")
    @patch.object(mercure_rights.mercure, "_calendar_events")
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_unsafe_vehicle_identifier_is_never_used_as_provider_path(
        self, session, contact, today, events, vehicle_details
    ):
        session.return_value = Mock()
        today.return_value = datetime.date(2026, 9, 22)
        contact.return_value = {"email": "", "telephone": ""}
        events.return_value = [{
            "id": "rdv-1",
            "extendedProps": {"clientLibreId": "free-1", "vehiculeId": ["../../admin"]},
        }]

        result = mercure_rights.contact_snapshot("free:free-1")

        vehicle_details.assert_not_called()
        self.assertEqual(result["operationalInventory"]["vehicles"], [])
        self.assertEqual(result["operationalInventory"]["appointments"][0]["vehicleIds"], [])

    @patch.object(mercure_rights.mercure, "_calendar_events")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_inventory_failure_keeps_contact_export_partial_without_error_detail(
        self, session, contact, events
    ):
        session.return_value = Mock()
        contact.return_value = {"email": "client@example.fr", "telephone": ""}
        events.side_effect = RuntimeError("provider secret detail")

        result = mercure_rights.contact_snapshot("account:12")

        self.assertEqual(result["contact"]["email"], "client@example.fr")
        self.assertEqual(result["operationalInventory"]["state"], "unavailable")
        self.assertFalse(result["coverage"]["boundedOperationalInventory"])
        self.assertTrue(result["partial"])
        self.assertNotIn("provider secret detail", repr(result))


if __name__ == "__main__":
    unittest.main()
