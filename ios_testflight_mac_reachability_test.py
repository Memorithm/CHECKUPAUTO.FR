"""Exercise the TestFlight SSH endpoint resolver without touching a real host."""
from pathlib import Path
import os
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parent / ".github" / "workflows" / "ios-testflight.yml"


def resolution_script():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    before = "      - name: Resolve reachable Mac mini SSH endpoint\n"
    after = "      - name: Resolve authorized Mac SSH identity\n"
    assert before in workflow and after in workflow
    assert workflow.index(before) < workflow.index(after)
    section = workflow.split(before, 1)[1].split(after, 1)[0]
    assert "        run: |\n" in section
    return textwrap.dedent(section.split("        run: |\n", 1)[1])


class TestFlightMacReachabilityTests(unittest.TestCase):
    def run_probe(self, *, reachable, hostname="Mac-mini-de-tarek.local"):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "timeout"
            # The child never makes a network request. It only emulates whether
            # a requested endpoint would answer on TCP port 22.
            tool.write_text('#!/bin/sh\n[ "$6" = "$MAC_REACHABLE_FOR_TEST" ]\n',
                            encoding="utf-8")
            tool.chmod(0o755)
            outputs = Path(directory) / "environment"
            env = os.environ.copy()
            env.update({
                "PATH": directory + os.pathsep + os.environ.get("PATH", ""),
                "CHECKUPAUTO_MAC_HOST": hostname,
                "CHECKUPAUTO_MAC_FALLBACK_IPV4": "192.168.0.27",
                "CHECKUPAUTO_MAC_SECONDARY_IPV4": "192.168.0.17",
                "MAC_REACHABLE_FOR_TEST": reachable,
                "GITHUB_ENV": str(outputs),
            })
            proc = subprocess.run(
                ["bash", "-c", resolution_script()],
                env=env, capture_output=True, text=True, timeout=10,
                check=False,
            )
            return proc, outputs.read_text(encoding="utf-8") if outputs.exists() else ""

    def test_fallback_when_mdns_is_not_resolved(self):
        result, env = self.run_probe(reachable="192.168.0.27")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env, "CHECKUPAUTO_MAC_HOST=192.168.0.27\n")
        self.assertIn("using reachable LAN IPv4", result.stdout)

    def test_secondary_address_when_primary_is_unavailable(self):
        result, env = self.run_probe(reachable="192.168.0.17")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env, "CHECKUPAUTO_MAC_HOST=192.168.0.17\n")

    def test_prefer_original_host_when_reachable(self):
        result, env = self.run_probe(reachable="Mac-mini-de-tarek.local")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env, "CHECKUPAUTO_MAC_HOST=Mac-mini-de-tarek.local\n")

    def test_no_reachable_host_fails_closed(self):
        result, env = self.run_probe(reachable="unavailable")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(env, "")
        self.assertIn("port 22 unreachable", result.stdout)

    def test_invalid_host_rejected_before_environment_export(self):
        result, env = self.run_probe(reachable="192.168.0.27",
                                     hostname="untrusted\nSSH_AUTH_SOCK=malicious")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(env, "")
        self.assertIn("Invalid Mac mini endpoint", result.stdout)

    def test_release_authentication_stays_noninteractive_and_fail_closed(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("-o BatchMode=yes", workflow)
        self.assertIn("-o IdentitiesOnly=yes", workflow)
        self.assertIn('CHECKUPAUTO_MAC_SSH_KEY: ${{ secrets.CHECKUPAUTO_MAC_SSH_KEY }}', workflow)
        self.assertIn("SSH identity for this runner", workflow)
        self.assertIn("ssh-keygen -y -f", workflow)
        self.assertIn("StrictHostKeyChecking=accept-new", workflow)


if __name__ == "__main__":
    unittest.main()
