import unittest
from unittest.mock import patch

import deployment_admin
from admin_http_test_support import AdminHttpHarness


class DeploymentSourceRouteTest(unittest.TestCase):
    """S-14: POST saves the update source, DELETE removes its token."""

    @classmethod
    def setUpClass(cls):
        cls.http = AdminHttpHarness()

    @classmethod
    def tearDownClass(cls):
        cls.http.close()

    def test_post_saves_source_and_never_deletes_token(self):
        payload = {"repository": "Memorithm/CHECKUPAUTO.FR", "branch": "main", "token": "x" * 40}
        with patch.object(deployment_admin, "save_update_source", return_value={"ok": True, "saved": True}) as save, \
             patch.object(deployment_admin, "delete_update_source_token") as delete:
            status, body, _ = self.http.request("POST", "/api/admin/deployment/source", payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"ok": True, "saved": True})
        save.assert_called_once_with(payload)
        delete.assert_not_called()

    def test_post_invalid_source_is_rejected_without_side_effect(self):
        with patch.object(deployment_admin, "save_update_source", side_effect=ValueError("bad")), \
             patch.object(deployment_admin, "delete_update_source_token") as delete:
            status, body, _ = self.http.request("POST", "/api/admin/deployment/source", {"repository": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "deployment_source_invalid")
        delete.assert_not_called()

    def test_delete_removes_token(self):
        with patch.object(deployment_admin, "delete_update_source_token", return_value={"ok": True, "deleted": True}) as delete, \
             patch.object(deployment_admin, "save_update_source") as save:
            status, body, _ = self.http.request("DELETE", "/api/admin/deployment/source")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"ok": True, "deleted": True})
        delete.assert_called_once_with()
        save.assert_not_called()

    def test_routes_still_require_admin_authentication(self):
        with patch.object(deployment_admin, "delete_update_source_token") as delete:
            status, _, _ = self.http.request("DELETE", "/api/admin/deployment/source", auth=False)
        self.assertEqual(status, 401)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
