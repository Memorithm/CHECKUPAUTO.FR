from pathlib import Path
import shutil
import subprocess
import unittest


class CustomerOIDCAdminFrontendTest(unittest.TestCase):
    def test_page_and_javascript_never_prefill_or_read_back_secrets(self):
        root=Path(__file__).parent
        html=(root/"admin/customers.html").read_text()
        js=(root/"admin/customers.js").read_text()
        self.assertIn("/admin/customers.html",html)
        self.assertIn("/api/admin/customers/oidc",js)
        self.assertIn("type='password'",js)
        self.assertIn("autocomplete='new-password'",js)
        self.assertIn("clientSecret",js)
        self.assertNotIn("data.clientSecret",js)
        self.assertNotIn("row.clientSecret",js)
        self.assertNotIn("console.log",js)
        self.assertIn(".value=''",js)
        self.assertIn("secrets ne sont jamais relus",js)
        self.assertNotIn("Microsoft",html)
        self.assertNotIn("microsoft",js)
        self.assertIn("new Set(['google','apple'])",js)

    @unittest.skipUnless(shutil.which("node"),"Node.js required")
    def test_javascript_parses(self):
        root=Path(__file__).parent
        result=subprocess.run(["node","--check",str(root/"admin/customers.js")],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_backoffice_links_customer_identity_page(self):
        root=Path(__file__).parent
        index=(root/"admin/index.html").read_text()
        self.assertIn('href="/admin/customers.html"',index)


if __name__=="__main__":
    unittest.main()
