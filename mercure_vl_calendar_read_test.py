import unittest
from unittest.mock import patch
import mercure_vl_calendar_read as reader

class Tests(unittest.TestCase):
    def test_exact_reference(self):
        with patch.object(reader.mercure,"_session",return_value=object()),patch.object(reader.mercure,"_calendar_events",return_value=[{"id":"abc"}]),patch.object(reader.mercure,"_event_id",side_effect=lambda x:x["id"]):
            result=reader.read_reference(reference="abc",date="2026-10-14")
        self.assertTrue(result["calendarRead"])
        self.assertFalse(result["customerIdentityVerified"])

    def test_missing_reference(self):
        with patch.object(reader.mercure,"_session",return_value=object()),patch.object(reader.mercure,"_calendar_events",return_value=[]):
            with self.assertRaises(ValueError):
                reader.read_reference(reference="abc",date="2026-10-14")
