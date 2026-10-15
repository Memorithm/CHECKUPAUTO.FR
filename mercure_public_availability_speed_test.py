import threading
import time
import unittest
from unittest.mock import Mock, patch

import mercure_admin_client
import mercure_public_client as mercure

RAW = {"status": 200, "tarif": "80", "message": {"donnees": [
    {"date": {"annee": 2026, "mois": {"numero": "10", "nom": "octobre"}, "jour": "20", "dow": "mardi"},
     "AM": {"creneaux": [{"heure": "09:00", "prix": "80"}]}, "PM": {"creneaux": []}}]}}


def _browser(payload=RAW):
    response = Mock(status_code=200)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    browser = Mock()
    browser.post.return_value = response
    return browser


class AvailabilitySpeedTest(unittest.TestCase):
    def setUp(self):
        self._today = patch.object(mercure_admin_client, "business_today",
                                   return_value=__import__("datetime").date(2026, 10, 15))
        self._today.start()
        self.reset()

    def tearDown(self):
        self._today.stop()
        self.reset()

    def reset(self):
        with mercure._CACHE_LOCK:
            mercure._CACHE.clear()
            mercure._SESSION_POOL.clear()
            mercure._REFRESHING.clear()
        mercure._breaker_success()

    def test_session_is_reused_between_reads(self):
        browser = _browser()
        with patch.object(mercure, "_provider_session", return_value=browser) as opened:
            mercure._provider_availability("1763", "2026-10-20")
            mercure._provider_availability("1763", "2026-10-27")
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(browser.post.call_count, 2)
        browser.close.assert_not_called()

    def test_expired_reused_session_is_retried_once_with_a_fresh_one(self):
        stale = _browser({"status": 500})
        fresh = _browser()
        stale._checkupauto_opened_at = time.monotonic()
        mercure._SESSION_POOL.append((stale._checkupauto_opened_at, stale))
        with patch.object(mercure, "_provider_session", return_value=fresh) as opened:
            data = mercure._provider_availability("1763", "2026-10-20")
        self.assertEqual(data["status"], 200)
        self.assertEqual(opened.call_count, 1)
        stale.close.assert_called_once_with()

    def test_fresh_session_failure_is_not_retried(self):
        broken = _browser({"status": 500})
        with patch.object(mercure, "_provider_session", return_value=broken) as opened:
            with self.assertRaises(RuntimeError):
                mercure._provider_availability("1763", "2026-10-20")
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(mercure._SESSION_POOL, [])

    def test_old_session_is_not_reused(self):
        old = _browser()
        mercure._SESSION_POOL.append((time.monotonic() - mercure.SESSION_REUSE_SECONDS - 1, old))
        with patch.object(mercure, "_provider_session", return_value=_browser()) as opened:
            mercure._provider_availability("1763", "2026-10-20")
        self.assertEqual(opened.call_count, 1)
        old.close.assert_called_once_with()

    def test_display_gets_stale_list_at_once_and_refreshes_behind(self):
        with patch.object(mercure, "_provider_availability", return_value=RAW):
            first = mercure.availability("technical", "2026-10-20")
        with mercure._CACHE_LOCK:
            mercure._CACHE[("technical", "2026-10-20")] = (time.monotonic() - 60, first)
        done = threading.Event()

        def slow(*_):
            done.wait(5)
            return RAW
        with patch.object(mercure, "_provider_availability", side_effect=slow) as provider:
            shown = mercure.availability("technical", "2026-10-20", allow_stale=True)
            self.assertIs(shown, first)
            done.set()
            for _ in range(100):
                with mercure._CACHE_LOCK:
                    if not mercure._REFRESHING:
                        break
                time.sleep(0.01)
        self.assertEqual(provider.call_count, 1)
        with mercure._CACHE_LOCK:
            age = time.monotonic() - mercure._CACHE[("technical", "2026-10-20")][0]
        self.assertLess(age, mercure.CACHE_TTL)

    def test_booking_checks_never_use_a_stale_list(self):
        with patch.object(mercure, "_provider_availability", return_value=RAW):
            first = mercure.availability("technical", "2026-10-20")
        with mercure._CACHE_LOCK:
            mercure._CACHE[("technical", "2026-10-20")] = (time.monotonic() - 60, first)
        with patch.object(mercure, "_provider_availability", return_value=RAW) as provider:
            fresh = mercure.availability("technical", "2026-10-20")
        self.assertIsNot(fresh, first)
        self.assertEqual(provider.call_count, 1)

    def test_too_old_list_is_never_shown(self):
        with patch.object(mercure, "_provider_availability", return_value=RAW):
            first = mercure.availability("technical", "2026-10-20")
        with mercure._CACHE_LOCK:
            mercure._CACHE[("technical", "2026-10-20")] = (time.monotonic() - mercure.STALE_TTL - 1, first)
        with patch.object(mercure, "_provider_availability", return_value=RAW) as provider:
            shown = mercure.availability("technical", "2026-10-20", allow_stale=True)
        self.assertIsNot(shown, first)
        self.assertEqual(provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
