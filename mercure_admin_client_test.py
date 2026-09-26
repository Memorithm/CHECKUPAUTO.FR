import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import mercure_admin_client as mercure


class MercureSchemaTest(unittest.TestCase):
    def test_login_preserves_existing_session_file_owner(self):
        with tempfile.TemporaryDirectory() as td:
            session_file = Path(td) / "mercure-admin-session.json"
            session_file.write_text('{"cookies":{"old":"cookie"}}\n')
            st = session_file.stat()
            browser = Mock()
            first = Mock(text='<input name="_csrf_token" value="csrf-123">')
            first.raise_for_status.return_value = None
            second = Mock(status_code=302, headers={"Location": "/admin/calendrier"})
            jar = requests.cookies.RequestsCookieJar(); jar.set("PHPSESSID", "cookie-123")
            browser.get.return_value = first; browser.post.return_value = second; browser.cookies = jar
            with patch.object(mercure, "SESSION_FILE", session_file), \
                 patch.object(mercure.requests, "Session", return_value=browser), \
                 patch.object(mercure.os, "chown") as chown:
                result = mercure.login("user", "password")
            self.assertTrue(result["connected"])
            chown.assert_called_once_with(session_file.with_suffix(".tmp"), st.st_uid, st.st_gid)
            self.assertEqual(session_file.stat().st_mode & 0o777, 0o600)

    @patch.object(mercure, "_session")
    @patch.object(mercure, "_appointments")
    @patch.object(mercure, "_calendar_events")
    def test_review_email_comes_from_calendar_extended_props(self, events, appointments, session):
        session.return_value = Mock()
        appointments.return_value = [{"id": 42, "date_rdv": "2026-09-19 10:00:00", "est_honore": 1, "name": "Client"}]
        events.return_value = [{
            "id": 42,
            "backgroundColor": "#cccccc",
            "extendedProps": {"rendezVousId": 42, "email": "client@example.fr"},
        }]
        rows = mercure.review_followup_rows(2)
        self.assertEqual(rows[0]["email"], "client@example.fr")
        self.assertTrue(rows[0]["finished"])

    @patch.object(mercure, "_session")
    @patch.object(mercure, "_calendar_events")
    @patch.object(mercure, "vehicle_details")
    def test_reminder_source_uses_verified_vehicle_due_date(self, vehicle, events, session):
        session.return_value = Mock()
        events.return_value = [{
            "extendedProps": {
                "rendezVousId": 77,
                "clientCompteId": "12",
                "clientLibreId": "",
                "vehiculeId": ["99"],
            },
        }]
        vehicle.return_value = {"date_echeance": "2026-11-18"}
        rows = mercure.reminder_source_rows("2026-09-01", "2026-09-20")
        self.assertEqual(rows, [{
            "vehicleId": "99", "clientKind": "account", "clientId": "12",
            "dueDate": "2026-11-18", "appointmentId": "77",
        }])


    @patch.object(mercure, "_session")
    @patch.object(mercure, "_calendar_events")
    @patch("mercure_public_client.service")
    def test_synthetic_creation_verification_failure_best_effort_removes_created_slot(self, service, events, session):
        service.return_value={"duration":75,"id":"11"}
        browser=Mock()
        created=Mock(status_code=200,text="")
        created.raise_for_status.return_value=None
        created.json.return_value={"id":"RDV-TEST-987"}
        removed=Mock(status_code=200,text="")
        browser.post.side_effect=[created,removed]
        session.return_value=browser
        events.side_effect=RuntimeError("calendar temporarily unavailable")

        with self.assertRaisesRegex(RuntimeError,"calendar temporarily unavailable"):
            mercure.create_synthetic_test_appointment("technical","2026-10-03","15:00")

        self.assertEqual(browser.post.call_count,2)
        cleanup=browser.post.call_args_list[1]
        self.assertEqual(cleanup.args[0],mercure.BASE+"/admin/rendez_vous_remove")
        self.assertEqual(cleanup.kwargs["data"],{"rendezvous_id":"RDV-TEST-987"})

    @patch.object(mercure, "_session")
    @patch.object(mercure, "_calendar_events")
    @patch("mercure_public_client.service")
    def test_synthetic_creation_missing_calendar_event_also_removes_created_slot(self, service, events, session):
        service.return_value={"duration":75,"id":"11"}
        browser=Mock()
        created=Mock(status_code=200,text="")
        created.raise_for_status.return_value=None
        created.json.return_value={"id":"RDV-TEST-654"}
        removed=Mock(status_code=200,text="")
        browser.post.side_effect=[created,removed]
        session.return_value=browser
        events.return_value=[]

        with self.assertRaisesRegex(RuntimeError,"non retrouvé"):
            mercure.create_synthetic_test_appointment("technical","2026-10-03","15:40")

        self.assertEqual(browser.post.call_count,2)
        self.assertEqual(
            browser.post.call_args_list[1].kwargs["data"],
            {"rendezvous_id":"RDV-TEST-654"},
        )

    @patch.object(mercure, "_session", side_effect=RuntimeError("client@example.fr bearer_secret=SUPER-SECRET-VALUE"))
    def test_session_status_redacts_unexpected_exception_text(self, _session):
        result = mercure.session_status()
        self.assertFalse(result["connected"])
        self.assertEqual(result["state"], "unexpected_error")
        self.assertEqual(result["error"], "Session Mercure indisponible")
        exposed = repr(result)
        self.assertNotIn("client@example.fr", exposed)
        self.assertNotIn("SUPER-SECRET-VALUE", exposed)

    @patch.object(mercure, "_session", side_effect=requests.Timeout("https://mercure.invalid/?token=SECRET"))
    def test_session_status_reports_bounded_timeout_state(self, _session):
        result = mercure.session_status()
        self.assertFalse(result["connected"])
        self.assertEqual(result["state"], "timeout")
        self.assertEqual(result["error"], "Session Mercure indisponible")
        self.assertNotIn("SECRET", repr(result))


    @patch.object(mercure, "_session")
    @patch.object(mercure, "_calendar_events")
    @patch.object(mercure, "_appointments")
    def test_upcoming_mobile_control_appointments_require_exact_provider_join(self, appointments, events, session):
        session.return_value = Mock()
        appointments.return_value = [
            {"id": 77, "date_rdv": "2026-10-04 14:30:00", "prestation": "Contrôle technique"},
            {"id": 78, "date_rdv": "2026-10-04 15:00:00", "prestation": "Visite pollution"},
        ]
        events.return_value = [
            {"id": 77, "extendedProps": {
                "rendezVousId": 77, "clientCompteId": "12", "clientLibreId": "", "vehiculeId": ["99"]
            }},
            {"id": 78, "extendedProps": {
                "rendezVousId": 78, "clientCompteId": "12", "clientLibreId": "", "vehiculeId": ["99"]
            }},
            {"id": 999, "extendedProps": {
                "rendezVousId": 999, "clientCompteId": "12", "clientLibreId": "", "vehiculeId": ["99"]
            }},
        ]
        rows = mercure.upcoming_control_appointments("2026-10-01", "2026-10-10")
        self.assertEqual(rows, [{
            "vehicleId": "99",
            "clientKind": "account",
            "clientId": "12",
            "appointmentId": "77",
            "appointmentAt": "2026-10-04T14:30:00+02:00",
        }])

    def test_upcoming_mobile_control_window_is_bounded(self):
        with self.assertRaises(ValueError):
            mercure.upcoming_control_appointments("2026-01-01", "2026-08-01")


if __name__ == "__main__":
    unittest.main()
