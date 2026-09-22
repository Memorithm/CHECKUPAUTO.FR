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


if __name__ == '__main__':
    unittest.main()
