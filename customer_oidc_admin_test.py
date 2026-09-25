import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import customer_oidc_admin as admin


class CustomerOIDCAdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"private"/"customer"/"oidc.json"
        self.env=patch.dict(os.environ,{"CYBERCHECK_CUSTOMER_OIDC_CONFIG_PATH":str(self.path)},clear=False)
        self.env.start();self.addCleanup(self.env.stop)

    def test_save_is_private_preserves_other_provider_and_never_returns_secret(self):
        first=admin.save("google","google-client","google-secret-value","https://stage.example")
        second=admin.save("microsoft","ms-client","microsoft-secret","https://stage.example")
        self.assertTrue(first["configured"])
        self.assertTrue(second["configured"])
        self.assertFalse(first["secretsReadable"])
        self.assertNotIn("google-secret-value",repr(first))
        self.assertNotIn("google-client",repr(first))
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777,0o700)
        doc=json.loads(self.path.read_text())
        self.assertEqual(set(doc["providers"]),{"google","microsoft"})
        self.assertEqual(doc["providers"]["google"]["clientSecret"],"google-secret-value")

    def test_remove_one_provider_keeps_others(self):
        admin.save("google","google-client","google-secret-value","https://stage.example")
        admin.save("apple","apple-service-id","apple-secret-jwt-value","https://stage.example")
        removed=admin.remove("google","https://stage.example")
        self.assertTrue(removed["removed"])
        self.assertFalse(removed["configured"])
        doc=json.loads(self.path.read_text())
        self.assertEqual(set(doc["providers"]),{"apple"})
        self.assertNotIn("apple-secret-jwt-value",repr(removed))

    def test_symlink_target_is_rejected(self):
        self.path.parent.mkdir(parents=True)
        target=Path(self.tmp.name)/"real.json";target.write_text('{"providers":{}}')
        self.path.symlink_to(target)
        with self.assertRaisesRegex(admin.CustomerOIDCAdminError,"^customer_oidc_admin_target_invalid$"):
            admin.save("google","client-id","secret-value","https://stage.example")

    def test_invalid_provider_and_short_secret_fail_before_write(self):
        with self.assertRaisesRegex(admin.CustomerOIDCAdminError,"^customer_oidc_admin_provider_invalid$"):
            admin.save("unknown","client","secret-value","https://stage.example")
        with self.assertRaisesRegex(admin.CustomerOIDCAdminError,"^customer_oidc_admin_client_secret_invalid$"):
            admin.save("google","client","tiny","https://stage.example")
        self.assertFalse(self.path.exists())

    def test_status_contains_callbacks_but_no_client_values(self):
        admin.save("google","google-client","google-secret-value","https://stage.example")
        status=admin.status("https://stage.example")
        google=next(row for row in status["providers"] if row["id"]=="google")
        self.assertTrue(google["configured"])
        self.assertEqual(google["callbackUrl"],"https://stage.example/auth/customer/google/callback")
        self.assertNotIn("google-client",repr(status))
        self.assertNotIn("google-secret-value",repr(status))


if __name__=="__main__":
    unittest.main()
