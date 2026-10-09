import copy
import datetime as dt
import unittest
from unittest.mock import Mock, patch

import mercure_vl_live_slot_evidence as evidence


class LiveSlotEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.resource = {"id": 454, "extendedProps": {
            "typeVl": True, "typePl": False, "typeCl": False},
            "businessHours": [{"daysOfWeek": "[1]", "startTime": "09:00", "endTime": "13:00"},
                              {"daysOfWeek": [1], "startTime": "13:00", "endTime": "17:40"}]}
        self.raw = {"status": 200, "duree": 40, "message": {"donnees": [{
            "date": {"annee": "2026", "mois": {"numero": "10"}, "jour": "12"},
            "AM": {"creneaux": [{"heure": "12:40", "prix": 80}]},
            "PM": {"creneaux": []}}]}}
        self.kw = dict(service="technical", date="2026-10-12", time="12:40", line_id="454")

    def qualify(self, resources=None, raw=None, **overrides):
        return evidence.qualify(**(self.kw | overrides), resources=[self.resource] if resources is None else resources,
                                availability=self.raw if raw is None else raw)

    def test_single_vl_line_joins_live_slot_without_claiming_hold(self):
        result = self.qualify()
        self.assertEqual(result["lineId"], "454")
        self.assertEqual(result["priceCents"], 8000)
        self.assertTrue(result["slotAvailable"])
        self.assertFalse(result["slotHeld"])
        self.assertNotIn("bookingEnabled", result)

    def test_multiple_missing_or_malformed_resources_fail_closed(self):
        for resources in ([], [self.resource, copy.deepcopy(self.resource)], {}, None, [None]):
            with self.subTest(resources=resources), self.assertRaises(ValueError):
                evidence.qualify(**self.kw, resources=resources, availability=self.raw)

    def test_different_resource_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "line_mismatch"):
            self.qualify(line_id="455")

    def test_resource_must_be_exclusively_and_explicitly_vl(self):
        for field, value in (("typeVl", 1), ("typeVl", "true"), ("typePl", True), ("typeCl", None)):
            with self.subTest(field=field, value=value):
                resource = copy.deepcopy(self.resource)
                resource["extendedProps"][field] = value
                with self.assertRaisesRegex(ValueError, "exclusive_vl"):
                    self.qualify(resources=[resource])

    def test_full_duration_must_fit_opening_hours(self):
        resource = copy.deepcopy(self.resource)
        resource["businessHours"] = resource["businessHours"][:1]
        with self.assertRaisesRegex(ValueError, "outside_line_hours"):
            self.qualify(resources=[resource])

    def test_gap_between_periods_is_not_a_contiguous_opening(self):
        resource = copy.deepcopy(self.resource)
        resource["businessHours"][1]["startTime"] = "13:20"
        with self.assertRaisesRegex(ValueError, "outside_line_hours"):
            self.qualify(resources=[resource])

    def test_slot_on_another_weekday_is_not_qualified(self):
        with self.assertRaisesRegex(ValueError, "outside_line_hours"):
            self.qualify(date="2026-10-13")

    def test_ambiguous_slots_and_days_are_rejected(self):
        for duplicate_day in (False, True):
            raw = copy.deepcopy(self.raw)
            day = raw["message"]["donnees"][0]
            if duplicate_day:
                raw["message"]["donnees"].append(copy.deepcopy(day))
            else:
                day["PM"]["creneaux"] = copy.deepcopy(day["AM"]["creneaux"])
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                self.qualify(raw=raw)

    def test_absence_is_not_availability(self):
        self.raw["message"]["donnees"][0]["AM"]["creneaux"] = []
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.qualify()

    def test_duration_and_response_shape_are_verified(self):
        for key, value in (("status", "200"), ("status", True), ("duree", 20), ("duree", True), ("message", [])):
            raw = copy.deepcopy(self.raw)
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.qualify(raw=raw)

    def test_price_requires_finite_exact_cents(self):
        for value in (None, True, "NaN", "Infinity", -1, 80.001, {}, 10001):
            raw = copy.deepcopy(self.raw)
            raw["message"]["donnees"][0]["AM"]["creneaux"][0]["prix"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.qualify(raw=raw)

    def test_dates_and_times_are_canonical(self):
        for field, value in (("date", "20261012"), ("date", "2026-02-30"), ("time", "9:00"), ("time", "24:00")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.qualify(**{field: value})

    def test_loader_uses_fresh_availability_and_closes_session(self):
        session = Mock()
        response = session.get.return_value
        response.json.return_value = [self.resource]
        with patch.object(evidence.admin, "business_today", return_value=dt.date(2026, 10, 9)), \
             patch.object(evidence.admin, "_session", return_value=session), \
             patch.object(evidence.admin, "_check_auth", side_effect=lambda response: response), \
             patch.object(evidence.public, "_provider_availability", return_value=self.raw) as fresh, \
             patch.object(evidence.public, "availability") as cached:
            result = evidence.load(**self.kw)
        self.assertTrue(result["slotAvailable"])
        fresh.assert_called_once_with("1763", "2026-10-12")
        cached.assert_not_called()
        session.post.assert_not_called()
        session.close.assert_called_once()
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_transport_failure_has_no_fallback_to_cache(self):
        session = Mock()
        session.get.side_effect = TimeoutError
        with patch.object(evidence.admin, "business_today", return_value=dt.date(2026, 10, 9)), \
             patch.object(evidence.admin, "_session", return_value=session), \
             patch.object(evidence.public, "availability") as cached:
            with self.assertRaises(TimeoutError):
                evidence.load(**self.kw)
        cached.assert_not_called()
        session.close.assert_called_once()
