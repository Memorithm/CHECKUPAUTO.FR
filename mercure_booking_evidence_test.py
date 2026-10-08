import unittest
from unittest.mock import patch

import mercure_booking_evidence as evidence


class MercureBookingEvidenceTest(unittest.TestCase):
    def verify(self, events):
        with patch.object(evidence.mercure,"_session",return_value=object()), \
             patch.object(evidence.mercure,"_calendar_events",return_value=events):
            return evidence.verify_appointment(
                provider_reference="mercure-123",date="2026-10-15",time="10:30")

    def test_exact_authoritative_event_matches_expected_local_slot(self):
        self.assertTrue(self.verify([{"id":"mercure-123","start":"2026-10-15T10:30:00+02:00"}]))
        self.assertTrue(self.verify([{"id":"mercure-123","start":"2026-10-15T08:30:00Z"}]))

    def test_missing_duplicate_or_wrong_slot_is_not_confirmed(self):
        for events in (
            [], [{"id":"other","start":"2026-10-15T10:30:00+02:00"}],
            [{"id":"mercure-123","start":"2026-10-15T11:00:00+02:00"}],
            [{"id":"mercure-123","start":"bad"}],
            [{"id":"mercure-123","start":"2026-10-15T10:30:00+02:00"}]*2,
        ):
            with self.subTest(events=events):
                self.assertFalse(self.verify(events))

    def test_cancelled_event_is_never_confirmed(self):
        for event in (
            {"id":"mercure-123","start":"2026-10-15T10:30:00+02:00","status":"cancelled"},
            {"id":"mercure-123","start":"2026-10-15T10:30:00+02:00","extendedProps":{"cancelled":True}},
        ):
            with self.subTest(event=event):
                self.assertFalse(self.verify([event]))

    def test_malformed_calendar_is_rejected(self):
        with patch.object(evidence.mercure,"_session",return_value=object()), \
             patch.object(evidence.mercure,"_calendar_events",return_value={"events":[]}):
            with self.assertRaisesRegex(evidence.MercureBookingEvidenceError,"mercure_calendar_invalid"):
                evidence.verify_appointment(provider_reference="mercure-123",
                                            date="2026-10-15",time="10:30")
        with self.assertRaisesRegex(evidence.MercureBookingEvidenceError,"mercure_calendar_invalid"):
            self.verify([{"id":"mercure-123","start":"2026-10-15T10:30:00+02:00",
                          "extendedProps":"invalid"}])

    def test_provider_failure_cannot_be_interpreted_as_confirmation(self):
        with patch.object(evidence.mercure,"_session",side_effect=TimeoutError):
            with self.assertRaisesRegex(evidence.MercureBookingEvidenceError,"mercure_calendar_unavailable"):
                evidence.verify_appointment(
                    provider_reference="mercure-123",date="2026-10-15",time="10:30")

    def test_invalid_reference_is_rejected_before_provider_access(self):
        with patch.object(evidence.mercure,"_session") as session:
            with self.assertRaisesRegex(evidence.MercureBookingEvidenceError,"mercure_reference_invalid"):
                evidence.verify_appointment(provider_reference="../bad",date="2026-10-15",time="10:30")
            session.assert_not_called()


if __name__=="__main__":
    unittest.main()
