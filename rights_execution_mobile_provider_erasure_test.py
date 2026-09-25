import unittest
from unittest import mock

import rights_execution_dispatch as dispatch


class RightsExecutionMobileProviderErasureTest(unittest.TestCase):
    INSTALLATION = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"

    @staticmethod
    def binding(client_kind="account", client_id="client-42", vehicle_id="vehicle-1"):
        return {
            "binding_id": "binding-1",
            "installation_id": RightsExecutionMobileProviderErasureTest.INSTALLATION,
            "vehicle_id": vehicle_id,
            "client_kind": client_kind,
            "client_id": client_id,
        }

    @staticmethod
    def snapshot(*appointment_ids):
        return {
            "coverage": {"appointments": True},
            "operationalInventory": {
                "appointments": [
                    {"appointmentId": appointment_id}
                    for appointment_id in appointment_ids
                ],
                "appointmentCountInWindow": len(appointment_ids),
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

    def test_direct_mercure_subject_bypasses_mobile_lookup(self):
        with mock.patch.object(
            dispatch.mobile_devices,
            "registered_vehicle_bindings",
        ) as bindings:
            provider_ref, reason = dispatch._provider_erasure_subject_ref(
                "account:client-42"
            )
        self.assertEqual(provider_ref, "account:client-42")
        self.assertEqual(reason, "")
        bindings.assert_not_called()

    def test_mobile_installation_resolves_one_verified_provider_subject(self):
        with mock.patch.object(
            dispatch.mobile_devices,
            "registered_vehicle_bindings",
            return_value=[
                self.binding(vehicle_id="vehicle-1"),
                self.binding(vehicle_id="vehicle-2"),
            ],
        ):
            provider_ref, reason = dispatch._provider_erasure_subject_ref(
                self.INSTALLATION
            )
        self.assertEqual(provider_ref, "account:client-42")
        self.assertEqual(reason, "")

    def test_mobile_installation_without_binding_fails_closed(self):
        with mock.patch.object(
            dispatch.mobile_devices,
            "registered_vehicle_bindings",
            return_value=[],
        ):
            provider_ref, reason = dispatch._provider_erasure_subject_ref(
                self.INSTALLATION
            )
        self.assertIsNone(provider_ref)
        self.assertEqual(reason, "mercure_subject_binding_missing")

    def test_multiple_provider_subjects_are_ambiguous(self):
        with mock.patch.object(
            dispatch.mobile_devices,
            "registered_vehicle_bindings",
            return_value=[
                self.binding(client_id="client-42"),
                self.binding(client_id="client-99", vehicle_id="vehicle-2"),
            ],
        ):
            provider_ref, reason = dispatch._provider_erasure_subject_ref(
                self.INSTALLATION
            )
        self.assertIsNone(provider_ref)
        self.assertEqual(reason, "mercure_subject_binding_ambiguous")

    def test_invalid_provider_binding_fails_closed(self):
        with mock.patch.object(
            dispatch.mobile_devices,
            "registered_vehicle_bindings",
            return_value=[self.binding(client_kind="unexpected")],
        ):
            provider_ref, reason = dispatch._provider_erasure_subject_ref(
                self.INSTALLATION
            )
        self.assertIsNone(provider_ref)
        self.assertEqual(reason, "mercure_subject_binding_invalid")

    def test_binding_store_failure_fails_closed(self):
        with mock.patch.object(
            dispatch.mobile_devices,
            "registered_vehicle_bindings",
            side_effect=RuntimeError("mobile store unavailable"),
        ):
            provider_ref, reason = dispatch._provider_erasure_subject_ref(
                self.INSTALLATION
            )
        self.assertIsNone(provider_ref)
        self.assertEqual(reason, "mercure_subject_binding_unavailable")

    def test_mobile_erasure_uses_bound_provider_ref_for_provider_tail(self):
        payload = {
            "id": "a" * 32,
            "subjectRef": self.INSTALLATION,
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        review = self.receipt("review_followup", "b" * 64)
        booking = self.receipt("booking_conversions", "c" * 64)
        completion = {"complete": True, "appointmentSetHash": "a" * 64}
        staged = {
            "appointmentIds": ("apt-1",),
            "appointmentSetHash": "a" * 64,
        }
        with (
            mock.patch.object(
                dispatch,
                "_provider_erasure_recovery_needed",
                return_value=True,
            ),
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
                return_value="a" * 32,
            ),
            mock.patch.object(
                dispatch.mobile_devices,
                "registered_vehicle_bindings",
                return_value=[self.binding()],
            ) as bindings,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "receipt",
                return_value=None,
            ),
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "receipt",
                return_value=None,
            ),
            mock.patch.object(
                dispatch.provider_erasure_completion,
                "status",
                return_value=None,
            ),
            mock.patch.object(
                dispatch.provider_erasure_plan,
                "load",
                return_value=None,
            ),
            mock.patch.object(
                dispatch.mercure_rights,
                "contact_snapshot",
                return_value=self.snapshot("apt-1"),
            ) as snapshot,
            mock.patch.object(
                dispatch.provider_erasure_plan,
                "stage",
                return_value=staged,
            ) as stage,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_appointments",
                return_value=review,
            ),
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_appointments",
                return_value=booking,
            ),
            mock.patch.object(
                dispatch.provider_erasure_completion,
                "record",
                return_value=completion,
            ),
            mock.patch.object(
                dispatch.provider_erasure_plan,
                "clear",
                return_value=True,
            ) as clear,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        bindings.assert_called_once_with(self.INSTALLATION)
        snapshot.assert_called_once_with("account:client-42")
        stage.assert_called_once_with(
            "a" * 32,
            "account:client-42",
            ("apt-1",),
        )
        clear.assert_called_once_with(
            "a" * 32,
            "account:client-42",
            "a" * 64,
        )
        self.assertTrue(result["reviewFollowupErasure"]["executed"])
        self.assertTrue(result["bookingConversionErasure"]["executed"])

    def test_ambiguous_mobile_binding_mutates_no_provider_store(self):
        payload = {
            "id": "b" * 32,
            "subjectRef": self.INSTALLATION,
            "adapter": "privacy_suppression",
            "purpose": "all_processing",
        }
        with (
            mock.patch.object(
                dispatch,
                "_provider_erasure_recovery_needed",
                return_value=False,
            ),
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
                return_value="b" * 32,
            ),
            mock.patch.object(
                dispatch.mobile_devices,
                "registered_vehicle_bindings",
                return_value=[
                    self.binding(client_id="client-42"),
                    self.binding(client_id="client-99", vehicle_id="vehicle-2"),
                ],
            ),
            mock.patch.object(
                dispatch.mercure_rights,
                "contact_snapshot",
            ) as snapshot,
            mock.patch.object(
                dispatch.review_followup_privacy,
                "erase_appointments",
            ) as erase_review,
            mock.patch.object(
                dispatch.booking_conversion_erasure,
                "erase_appointments",
            ) as erase_booking,
        ):
            result = dispatch.execute(payload, "compliance.sqlite3")

        snapshot.assert_not_called()
        erase_review.assert_not_called()
        erase_booking.assert_not_called()
        self.assertEqual(
            result["reviewFollowupErasure"]["reason"],
            "mercure_subject_binding_ambiguous",
        )
        self.assertEqual(
            result["bookingConversionErasure"]["reason"],
            "mercure_subject_binding_ambiguous",
        )


if __name__ == "__main__":
    unittest.main()
