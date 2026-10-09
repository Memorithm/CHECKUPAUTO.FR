import unittest
from mercure_vl_slot_line_qualification import qualify

class Tests(unittest.TestCase):
    def setUp(self):
        self.event={"start":"2026-10-14T09:00:00+02:00","resourceId":"454",
                    "extendedProps":{"centreTypeId":1,"ligneId":454}}

    def test_matching_event_is_not_availability(self):
        result=qualify(events=[self.event],line_id="454",date="2026-10-14",time="09:00")
        self.assertTrue(result["observed"])
        self.assertFalse(result["slotAvailable"])

    def test_wrong_line_rejected(self):
        with self.assertRaises(ValueError):
            qualify(events=[self.event],line_id="455",date="2026-10-14",time="09:00")

    def test_duplicate_evidence_rejected(self):
        with self.assertRaises(ValueError):
            qualify(events=[self.event,self.event],line_id="454",date="2026-10-14",time="09:00")
