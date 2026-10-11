import os
import unittest
from unittest.mock import patch

import mercure_vl_notification_config as config
import mercure_vl_provider_writer_factory as factory
from mercure_booking_write_contract import BookingWriteRequest
from mercure_vl_write_payload import MercureVlWritePayloadError, build

APPOINTMENT = {"nom": "Test", "prenom": "Client", "email": "client@example.invalid",
               "telephone": "0102030405", "marque": "132", "modele": "42", "energie": "2",
               "immatriculation": "AB-123-CD", "date": "2026-10-14T09:00"}
METADATA = {"service_id": "1763", "duration": "40", "centre_type": "1",
            "line_id": "454", "operator_id": "464"}
OBSERVED = {"prestation": ["1763"], "duree": ["40"], "centre_type": ["1"],
            "ligne_id": ["454"], "utilisateur": ["464"]}


class FakeResponse:
    status_code = 200

    def json(self):
        return {"id": "9001"}


class RecordingSession:
    def __init__(self):
        self.posts = []

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, dict(data)))
        return FakeResponse()


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in config.SWITCHES}


class NotificationConfigTest(unittest.TestCase):
    def test_unset_switches_add_nothing(self):
        self.assertEqual(config.load({}), {})
        self.assertEqual(config.load({name: "" for name in config.SWITCHES}), {})

    def test_exact_true_false_values_map_to_mercure_fields(self):
        env = {"CHECKUPAUTO_MERCURE_NOTIFY_EMAIL_CONFIRMATION": "true",
               "CHECKUPAUTO_MERCURE_NOTIFY_SMS_CONFIRMATION": "false",
               "CHECKUPAUTO_MERCURE_NOTIFY_SMS_REMINDER": "true"}
        self.assertEqual(config.load(env), {"email_confirmation_vl": "true",
                                            "envoi_sms_vl": "false", "rappel_sms_vl": "true"})

    def test_ambiguous_values_are_configuration_errors(self):
        for value in ("1", "yes", "TRUE", "on", " true"):
            with self.subTest(value=value):
                with self.assertRaises(config.MercureNotificationConfigError):
                    config.load({"CHECKUPAUTO_MERCURE_NOTIFY_SMS_REMINDER": value})


class PayloadNotificationTest(unittest.TestCase):
    def test_default_payload_is_unchanged(self):
        self.assertEqual(build(appointment=APPOINTMENT, **METADATA),
                         build(appointment=APPOINTMENT, notifications=None, **METADATA))
        self.assertTrue(config.FIELDS.isdisjoint(build(appointment=APPOINTMENT, **METADATA)))

    def test_configured_fields_are_added(self):
        payload = build(appointment=APPOINTMENT, notifications={"envoi_sms_vl": "false"}, **METADATA)
        self.assertEqual(payload["envoi_sms_vl"], "false")
        self.assertNotIn("email_confirmation_vl", payload)

    def test_unknown_fields_cannot_be_injected(self):
        for value in ({"commentaire": "x"}, {"envoi_sms_vl": "maybe"}, ["envoi_sms_vl"]):
            with self.subTest(value=value):
                with self.assertRaises(MercureVlWritePayloadError):
                    build(appointment=APPOINTMENT, notifications=value, **METADATA)


class FactoryWiringTest(unittest.TestCase):
    def make(self, env):
        session = RecordingSession()
        with patch.dict(os.environ, env, clear=True), \
                patch.object(factory.mercure, "_session", return_value=session):
            writer = factory.create(appointment=APPOINTMENT, metadata=METADATA,
                                    observed_metadata=OBSERVED,
                                    expected_service_label="TOUT VEHICULE", authorized=True)
        return writer, session

    def request(self):
        return BookingWriteRequest(request_key="k" * 24, account_id="a", vehicle_id="v",
                                   service="technical", date="2026-10-14", time="09:00",
                                   price_cents=8000)

    def test_posted_form_reflects_configuration_only(self):
        writer, session = self.make({**clean_env(),
                                     "CHECKUPAUTO_MERCURE_NOTIFY_EMAIL_CONFIRMATION": "false",
                                     "CHECKUPAUTO_MERCURE_NOTIFY_SMS_REMINDER": "false"})
        writer.create_once(self.request())
        url, data = session.posts[0]
        self.assertTrue(url.endswith("/admin/rendez_vous_add"))
        self.assertEqual(data["email_confirmation_vl"], "false")
        self.assertEqual(data["rappel_sms_vl"], "false")
        self.assertNotIn("envoi_sms_vl", data)

    def test_default_environment_posts_the_previous_form(self):
        writer, session = self.make(clean_env())
        writer.create_once(self.request())
        self.assertEqual(session.posts[0][1], build(appointment=APPOINTMENT, **METADATA))

    def test_invalid_configuration_refuses_before_opening_a_session(self):
        with patch.dict(os.environ, {**clean_env(),
                                     "CHECKUPAUTO_MERCURE_NOTIFY_SMS_CONFIRMATION": "oui"}, clear=True), \
                patch.object(factory.mercure, "_session") as session:
            with self.assertRaisesRegex(factory.MercureVlWriterFactoryError, "notification"):
                factory.create(appointment=APPOINTMENT, metadata=METADATA,
                               observed_metadata=OBSERVED,
                               expected_service_label="TOUT VEHICULE", authorized=True)
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
