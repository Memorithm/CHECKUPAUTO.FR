import unittest
from unittest import mock

import rights_execution_dispatch as dispatch


class RightsExecutionBookingConversionTest(unittest.TestCase):
    def test_erasure_privacy_suppression_runs_booking_conversion_adapter(self):
        payload = {
            "id": "request-1",
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        booking_result = {
            "store": "booking_conversions",
            "executed": True,
            "coverageComplete": True,
            "affectedRows": 1,
            "browserSyntheticCoverageComplete": False,
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
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="request-1"),
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_for_mercure_subject",
                return_value={"executed": True},
            ) as review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_for_mercure_subject",
                return_value=booking_result,
            ) as booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        central.assert_called_once()
        review.assert_called_once_with("request-1", "account:42")
        booking.assert_called_once_with("request-1", "account:42")
        self.assertEqual(result["bookingConversionErasure"], booking_result)

    def test_non_erasure_privacy_suppression_does_not_delete_booking_conversions(self):
        payload = {
            "id": "request-2",
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
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_for_mercure_subject",
            ) as review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_for_mercure_subject",
            ) as booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        review.assert_not_called()
        booking.assert_not_called()
        self.assertNotIn("bookingConversionErasure", result)


if __name__ == "__main__":
    unittest.main()
