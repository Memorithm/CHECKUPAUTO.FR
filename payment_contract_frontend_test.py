from pathlib import Path
import shutil
import subprocess
import unittest


class PaymentContractFrontendTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for syntax validation')
    def test_payment_editor_javascript_parses(self):
        result = subprocess.run(
            ['node', '--check', str(Path(__file__).parent / 'admin/payments.js')],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refund_ui_is_explicitly_sandbox_and_preserves_idempotency_key(self):
        root = Path(__file__).parent
        html = (root / 'admin/payments.html').read_text()
        js = (root / 'admin/payments.js').read_text()
        self.assertIn('SANDBOX · AUCUN REMBOURSEMENT LIVE', html)
        self.assertIn('/api/admin/payments/refunds', js)
        self.assertIn('crypto.getRandomValues', js)
        self.assertIn('refund_reconciliation_required', js)
        self.assertIn("data.capability?.authoritativeRefundBalances!==true", js)
        self.assertIn("data.capability?.liveRefundsEnabled!==false", js)
        self.assertIn("refundSnapshot?.balances||[]", js)
        self.assertNotIn('transactionId', html)
        self.assertNotIn('transactionId', js)


if __name__ == '__main__':
    unittest.main()
