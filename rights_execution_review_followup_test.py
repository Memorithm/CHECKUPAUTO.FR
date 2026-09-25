import unittest
from unittest import mock

import rights_execution_dispatch as dispatch


class RightsExecutionReviewFollowupTest(unittest.TestCase):
    @staticmethod
    def complete_snapshot(*appointment_ids):
        return {
            "coverage": {"appointments": True},
            "operationalInventory": {
                "appointments": [
                    {"appointmentId": appointment_id} for appointment_id in appointment_ids
                ],
                "appointmentCountInWindow": len(appointment_ids),
            },
        }

    def test_erasure_privacy_suppression_runs_review_followup_adapter(self):
        payload = {
            "id": "a" * 32,
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        review_result = {
            "store": "review_followup",
            "affectedRows": 1,
        }
        with (
            mock.patch.object(
                dispatch.data_subject_rights,
                "execute",
                return_value={
                    "ok": True,
                    "adapter": "privacy_suppression",
                    "requestType": "erasure",
                },
            ) as central,
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="a" * 32),
            mock.patch.object(
                dispatch.mercure_rights,
                "contact_snapshot",
                return_value=self.complete_snapshot("apt-subject"),
            ) as snapshot,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_appointments",
                return_value=review_result,
            ) as review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_appointments",
                return_value={"store": "booking_conversions"},
            ) as booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        central.assert_called_once()
        snapshot.assert_called_once_with("account:42")
        review.assert_called_once_with("a" * 32, ("apt-subject",))
        booking.assert_called_once_with("a" * 32, ("apt-subject",))
        self.assertEqual(result["reviewFollowupErasure"]["affectedRows"], 1)
        self.assertTrue(result["reviewFollowupErasure"]["executed"])
        self.assertTrue(result["reviewFollowupErasure"]["coverageComplete"])

    def test_non_erasure_privacy_suppression_does_not_delete_review_followup(self):
        payload = {
            "id": "b" * 32,
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "direct_marketing",
        }
        with (
            mock.patch.object(
                dispatch.data_subject_rights,
                "execute",
                return_value={
                    "ok": True,
                    "adapter": "privacy_suppression",
                    "requestType": "objection",
                },
            ),
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot") as snapshot,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_appointments",
            ) as review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_appointments",
            ) as booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        snapshot.assert_not_called()
        review.assert_not_called()
        booking.assert_not_called()
        self.assertNotIn("reviewFollowupErasure", result)


if __name__ == "__main__":
    unittest.main()
