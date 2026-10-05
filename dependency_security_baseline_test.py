from pathlib import Path
import unittest

REQ=Path(__file__).resolve().parent/"requirements.txt"

class DependencySecurityBaselineTest(unittest.TestCase):
    def test_cryptography_uses_openssl_4_0_3_security_patch_wheels(self):
        text=REQ.read_text(encoding="utf-8")
        self.assertIn("cryptography==50.0.2",text)
        self.assertNotIn("cryptography==50.0.1",text)

if __name__=="__main__":
    unittest.main()
