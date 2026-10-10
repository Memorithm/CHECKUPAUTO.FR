import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent / ".github" / "workflows"
GUARD = "Refuse protected runners for pull request code"


def _jobs(text):
    """Split a workflow into (job name, body) using its two-space job keys."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n  (?=[A-Za-z0-9_-]+:\n)", "\n" + body)
    return [(part.split(":", 1)[0].strip(), part) for part in parts if part.strip()]


class CiRunnerIsolationTest(unittest.TestCase):
    """O-01: pull request code must not silently reach the shared self-hosted fleet."""

    def test_security_ci_runs_pull_requests_on_github_hosted_runners(self):
        text = (WORKFLOWS / "security-ci.yml").read_text(encoding="utf-8")
        self.assertIn("github.event_name == 'pull_request' && 'ubuntu-24.04'", text)

    def test_self_hosted_pull_request_jobs_guard_before_checkout(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if not re.search(r"^  pull_request:", text, re.M):
                continue
            for name, job in _jobs(text):
                if "runs-on: [self-hosted, Linux" not in job:
                    continue
                with self.subTest(workflow=path.name, job=name):
                    self.assertIn(GUARD, job)
                    self.assertLess(job.index(GUARD), job.index("actions/checkout@"))

    def test_3d_asset_ci_is_least_privilege_and_pins_host_keys(self):
        text = (WORKFLOWS / "3d-asset-ci.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("/root/.ssh", text)
        self.assertNotIn(".ssh/", text)
        self.assertNotIn("accept-new", text)
        self.assertNotIn("Mac-mini-de-tarek", text)
        jobs = dict(_jobs(text))
        self.assertIn("persist-credentials: false", jobs["export-glb"])
        self.assertNotIn("contents: write", jobs["export-glb"])
        self.assertIn("contents: write", jobs["commit-glb"])
        self.assertIn("runs-on: ubuntu-", jobs["commit-glb"])

    def test_no_workflow_grants_write_at_top_level(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            top = path.read_text(encoding="utf-8").split("\njobs:\n", 1)[0]
            with self.subTest(workflow=path.name):
                self.assertNotIn("contents: write", top)


if __name__ == "__main__":
    unittest.main()
