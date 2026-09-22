import io
import json
import unittest
from unittest.mock import patch

import data_subject_rights_cli as cli


class DataSubjectRectificationCliTest(unittest.TestCase):
    @patch.object(cli.rights_rectification, "execute")
    def test_rectification_uses_stdin_and_projects_sensitive_result(self, execute):
        installation_id = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        deadline_id = "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca"
        execute.return_value = {
            "ok": True,
            "requestId": "a" * 32,
            "requestType": "rectification",
            "adapter": "mobile_deadline_rectification",
            "field": "device_deadline_due_date",
            "source": "device",
            "updated": True,
            "executionId": "b" * 32,
            "requestStatus": "in_progress",
            "requestComplete": False,
            "installationId": installation_id,
            "deadlineId": deadline_id,
            "dueDate": "2027-02-20",
        }
        payload = {
            "requestId": "a" * 32,
            "installationId": installation_id,
            "correction": {"deadlineId": deadline_id, "dueDate": "2027-02-20"},
        }
        stdout = io.StringIO()
        code = cli.main(
            ["rectify-mobile-deadline"],
            stdin=io.StringIO(json.dumps(payload)),
            stdout=stdout,
        )
        self.assertEqual(code, 0)
        execute.assert_called_once_with(
            payload["requestId"],
            installation_id,
            payload["correction"],
        )
        output = stdout.getvalue()
        result = json.loads(output)
        self.assertTrue(result["updated"])
        self.assertEqual(result["source"], "device")
        self.assertNotIn(installation_id, output)
        self.assertNotIn(deadline_id, output)
        self.assertNotIn("2027-02-20", output)
        self.assertNotIn(payload["requestId"], output)

    @patch.object(cli.rights_rectification, "execute")
    def test_rectification_error_is_sanitized(self, execute):
        secret_marker = "sensitive-deadline-value"
        execute.side_effect = PermissionError(secret_marker)
        stdout = io.StringIO()
        code = cli.main(
            ["rectify-mobile-deadline"],
            stdin=io.StringIO(json.dumps({
                "requestId": "a" * 32,
                "installationId": "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
                "correction": {
                    "deadlineId": "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca",
                    "dueDate": "2027-02-20",
                },
            })),
            stdout=stdout,
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"ok": False, "error": "invalid_or_unauthorized_request"},
        )
        self.assertNotIn(secret_marker, stdout.getvalue())

    def test_status_declares_rectification_as_partial(self):
        stdout = io.StringIO()
        code = cli.main(["status"], stdin=io.StringIO(), stdout=stdout)
        self.assertEqual(code, 0)
        state = json.loads(stdout.getvalue())["capability"]["rectification"]
        self.assertTrue(state["partial"])
        self.assertFalse(state["bound"])
        self.assertFalse(state["authoritativeSourcesMutable"])


if __name__ == "__main__":
    unittest.main()
