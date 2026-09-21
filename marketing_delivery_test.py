import unittest
from unittest import mock

import marketing_delivery


class MarketingDeliveryTest(unittest.TestCase):
    def test_email_denial_happens_before_broker_send(self):
        with mock.patch.object(
            marketing_delivery.marketing_consent,
            "require_authorized",
            side_effect=PermissionError("explicit_consent_missing"),
        ) as authorize, mock.patch.object(
            marketing_delivery.notification_broker, "send_email"
        ) as send:
            with self.assertRaises(PermissionError):
                marketing_delivery.send_email(
                    "client@example.test",
                    "Offre Checkup Auto",
                    "Message",
                    reference="campaign-2026-09",
                )

        authorize.assert_called_once_with("email", "client@example.test", db_path=None)
        send.assert_not_called()

    def test_authorized_email_uses_dedicated_marketing_category(self):
        authorization = {
            "authorized": True,
            "reason": "explicit_consent",
            "consentId": "consent-1",
            "statementVersion": "1.0",
            "statementHash": "a" * 64,
            "validUntil": "",
        }
        delivery = {
            "ok": True,
            "channel": "email",
            "category": marketing_delivery.EMAIL_CATEGORY,
            "reference": "campaign-1",
            "status": "sent",
        }
        with mock.patch.object(
            marketing_delivery.marketing_consent,
            "require_authorized",
            return_value=authorization,
        ), mock.patch.object(
            marketing_delivery.notification_broker,
            "send_email",
            return_value=delivery,
        ) as send:
            result = marketing_delivery.send_email(
                "client@example.test",
                "Offre Checkup Auto",
                "Message texte",
                "<p>Message</p>",
                reference="campaign-1",
            )

        send.assert_called_once_with(
            "client@example.test",
            "Offre Checkup Auto",
            "Message texte",
            "<p>Message</p>",
            category="marketing_email",
            reference="campaign-1",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["consent"]["consentId"], "consent-1")
        self.assertNotIn("recipient", result)

    def test_push_denial_happens_before_token_lookup(self):
        installation = "4a8c91bf-58e0-4bd3-8b43-7fd77303d20f"
        with mock.patch.object(
            marketing_delivery.marketing_consent,
            "require_authorized",
            side_effect=PermissionError("explicit_consent_missing"),
        ), mock.patch.object(marketing_delivery, "_active_push_target") as target, mock.patch.object(
            marketing_delivery.notification_broker, "send_push"
        ) as send:
            with self.assertRaises(PermissionError):
                marketing_delivery.send_push(
                    installation,
                    "Offre",
                    "Message",
                    reference="push-campaign-1",
                )

        target.assert_not_called()
        send.assert_not_called()

    def test_authorized_push_resolves_token_from_mobile_registry(self):
        installation = "4a8c91bf-58e0-4bd3-8b43-7fd77303d20f"
        token = "ab" * 32
        authorization = {
            "authorized": True,
            "reason": "explicit_consent",
            "consentId": "consent-push",
            "statementVersion": "2.0",
            "statementHash": "b" * 64,
            "validUntil": "",
        }
        delivery = {
            "ok": True,
            "channel": "push",
            "category": marketing_delivery.PUSH_CATEGORY,
            "reference": "push-campaign-1",
            "status": "sent",
        }
        with mock.patch.object(
            marketing_delivery.marketing_consent,
            "require_authorized",
            return_value=authorization,
        ) as authorize, mock.patch.object(
            marketing_delivery,
            "_active_push_target",
            return_value=(token, "production"),
        ) as target, mock.patch.object(
            marketing_delivery.notification_broker,
            "send_push",
            return_value=delivery,
        ) as send:
            result = marketing_delivery.send_push(
                installation,
                "Rappel offre",
                "Offre réservée aux abonnés consentants",
                reference="push-campaign-1",
                data={"screen": "offers"},
            )

        authorize.assert_called_once_with("push", installation, db_path=None)
        target.assert_called_once_with(installation)
        send.assert_called_once_with(
            token,
            "Rappel offre",
            "Offre réservée aux abonnés consentants",
            category="marketing_push",
            reference="push-campaign-1",
            data={"screen": "offers"},
            environment="production",
        )
        self.assertTrue(result["ok"])
        self.assertNotIn(token, str(result))

    def test_active_push_target_fails_closed_for_disabled_installation(self):
        db = mock.MagicMock()
        db.execute.return_value.fetchone.return_value = {
            "device_token": "ab" * 32,
            "environment": "production",
            "disabled_at": "2026-09-21T20:00:00+00:00",
        }
        context = mock.MagicMock()
        context.__enter__.return_value = db
        context.__exit__.return_value = False
        with mock.patch.object(marketing_delivery.mobile_devices, "init_db"), mock.patch.object(
            marketing_delivery.mobile_devices, "connect", return_value=context
        ):
            with self.assertRaises(PermissionError):
                marketing_delivery._active_push_target(
                    "4a8c91bf-58e0-4bd3-8b43-7fd77303d20f"
                )

    def test_reference_is_required_and_bounded(self):
        with self.assertRaises(ValueError):
            marketing_delivery.send_email(
                "client@example.test", "Sujet", "Texte", reference=""
            )
        with self.assertRaises(ValueError):
            marketing_delivery.send_email(
                "client@example.test", "Sujet", "Texte", reference="x" * 161
            )

    def test_unimplemented_marketing_transports_fail_closed(self):
        with self.assertRaises(NotImplementedError):
            marketing_delivery.send_sms()
        with self.assertRaises(NotImplementedError):
            marketing_delivery.call_phone()


if __name__ == "__main__":
    unittest.main()
