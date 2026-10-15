"""Contract: the public Mercure planning never exposes Sunday or closed dates."""

import unittest

import mercure_public_client as mercure


def provider_day(day, weekday, slots, *, month="10"):
    return {
        "date": {
            "annee": 2026,
            "mois": {"numero": month, "nom": "octobre"},
            "jour": day,
            "dow": weekday,
        },
        "AM": {"creneaux": slots},
        "PM": {"creneaux": []},
    }


class MercurePublicOpenDaysTest(unittest.TestCase):
    def test_sunday_and_days_without_slots_are_excluded_at_source(self):
        slot = {"heure": "09:00", "prix": "80"}
        raw = {"tarif": "80", "message": {"donnees": [
            provider_day("17", "samedi", [slot]),
            provider_day("18", "lundi", [slot]),  # False weekday label cannot open Sunday.
            provider_day("19", "lundi", []),  # Closed / no available slots in Mercure.
            provider_day("20", "mardi", [slot]),
            provider_day("32", "mercredi", [slot]),  # Invalid provider calendar date.
        ]}}
        result = mercure._normalize_availability(
            "technical", mercure.SERVICES["technical"], "2026-10-15", raw,
        )
        self.assertEqual([day["date"] for day in result["days"]],
                         ["2026-10-17", "2026-10-20"])
        self.assertTrue(all(day["available"] and day["slots"]
                            for day in result["days"]))

    def test_short_numeric_provider_dates_are_canonical_iso_dates(self):
        slot = {"heure": "09:00", "prix": "80"}
        raw = {"tarif": "80", "message": {"donnees": [
            provider_day("7", "mercredi", [slot]),
        ]}}
        result = mercure._normalize_availability(
            "technical", mercure.SERVICES["technical"], "2026-10-01", raw,
        )
        self.assertEqual(result["days"][0]["date"], "2026-10-07")

    def test_all_closed_days_produce_empty_list(self):
        raw = {"tarif": "80", "message": {"donnees": [
            provider_day("18", "dimanche", [{"heure": "09:00", "prix": "80"}]),
            provider_day("19", "lundi", []),
        ]}}
        result = mercure._normalize_availability(
            "technical", mercure.SERVICES["technical"], "2026-10-18", raw,
        )
        self.assertEqual(result["days"], [])


if __name__ == "__main__":
    unittest.main()
