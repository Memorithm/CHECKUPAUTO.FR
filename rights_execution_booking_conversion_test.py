import unittest
from unittest import mock

import rights_execution_dispatch as dispatch


class RightsExecutionBookingConversionTest(unittest.TestCase):
    @staticmethod
    def snapshot(*ids):
        return {
            "coverage": {"appointments": True},
            "operationalInventory": {
                "appointments": [{"appointmentId": value} for value in ids],
                "appointmentCountInWindow": len(ids),
            },
        }

    @staticmethod
    def receipt(store, evidence):
        row = {
            "store": store,
            "appointmentSetHash": "a" * 64,
            "appointmentCount": 1,
            "affectedRows": 1,
            "remainingActiveRows": 0,
            "evidenceHash": evidence,
        }
        if store == "booking_conversions":
            row["browserSyntheticCoverageComplete"] = False
        return row

    @staticmethod
    def payload():
        return {
            "id": "a" * 32,
            "subjectRef": "account:42",
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }

    def common_central(self):
        return mock.patch.object(
            dispatch.data_subject_rights,
            "execute",
            return_value={
                "ok": True,
                "adapter": "privacy_suppression",
                "requestType": "erasure",
            },
        )

    def test_erasure_stages_plan_records_completion_and_clears(self):
        payload = self.payload()
        review = self.receipt("review_followup", "b" * 64)
        booking = self.receipt("booking_conversions", "c" * 64)
        staged = {"appointmentIds": ("apt-1",), "appointmentSetHash": "a" * 64}
        completion = {"complete": True, "appointmentSetHash": "a" * 64}
        with (
            mock.patch.object(dispatch, "_provider_erasure_recovery_needed", return_value=True),
            self.common_central() as central,
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="a" * 32),
            mock.patch.object(dispatch.review_followup_privacy, "receipt", return_value=None),
            mock.patch.object(dispatch.booking_conversion_erasure, "receipt", return_value=None),
            mock.patch.object(dispatch.provider_erasure_completion, "status", return_value=None),
            mock.patch.object(dispatch.provider_erasure_plan, "load", return_value=None),
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot", return_value=self.snapshot("apt-1")) as snapshot,
            mock.patch.object(dispatch.provider_erasure_plan, "stage", return_value=staged) as stage,
            mock.patch.object(dispatch.review_followup_privacy, "erase_appointments", return_value=review) as erase_review,
            mock.patch.object(dispatch.booking_conversion_erasure, "erase_appointments", return_value=booking) as erase_booking,
            mock.patch.object(dispatch.provider_erasure_completion, "record", return_value=completion) as record,
            mock.patch.object(dispatch.provider_erasure_plan, "clear", return_value=True) as clear,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        self.assertTrue(central.call_args.kwargs["resume_completed_erasure"])
        snapshot.assert_called_once_with("account:42")
        stage.assert_called_once_with("a" * 32, "account:42", ("apt-1",))
        erase_review.assert_called_once_with("a" * 32, ("apt-1",))
        erase_booking.assert_called_once_with("a" * 32, ("apt-1",))
        record.assert_called_once_with(
            "a" * 32,
            review,
            booking,
            "compliance.sqlite3",
            subject_source="direct_mercure",
            provider_subject_ref="account:42",
        )
        clear.assert_called_once_with("a" * 32, "account:42", "a" * 64)
        self.assertTrue(result["providerErasurePlanCleared"])
        self.assertEqual(result["providerErasureCompletion"], completion)

    def test_existing_plan_skips_provider_reread_after_crash(self):
        payload = self.payload()
        review = self.receipt("review_followup", "b" * 64)
        booking = self.receipt("booking_conversions", "c" * 64)
        plan = {"appointmentIds": ("apt-first",), "appointmentSetHash": "a" * 64}
        with (
            mock.patch.object(dispatch, "_provider_erasure_recovery_needed", return_value=True),
            self.common_central(),
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="a" * 32),
            mock.patch.object(dispatch.review_followup_privacy, "receipt", return_value=None),
            mock.patch.object(dispatch.booking_conversion_erasure, "receipt", return_value=None),
            mock.patch.object(dispatch.provider_erasure_completion, "status", return_value=None),
            mock.patch.object(dispatch.provider_erasure_plan, "load", return_value=plan),
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot") as snapshot,
            mock.patch.object(dispatch.provider_erasure_plan, "stage") as stage,
            mock.patch.object(dispatch.review_followup_privacy, "erase_appointments", return_value=review) as erase_review,
            mock.patch.object(dispatch.booking_conversion_erasure, "erase_appointments", return_value=booking) as erase_booking,
            mock.patch.object(dispatch.provider_erasure_completion, "record", return_value={"appointmentSetHash": "a" * 64}),
            mock.patch.object(dispatch.provider_erasure_plan, "clear", return_value=True),
        ):
            dispatch.execute(payload, "compliance.sqlite3")

        snapshot.assert_not_called()
        stage.assert_not_called()
        erase_review.assert_called_once_with("a" * 32, ("apt-first",))
        erase_booking.assert_called_once_with("a" * 32, ("apt-first",))

    def test_existing_receipts_finish_completion_without_provider_read(self):
        payload = self.payload()
        review = self.receipt("review_followup", "b" * 64)
        booking = self.receipt("booking_conversions", "c" * 64)
        completion = {"complete": True, "appointmentSetHash": "a" * 64}
        with (
            mock.patch.object(dispatch, "_provider_erasure_recovery_needed", return_value=True),
            self.common_central(),
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="a" * 32),
            mock.patch.object(dispatch.review_followup_privacy, "receipt", return_value=review),
            mock.patch.object(dispatch.booking_conversion_erasure, "receipt", return_value=booking),
            mock.patch.object(dispatch.provider_erasure_completion, "status", return_value=None),
            mock.patch.object(dispatch.provider_erasure_plan, "load", return_value=None),
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot") as snapshot,
            mock.patch.object(dispatch.review_followup_privacy, "erase_appointments") as erase_review,
            mock.patch.object(dispatch.booking_conversion_erasure, "erase_appointments") as erase_booking,
            mock.patch.object(dispatch.provider_erasure_completion, "record", return_value=completion) as record,
            mock.patch.object(dispatch.provider_erasure_plan, "clear", return_value=True),
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        snapshot.assert_not_called()
        erase_review.assert_not_called()
        erase_booking.assert_not_called()
        record.assert_called_once_with(
            "a" * 32,
            review,
            booking,
            "compliance.sqlite3",
            subject_source="direct_mercure",
            provider_subject_ref="account:42",
        )
        self.assertEqual(result["providerErasureCompletion"], completion)

    def test_stale_plan_replays_even_after_completion_was_recorded(self):
        payload = self.payload()
        review = self.receipt("review_followup", "b" * 64)
        booking = self.receipt("booking_conversions", "c" * 64)
        plan = {"appointmentIds": ("apt-1",), "appointmentSetHash": "a" * 64}
        completion = {"complete": True, "appointmentSetHash": "a" * 64}
        with (
            mock.patch.object(dispatch, "_provider_erasure_recovery_needed", return_value=True),
            self.common_central(),
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="a" * 32),
            mock.patch.object(dispatch.review_followup_privacy, "receipt", return_value=review),
            mock.patch.object(dispatch.booking_conversion_erasure, "receipt", return_value=booking),
            mock.patch.object(dispatch.provider_erasure_completion, "status", return_value=completion),
            mock.patch.object(dispatch.provider_erasure_plan, "load", return_value=plan),
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot") as snapshot,
            mock.patch.object(dispatch.review_followup_privacy, "erase_appointments", return_value=review) as erase_review,
            mock.patch.object(dispatch.booking_conversion_erasure, "erase_appointments", return_value=booking) as erase_booking,
            mock.patch.object(dispatch.provider_erasure_completion, "record", return_value=completion) as record,
            mock.patch.object(dispatch.provider_erasure_plan, "clear", return_value=True) as clear,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        snapshot.assert_not_called()
        erase_review.assert_called_once_with("a" * 32, ("apt-1",))
        erase_booking.assert_called_once_with("a" * 32, ("apt-1",))
        record.assert_called_once_with(
            "a" * 32,
            review,
            booking,
            "compliance.sqlite3",
            subject_source="direct_mercure",
            provider_subject_ref="account:42",
        )
        clear.assert_called_once_with("a" * 32, "account:42", "a" * 64)
        self.assertTrue(result["providerErasurePlanCleared"])

    def test_incomplete_inventory_creates_no_plan_or_mutation(self):
        payload = self.payload()
        incomplete = {
            "coverage": {"appointments": False},
            "operationalInventory": {
                "appointments": [{"appointmentId": "apt-1"}],
                "appointmentCountInWindow": 1,
            },
        }
        with (
            mock.patch.object(dispatch, "_provider_erasure_recovery_needed", return_value=True),
            self.common_central(),
            mock.patch.object(dispatch.data_subject_rights, "_request_id", return_value="a" * 32),
            mock.patch.object(dispatch.review_followup_privacy, "receipt", return_value=None),
            mock.patch.object(dispatch.booking_conversion_erasure, "receipt", return_value=None),
            mock.patch.object(dispatch.provider_erasure_completion, "status", return_value=None),
            mock.patch.object(dispatch.provider_erasure_plan, "load", return_value=None),
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot", return_value=incomplete),
            mock.patch.object(dispatch.provider_erasure_plan, "stage") as stage,
            mock.patch.object(dispatch.review_followup_privacy, "erase_appointments") as erase_review,
            mock.patch.object(dispatch.booking_conversion_erasure, "erase_appointments") as erase_booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        stage.assert_not_called()
        erase_review.assert_not_called()
        erase_booking.assert_not_called()
        self.assertEqual(result["reviewFollowupErasure"]["reason"], "mercure_appointment_inventory_incomplete")
        self.assertEqual(result["bookingConversionErasure"]["reason"], "mercure_appointment_inventory_incomplete")

    def test_non_erasure_does_not_enter_provider_tail(self):
        payload = self.payload()
        payload["purpose"] = "direct_marketing"
        with (
            mock.patch.object(dispatch, "_provider_erasure_recovery_needed", return_value=False),
            mock.patch.object(
                dispatch.data_subject_rights,
                "execute",
                return_value={"ok": True, "adapter": "privacy_suppression", "requestType": "objection"},
            ),
            mock.patch.object(dispatch.provider_erasure_plan, "load") as plan,
            mock.patch.object(dispatch.mercure_rights, "contact_snapshot") as snapshot,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        plan.assert_not_called()
        snapshot.assert_not_called()
        self.assertNotIn("bookingConversionErasure", result)


if __name__ == "__main__":
    unittest.main()
