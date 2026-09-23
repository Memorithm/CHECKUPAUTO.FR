import datetime
import unittest
from unittest.mock import Mock, patch

import mercure_rights


class MercureRightsVehicleCoverageTest(unittest.TestCase):
    def _boundary(self, vehicle_attested):
        return {
            "state": "attested",
            "attested": True,
            "historyStart": "2026-09-01",
            "futureDays": 0,
            "evidenceSha256": "a" * 64,
            "reason": "",
            "vehicleInventory": {
                "state": "attested" if vehicle_attested else "unconfigured",
                "attested": vehicle_attested,
                "source": (
                    "appointment_calendar_subject_vehicle_set"
                    if vehicle_attested
                    else ""
                ),
                "evidenceSha256": "b" * 64 if vehicle_attested else "",
                "reason": "" if vehicle_attested else "provider_vehicle_inventory_not_attested",
            },
        }

    @patch.object(mercure_rights.mercure_provider_coverage, "boundary")
    @patch.object(mercure_rights.mercure, "vehicle_details")
    @patch.object(mercure_rights.mercure, "_appointments")
    @patch.object(mercure_rights.mercure, "_calendar_events")
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_independent_attestation_allows_vehicle_inventory_completeness(
        self, session, contact, today, events, billing, vehicle_details, boundary
    ):
        provider_session = Mock()
        session.return_value = provider_session
        contact.return_value = {"email": "", "telephone": ""}
        today.return_value = datetime.date(2026, 9, 23)
        boundary.return_value = self._boundary(True)
        events.return_value = [{
            "id": "rdv-1",
            "extendedProps": {"clientCompteId": "12", "vehiculeId": ["veh-1"]},
        }]
        billing.return_value = [{
            "id": "rdv-1", "etat_paiement": "payé", "prix_tcc": "80"
        }]
        vehicle_details.return_value = {"date_echeance": "2027-01-01"}

        result = mercure_rights.contact_snapshot("account:12")

        self.assertTrue(result["coverage"]["providerBoundaryAttested"])
        self.assertTrue(result["coverage"]["providerVehicleInventoryAttested"])
        self.assertTrue(result["coverage"]["vehicles"])
        self.assertTrue(result["coverage"]["appointments"])
        self.assertTrue(result["coverage"]["billing"])
        self.assertTrue(result["partial"])
        vehicle_details.assert_called_once_with("veh-1", provider_session)

    @patch.object(mercure_rights.mercure_provider_coverage, "boundary")
    @patch.object(mercure_rights.mercure, "vehicle_details")
    @patch.object(mercure_rights.mercure, "_appointments", return_value=[])
    @patch.object(mercure_rights.mercure, "_calendar_events")
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_temporal_attestation_alone_never_proves_vehicle_exhaustion(
        self, session, contact, today, events, billing, vehicle_details, boundary
    ):
        session.return_value = Mock()
        contact.return_value = {"email": "", "telephone": ""}
        today.return_value = datetime.date(2026, 9, 23)
        boundary.return_value = self._boundary(False)
        events.return_value = []

        result = mercure_rights.contact_snapshot("account:12")

        self.assertTrue(result["coverage"]["providerBoundaryAttested"])
        self.assertFalse(result["coverage"]["providerVehicleInventoryAttested"])
        self.assertFalse(result["coverage"]["vehicles"])
        vehicle_details.assert_not_called()

    @patch.object(mercure_rights.mercure_provider_coverage, "boundary")
    @patch.object(mercure_rights.mercure, "vehicle_details")
    @patch.object(mercure_rights.mercure, "_appointments")
    @patch.object(mercure_rights.mercure, "_calendar_events")
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_vehicle_provider_failure_keeps_attested_inventory_incomplete(
        self, session, contact, today, events, billing, vehicle_details, boundary
    ):
        session.return_value = Mock()
        contact.return_value = {"email": "", "telephone": ""}
        today.return_value = datetime.date(2026, 9, 23)
        boundary.return_value = self._boundary(True)
        events.return_value = [{
            "id": "rdv-1",
            "extendedProps": {"clientCompteId": "12", "vehiculeId": ["veh-1"]},
        }]
        billing.return_value = [{
            "id": "rdv-1", "etat_paiement": "payé", "prix_tcc": "80"
        }]
        vehicle_details.side_effect = RuntimeError("provider secret detail")

        result = mercure_rights.contact_snapshot("account:12")

        self.assertTrue(result["coverage"]["providerVehicleInventoryAttested"])
        self.assertFalse(result["coverage"]["vehicles"])
        self.assertEqual(result["operationalInventory"]["vehicleState"], "unavailable")
        self.assertNotIn("provider secret detail", repr(result))


if __name__ == "__main__":
    unittest.main()
