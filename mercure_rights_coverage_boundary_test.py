import datetime
import unittest
from unittest.mock import Mock, patch

import mercure_rights


class MercureRightsCoverageBoundaryTest(unittest.TestCase):
    @patch.object(mercure_rights.mercure_provider_coverage, "boundary")
    @patch.object(mercure_rights.mercure, "_appointments", return_value=[])
    @patch.object(mercure_rights.mercure, "_calendar_events", return_value=[])
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact")
    @patch.object(mercure_rights.mercure, "_session")
    def test_attested_provider_boundary_does_not_claim_inventory_completeness(
        self, session, contact, today, events, appointments, boundary
    ):
        session.return_value = Mock()
        today.return_value = datetime.date(2026, 9, 23)
        contact.return_value = {"email": "client@example.fr", "telephone": ""}
        boundary.return_value = {
            "state": "attested",
            "attested": True,
            "historyStart": "2018-04-12",
            "futureDays": 180,
            "evidenceSha256": "a" * 64,
            "reason": "",
        }

        result = mercure_rights.contact_snapshot("account:12")

        boundary.assert_called_once_with(datetime.date(2026, 9, 23))
        self.assertTrue(result["coverage"]["providerBoundaryAttested"])
        self.assertFalse(result["coverage"]["providerBoundaryAppliedToInventory"])
        self.assertFalse(result["coverage"]["appointments"])
        self.assertFalse(result["coverage"]["vehicles"])
        self.assertFalse(result["coverage"]["billing"])
        self.assertTrue(result["partial"])

    @patch.object(mercure_rights.mercure_provider_coverage, "boundary")
    @patch.object(mercure_rights.mercure, "_calendar_events", side_effect=RuntimeError("provider secret"))
    @patch.object(mercure_rights.mercure, "business_today")
    @patch.object(mercure_rights.mercure, "_customer_contact", return_value={"email": "", "telephone": ""})
    @patch.object(mercure_rights.mercure, "_session", return_value=Mock())
    def test_unconfigured_boundary_and_inventory_failure_remain_fail_closed(
        self, session, contact, today, events, boundary
    ):
        today.return_value = datetime.date(2026, 9, 23)
        boundary.return_value = {
            "state": "unconfigured",
            "attested": False,
            "historyStart": "",
            "futureDays": 0,
            "evidenceSha256": "",
            "reason": "provider_boundary_not_attested",
        }

        result = mercure_rights.contact_snapshot("free:42")

        self.assertFalse(result["coverage"]["providerBoundaryAttested"])
        self.assertFalse(result["coverage"]["boundedOperationalInventory"])
        self.assertFalse(result["coverage"]["providerBoundaryAppliedToInventory"])
        self.assertNotIn("provider secret", repr(result))


if __name__ == "__main__":
    unittest.main()
