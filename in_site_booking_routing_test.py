import unittest
from unittest.mock import patch

import booking_health
import in_site_booking_routing as routing

ON = {"CHECKUPAUTO_IN_SITE_BOOKING_ENABLED": "true"}
VEHICLE = {"vehicleId": "00000000-0000-4000-8000-0000000000aa"}
SERVICE = routing.mercure_public_client.SERVICES["technical"]["label"]


def decide(environ, **overrides):
    args = dict(service_label=SERVICE, preferred_date="2026-12-15", preferred_time="09:00",
                vehicle=VEHICLE, environ=environ, session_checker=lambda: True)
    args.update(overrides)
    return routing.decide(**args)


class RoutingTest(unittest.TestCase):
    def setUp(self):
        booking_health._reset_for_tests()

    def test_flag_off_is_delegated_without_any_check(self):
        with patch.object(routing.in_site_booking_readiness, "public_status", side_effect=AssertionError), \
                patch.object(booking_health, "session_status", side_effect=AssertionError), \
                patch.object(booking_health, "record_route", side_effect=AssertionError):
            for env in ({}, {"CHECKUPAUTO_IN_SITE_BOOKING_ENABLED": "1"},
                        {"CHECKUPAUTO_IN_SITE_BOOKING_ENABLED": "TRUE"}):
                self.assertEqual(decide(env), {"mode": "delegated", "reason": "in_site_flag_off"})

    def test_flag_on_without_signoff_or_write_config_is_delegated(self):
        # Real readiness evaluation: no write config, no sign-off evidence.
        self.assertEqual(decide(ON)["reason"], "readiness_closed")
        self.assertEqual(booking_health.snapshot()["fallbackReasons"], {"readiness_closed": 1})

    def test_each_prerequisite_falls_back(self):
        ready = patch.object(routing.in_site_booking_readiness, "public_status", return_value={"bookingEnabled": True})
        with ready:
            self.assertEqual(decide(ON, service_label="Contre-visite")["reason"], "service_not_supported")
            self.assertEqual(decide(ON, preferred_date="")["reason"], "slot_missing")
            self.assertEqual(decide(ON, preferred_time="9h")["reason"], "slot_missing")
            self.assertEqual(decide(ON, preferred_date="2026-02-30")["reason"], "slot_missing")
            self.assertEqual(decide(ON, vehicle={})["reason"], "vehicle_missing")
            with patch.object(booking_health, "session_status", return_value={"connected": False}):
                self.assertEqual(decide(ON)["reason"], "mercure_session_invalid")
            with patch.object(booking_health, "session_status", side_effect=RuntimeError):
                self.assertEqual(decide(ON)["reason"], "routing_error")
            with patch.object(booking_health, "session_status", return_value={"connected": True}):
                self.assertEqual(decide(ON), {"mode": "in_site", "reason": "", "service": "technical",
                                              "checkout": "site"})
        self.assertEqual(booking_health.snapshot()["routes"]["in_site"], 1)

    def test_mercure_hosted_checkout_skips_site_writer_readiness_but_not_session(self):
        hosted = {**ON, "CHECKUPAUTO_MERCURE_HOSTED_PAYMENT_ENABLED": "true"}
        with patch.object(routing.in_site_booking_readiness, "public_status", side_effect=AssertionError):
            with patch.object(booking_health, "session_status", return_value={"connected": True}):
                self.assertEqual(decide(hosted), {"mode": "in_site", "reason": "", "service": "technical",
                                                  "checkout": "mercure-hosted"})
            with patch.object(booking_health, "session_status", return_value={"connected": False}):
                self.assertEqual(decide(hosted)["reason"], "mercure_session_invalid")
        # The hosted flag alone never opens the on-site journey.
        self.assertEqual(decide({"CHECKUPAUTO_MERCURE_HOSTED_PAYMENT_ENABLED": "true"})["reason"],
                         "in_site_flag_off")

    def test_service_key_matches_exact_labels_only(self):
        self.assertEqual(routing.service_key(SERVICE.upper()), "technical")
        self.assertEqual(routing.service_key(routing.mercure_public_client.SERVICES["fitted"]["label"]), "fitted")
        self.assertEqual(routing.service_key(""), "")


if __name__ == "__main__":
    unittest.main()
