import io
import json
import unittest
from unittest import mock

import marketing_campaign_cli


class MarketingCampaignCliTest(unittest.TestCase):
    def test_status_returns_only_campaign_capability_and_bounded_run_evidence(self):
        output = io.StringIO()
        with mock.patch.object(
            marketing_campaign_cli.marketing_campaigns,
            "capability",
            return_value={"bound": True, "rawRecipientsPersisted": False},
        ), mock.patch.object(
            marketing_campaign_cli.marketing_campaigns,
            "recent_runs",
            return_value=[{"runId": "a" * 32, "deliveredCount": 4}],
        ):
            code = marketing_campaign_cli.main(["status"], stdin=io.StringIO(""), stdout=output)
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["capability"]["bound"])
        self.assertEqual(payload["recentRuns"][0]["deliveredCount"], 4)

    def test_email_command_passes_raw_targets_only_to_campaign_facade_and_never_echoes_them(self):
        raw_recipient = "private.person@example.test"
        raw_content = "Contenu commercial confidentiel"
        request = {
            "recipients": [raw_recipient],
            "subject": "Offre consentie",
            "text": raw_content,
            "html": "<p>" + raw_content + "</p>",
            "reference": "campaign-2026-09",
        }
        output = io.StringIO()
        safe_run = {
            "runId": "b" * 32,
            "channel": "email",
            "referenceHash": "c" * 64,
            "contentHash": "d" * 64,
            "audienceCount": 1,
            "attemptedCount": 1,
            "deliveredCount": 1,
            "blockedCount": 0,
            "failedCount": 0,
            "pendingCount": 0,
            "status": "completed",
        }
        with mock.patch.object(
            marketing_campaign_cli.marketing_campaigns,
            "run_email_campaign",
            return_value=safe_run,
        ) as run:
            code = marketing_campaign_cli.main(
                ["email"],
                stdin=io.StringIO(json.dumps(request)),
                stdout=output,
            )
        self.assertEqual(code, 0)
        run.assert_called_once_with(
            [raw_recipient],
            "Offre consentie",
            raw_content,
            "<p>" + raw_content + "</p>",
            reference="campaign-2026-09",
        )
        rendered = output.getvalue()
        self.assertNotIn(raw_recipient, rendered)
        self.assertNotIn(raw_content, rendered)
        self.assertEqual(json.loads(rendered)["run"]["status"], "completed")

    def test_push_command_uses_installation_ids_and_does_not_accept_apns_token_field(self):
        installation = "12345678-1234-4234-8234-1234567890ab"
        request = {
            "installationIds": [installation],
            "apnsToken": "aa" * 32,
            "title": "CheckupAuto",
            "body": "Votre contrôle approche",
            "reference": "push-1",
            "data": {"route": "/vehicles"},
        }
        output = io.StringIO()
        with mock.patch.object(
            marketing_campaign_cli.marketing_campaigns,
            "run_push_campaign",
            return_value={"runId": "e" * 32, "status": "completed"},
        ) as run:
            code = marketing_campaign_cli.main(
                ["push"],
                stdin=io.StringIO(json.dumps(request)),
                stdout=output,
            )
        self.assertEqual(code, 0)
        run.assert_called_once_with(
            [installation],
            "CheckupAuto",
            "Votre contrôle approche",
            reference="push-1",
            data={"route": "/vehicles"},
        )
        self.assertNotIn(request["apnsToken"], output.getvalue())

    def test_invalid_json_is_sanitized_and_never_echoed(self):
        output = io.StringIO()
        secret = "PRIVATE-SENTINEL"
        code = marketing_campaign_cli.main(
            ["email"],
            stdin=io.StringIO('{"secret":"' + secret),
            stdout=output,
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"ok": False, "error": "invalid_or_unauthorized_request"},
        )
        self.assertNotIn(secret, output.getvalue())

    def test_oversized_input_is_rejected_before_campaign_execution(self):
        output = io.StringIO()
        oversized = "x" * (marketing_campaign_cli.MAX_STDIN_BYTES + 1)
        with mock.patch.object(
            marketing_campaign_cli.marketing_campaigns,
            "run_email_campaign",
        ) as run:
            code = marketing_campaign_cli.main(
                ["email"], stdin=io.StringIO(oversized), stdout=output
            )
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_internal_errors_are_not_disclosed(self):
        output = io.StringIO()
        request = {
            "recipients": ["a@example.test"],
            "subject": "Offre",
            "text": "Texte",
            "reference": "campaign",
        }
        with mock.patch.object(
            marketing_campaign_cli.marketing_campaigns,
            "run_email_campaign",
            side_effect=RuntimeError("database path /private/secret.sqlite3"),
        ):
            code = marketing_campaign_cli.main(
                ["email"], stdin=io.StringIO(json.dumps(request)), stdout=output
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "error": "internal_error"})
        self.assertNotIn("secret.sqlite3", output.getvalue())

    def test_unknown_command_is_rejected_without_consuming_stdin(self):
        output = io.StringIO()
        stream = io.StringIO("sensitive payload")
        code = marketing_campaign_cli.main(["sms"], stdin=stream, stdout=output)
        self.assertEqual(code, 2)
        self.assertEqual(stream.tell(), 0)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "error": "usage"})


if __name__ == "__main__":
    unittest.main()
