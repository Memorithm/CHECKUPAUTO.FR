import unittest
from unittest.mock import Mock, patch

import mercure_admin_client as mercure

ENV = {mercure.USERNAME_ENV: "compte-dedie", mercure.PASSWORD_ENV: "mot-de-passe-secret"}


class MercureSessionRenewalTest(unittest.TestCase):
    def setUp(self):
        mercure._RENEW_LAST_ATTEMPT = None

    def tearDown(self):
        mercure._RENEW_LAST_ATTEMPT = None

    def test_without_environment_credentials_nothing_is_attempted(self):
        login = Mock()
        result = mercure.renew_session_from_environment({}, login_fn=login)
        self.assertEqual(result, {"renewed": False, "state": "renewal_not_configured"})
        login.assert_not_called()

    def test_renewal_uses_environment_and_never_exposes_credentials(self):
        login = Mock(return_value={"connected": True})
        result = mercure.renew_session_from_environment(ENV, now=1000.0, login_fn=login)
        login.assert_called_once_with("compte-dedie", "mot-de-passe-secret")
        self.assertEqual(result, {"renewed": True, "state": "renewed"})
        self.assertNotIn("mot-de-passe-secret", repr(result))
        self.assertNotIn("compte-dedie", repr(result))

    def test_attempts_are_throttled_to_protect_the_account(self):
        login = Mock(side_effect=PermissionError("Connexion Mercure refusée"))
        first = mercure.renew_session_from_environment(ENV, now=1000.0, login_fn=login)
        second = mercure.renew_session_from_environment(ENV, now=1000.0 + 60, login_fn=login)
        third = mercure.renew_session_from_environment(
            ENV, now=1000.0 + mercure.RENEW_MIN_INTERVAL_SECONDS + 1, login_fn=login)
        self.assertEqual(first["state"], "renewal_refused")
        self.assertEqual(second["state"], "renewal_throttled")
        self.assertEqual(third["state"], "renewal_refused")
        self.assertEqual(login.call_count, 2)

    def test_expired_session_is_renewed_then_rechecked(self):
        checks = [mercure.MercureSessionError("Session Mercure expirée"),
                  {"connected": True, "status": 200, "state": "ready"}]

        def check():
            value = checks.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        with patch.object(mercure, "_check_session", side_effect=check), \
             patch.object(mercure, "renew_session_from_environment",
                          return_value={"renewed": True, "state": "renewed"}) as renew:
            result = mercure.session_status()
        renew.assert_called_once_with()
        self.assertTrue(result["connected"])
        self.assertTrue(result["renewed"])

    def test_refused_renewal_is_reported_without_details(self):
        with patch.object(mercure, "_check_session",
                          side_effect=mercure.MercureSessionError("Session Mercure expirée")), \
             patch.object(mercure, "renew_session_from_environment",
                          return_value={"renewed": False, "state": "renewal_refused"}):
            result = mercure.session_status()
        self.assertEqual(result, {"connected": False, "state": "renewal_refused",
                                  "error": "Session Mercure indisponible"})

    def test_network_failures_do_not_trigger_a_login(self):
        import requests
        with patch.object(mercure, "_check_session", side_effect=requests.Timeout("x")), \
             patch.object(mercure, "renew_session_from_environment") as renew:
            result = mercure.session_status()
        renew.assert_not_called()
        self.assertEqual(result["state"], "timeout")

    def test_renewal_can_be_disabled_by_caller(self):
        with patch.object(mercure, "_check_session",
                          side_effect=mercure.MercureSessionError("Session Mercure expirée")), \
             patch.object(mercure, "renew_session_from_environment") as renew:
            result = mercure.session_status(renew=False)
        renew.assert_not_called()
        self.assertEqual(result["state"], "session_unavailable")


if __name__ == "__main__":
    unittest.main()
