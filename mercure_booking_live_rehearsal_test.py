import os
import unittest
from unittest.mock import patch

import mercure_booking_live_rehearsal as rehearsal


class MercureLiveRehearsalTest(unittest.TestCase):
    def test_live_writes_are_disabled_by_default(self):
        with patch.dict(os.environ,{},clear=True), patch.object(rehearsal.booking_test,"create_session") as create:
            with self.assertRaises(PermissionError):
                rehearsal.rehearse("technical","2026-10-13","09:40")
            create.assert_not_called()

    def test_verified_creation_is_always_removed(self):
        with patch.dict(os.environ,{"CHECKUPAUTO_LIVE_BOOKING_REHEARSAL":"I_ACCEPT_TEMPORARY_MERCURE_APPOINTMENT"}), \
             patch.object(rehearsal.booking_test,"create_session",return_value={"token":"fake"}), \
             patch.object(rehearsal.booking_test,"create_appointment",return_value={"providerVerified":True}), \
             patch.object(rehearsal.booking_test,"remove_appointment",return_value={"providerVerified":True}) as remove:
            result=rehearsal.rehearse("technical","2026-10-13","09:40")
        self.assertTrue(result["createdAndReread"])
        self.assertTrue(result["removedAndReread"])
        remove.assert_called_once_with("fake")

    def test_failed_cleanup_never_reports_success(self):
        with patch.dict(os.environ,{"CHECKUPAUTO_LIVE_BOOKING_REHEARSAL":"I_ACCEPT_TEMPORARY_MERCURE_APPOINTMENT"}), \
             patch.object(rehearsal.booking_test,"create_session",return_value={"token":"fake"}), \
             patch.object(rehearsal.booking_test,"create_appointment",return_value={"providerVerified":True}), \
             patch.object(rehearsal.booking_test,"remove_appointment",side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                rehearsal.rehearse("technical","2026-10-13","09:40")


if __name__=="__main__":
    unittest.main()
