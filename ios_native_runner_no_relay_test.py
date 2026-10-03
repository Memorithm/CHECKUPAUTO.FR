from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class NativeRunnerNoRelayTest(unittest.TestCase):
 def test_ios_ci_is_native_mac_only(self):
  text=(ROOT/".github/workflows/ios-core-ci.yml").read_text()
  self.assertIn("runs-on: [self-hosted, macOS, ARM64, checkupauto, ios]",text)
  for forbidden in ("ssh ","scp ","CHECKUPAUTO_MAC_SSH_KEY","remoteops_thor"):
   self.assertNotIn(forbidden,text)
if __name__=="__main__": unittest.main()
