import unittest
from unittest import mock

import rights_execution_dispatch as dispatch


class RightsExecutionBookingConversionTest(unittest.TestCase):
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

    def test_erasure_privacy_suppression_runs_booking_conversion_adapter(self):
        payload = {
            "id": "request-1",
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        booking_result = {
            "store": "booking_conversions",
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
                dispatch.mercure_rights,
                "contact_snapshot",
                return_value=self.complete_snapshot("apt-subject"),
            ) as snapshot,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_appointments",
                return_value={"store": "review_followup"},
            ) as review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_appointments",
                return_value=booking_result,
            ) as booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        central.assert_called_once()
        self.assertTrue(central.call_args.kwargs["resume_completed_erasure"])
        snapshot.assert_called_once_with("account:42")
        review.assert_called_once_with("request-1", ("apt-subject",))
        booking.assert_called_once_with("request-1", ("apt-subject",))
        self.assertEqual(result["bookingConversionErasure"]["affectedRows"], 1)
        self.assertTrue(result["bookingConversionErasure"]["executed"])
        self.assertTrue(result["bookingConversionErasure"]["coverageComplete"])
        self.assertFalse(result["bookingConversionErasure"]["browserSyntheticCoverageComplete"])

    def test_same_first_snapshot_is_used_when_provider_inventory_changes(self):
        payload = {
            "id": "request-race",
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        first = self.complete_snapshot("apt-first")
        changed = self.complete_snapshot("apt-first", "apt-late")
        with (
            mock.patch.object(
                dispatch.data_subject_rights,
                "execute",
                return_value={
                    "ok": True,
                    "adapter": "privacy_suppression",
                    "requestType": "erasure",
                },
            ),
            mock.patch.object(
                dispatch.data_subject_rights,
                "_request_id",
                return_value="request-race",
            ),
            mock.patch.object(
                dispatch.mercure_rights,
                "contact_snapshot",
                side_effect=[first, changed],
            ) as snapshot,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_appointments",
                return_value={"store": "review_followup"},
            ) as review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_appointments",
                return_value={"store": "booking_conversions"},
            ) as booking,
        ):
            dispatch.execute(payload, "compliance.sqlite3")

        self.assertEqual(snapshot.call_count, 1)
        review.assert_called_once_with("request-race", ("apt-first",))
        booking.assert_called_once_with("request-race", ("apt-first",))

    def test_incomplete_shared_inventory_mutates_neither_store(self):
        payload = {
            "id": "request-incomplete",
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        incomplete = {
            "coverage": {"appointments": False},
            "operationalInventory": {
                "appointments": [{"appointmentId": "apt-subject"}],
                "appointmentCountInWindow": 1,
            },
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
            ),
            mock.patch.object(
                dispatch.data_subject_rights,
                "_request_id",
                return_value="request-incomplete",
            ),
            mock.patch.object(
                dispatch.mercure_rights,
                "contact_snapshot",
                return_value=incomplete,
            ) as snapshot,
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

        snapshot.assert_called_once_with("account:42")
        review.assert_not_called()
        booking.assert_not_called()
        self.assertEqual(
            result["reviewFollowupErasure"]["reason"],
            "mercure_appointment_inventory_incomplete",
        )
        self.assertEqual(
            result["bookingConversionErasure"]["reason"],
            "mercure_appointment_inventory_incomplete",
        )

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
        self.assertNotIn("bookingConversionErasure", result)


if __name__ == "__main__":
    unittest.main()
