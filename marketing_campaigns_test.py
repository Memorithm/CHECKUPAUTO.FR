import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_store
import marketing_campaigns


class MarketingCampaignsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        compliance_store.init_db(self.db)

    @staticmethod
    def _sent():
        return {
            "ok": True,
            "delivery": {
                "status": "sent",
                "alreadySent": False,
                "inFlight": False,
                "deferred": False,
            },
        }

    @staticmethod
    def _deferred():
        return {
            "ok": False,
            "delivery": {
                "status": "failed",
                "alreadySent": False,
                "inFlight": False,
                "deferred": True,
            },
        }

    def test_email_campaign_routes_every_target_through_consent_gated_facade(self):
        outcomes = [
            self._sent(),
            PermissionError("explicit_consent_missing"),
            RuntimeError("provider secret detail"),
            self._deferred(),
        ]
        recipients = [
            "ALICE@example.test",
            "bob@example.test",
            "carol@example.test",
            "dave@example.test",
        ]
        with mock.patch.object(
            marketing_campaigns.marketing_delivery,
            "send_email",
            side_effect=outcomes,
        ) as send:
            result = marketing_campaigns.run_email_campaign(
                recipients,
                "Contrôle technique",
                "Votre offre consentie.",
                "<p>Votre offre consentie.</p>",
                reference="campaign-autumn-2026",
                db_path=self.db,
            )

        self.assertEqual(send.call_count, 4)
        self.assertEqual(send.call_args_list[0].args[0], "alice@example.test")
        for call in send.call_args_list:
            self.assertEqual(call.kwargs["reference"], "campaign-autumn-2026")
            self.assertEqual(call.kwargs["consent_db_path"], self.db)
        self.assertEqual(result["audienceCount"], 4)
        self.assertEqual(result["attemptedCount"], 4)
        self.assertEqual(result["deliveredCount"], 1)
        self.assertEqual(result["blockedCount"], 1)
        self.assertEqual(result["failedCount"], 1)
        self.assertEqual(result["pendingCount"], 1)
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("provider secret detail", repr(result))

    def test_campaign_audit_persists_only_hashes_counts_and_timestamps(self):
        recipient = "private.person@example.test"
        subject = "Message marketing privé"
        body = "Contenu marketing qui ne doit pas être persisté."
        reference = "raw-campaign-reference"
        with mock.patch.object(
            marketing_campaigns.marketing_delivery,
            "send_email",
            return_value=self._sent(),
        ):
            result = marketing_campaigns.run_email_campaign(
                [recipient],
                subject,
                body,
                reference=reference,
                db_path=self.db,
            )

        with compliance_store.connect(self.db) as db:
            row = db.execute(
                "SELECT * FROM marketing_campaign_run WHERE run_id=?",
                (result["runId"],),
            ).fetchone()
            columns = [item[1] for item in db.execute("PRAGMA table_info(marketing_campaign_run)")]
        persisted = repr(dict(row))
        self.assertNotIn(recipient, persisted)
        self.assertNotIn(subject, persisted)
        self.assertNotIn(body, persisted)
        self.assertNotIn(reference, persisted)
        self.assertNotIn("recipient", " ".join(columns).lower())
        self.assertNotIn("subject", " ".join(columns).lower())
        self.assertEqual(len(result["referenceHash"]), 64)
        self.assertEqual(len(result["contentHash"]), 64)

    def test_email_campaign_deduplicates_case_insensitively(self):
        with mock.patch.object(
            marketing_campaigns.marketing_delivery,
            "send_email",
            return_value=self._sent(),
        ) as send:
            result = marketing_campaigns.run_email_campaign(
                ["Alice@Example.test", "alice@example.test"],
                "Info",
                "Contenu de campagne.",
                reference="dedupe",
                db_path=self.db,
            )
        self.assertEqual(send.call_count, 1)
        self.assertEqual(result["audienceCount"], 1)
        self.assertEqual(result["deliveredCount"], 1)
        self.assertEqual(result["status"], "completed")

    def test_invalid_email_rejects_entire_campaign_before_any_send(self):
        with mock.patch.object(marketing_campaigns.marketing_delivery, "send_email") as send:
            with self.assertRaises(ValueError):
                marketing_campaigns.run_email_campaign(
                    ["valid@example.test", "invalid-address"],
                    "Info",
                    "Contenu de campagne.",
                    reference="invalid-audience",
                    db_path=self.db,
                )
        send.assert_not_called()
        self.assertEqual(marketing_campaigns.recent_runs(self.db), [])

    def test_push_campaign_uses_installation_ids_not_apns_tokens(self):
        installation_a = "12345678-1234-4234-8234-1234567890ab"
        installation_b = "22345678-1234-4234-8234-1234567890ab"
        with mock.patch.object(
            marketing_campaigns.marketing_delivery,
            "send_push",
            return_value=self._sent(),
        ) as send:
            result = marketing_campaigns.run_push_campaign(
                [installation_a, installation_b],
                "CheckupAuto",
                "Votre contrôle approche.",
                reference="push-campaign-1",
                data={"route": "/vehicles"},
                db_path=self.db,
            )
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args[0], installation_a)
        self.assertEqual(send.call_args_list[1].args[0], installation_b)
        self.assertEqual(result["deliveredCount"], 2)
        self.assertEqual(result["status"], "completed")

    def test_all_missing_consents_produce_blocked_run_without_leaking_reason(self):
        with mock.patch.object(
            marketing_campaigns.marketing_delivery,
            "send_email",
            side_effect=PermissionError("privacy_suppressed private detail"),
        ):
            result = marketing_campaigns.run_email_campaign(
                ["a@example.test", "b@example.test"],
                "Info",
                "Contenu de campagne.",
                reference="blocked-run",
                db_path=self.db,
            )
        self.assertEqual(result["blockedCount"], 2)
        self.assertEqual(result["deliveredCount"], 0)
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("private detail", repr(result))

    def test_audience_limit_fails_closed_before_delivery(self):
        recipients = [f"user{i}@example.test" for i in range(marketing_campaigns.MAX_AUDIENCE + 1)]
        with mock.patch.object(marketing_campaigns.marketing_delivery, "send_email") as send:
            with self.assertRaises(ValueError):
                marketing_campaigns.run_email_campaign(
                    recipients,
                    "Info",
                    "Contenu de campagne.",
                    reference="too-large",
                    db_path=self.db,
                )
        send.assert_not_called()

    def test_capability_exposes_privacy_and_transport_boundaries(self):
        state = marketing_campaigns.capability(self.db)
        self.assertTrue(state["bound"])
        self.assertEqual(state["channels"], ["email", "push"])
        self.assertFalse(state["smsConfigured"])
        self.assertFalse(state["phoneConfigured"])
        self.assertTrue(state["consentGateRequiredPerRecipient"])
        self.assertFalse(state["rawRecipientsPersisted"])
        self.assertFalse(state["rawContentPersisted"])
        self.assertEqual(state["deliveryFacade"], "marketing_delivery")


if __name__ == "__main__":
    unittest.main()
