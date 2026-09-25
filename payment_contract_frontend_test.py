from pathlib import Path
import shutil
import subprocess
import unittest


class PaymentContractFrontendTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for syntax validation')
    def test_refund_operation_surface_is_absent(self):
        root = Path(__file__).parent
        html = (root / 'admin/payments.html').read_text()
        js = (root / 'admin/payments.js').read_text()
        self.assertNotIn('/api/admin/payments/refunds', js)
        self.assertNotIn('refundForm', html)
        self.assertNotIn('refundSubmit', js)
        self.assertIn('formulaire de contact', html)

    def test_payline_sandbox_secret_form_never_prefills_or_reads_back_access_key(self):
        root = Path(__file__).parent
        html = (root / 'admin/payments.html').read_text()
        js = (root / 'admin/payments.js').read_text()
        self.assertIn('id="paylineAccessKey"', html)
        self.assertIn('type="password"', html)
        self.assertIn('autocomplete="new-password"', html)
        self.assertIn('/api/admin/payments/payline-sandbox', js)
        self.assertIn("$('#paylineAccessKey').value=''", js)
        self.assertNotIn('data.status.accessKey', js)
        self.assertNotIn('data.accessKey', js)
        self.assertNotIn('console.log', js)

    def test_payment_editor_javascript_parses(self):
        result = subprocess.run(
            ['node', '--check', str(Path(__file__).parent / 'admin/payments.js')],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
