"""O-02: third-party actions pinned by commit SHA."""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent / ".github" / "workflows"


class WorkflowPinningTest(unittest.TestCase):
    def test_every_action_is_pinned_by_full_commit_sha(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = re.search(r"\buses:\s*([^\s#]+)", line)
                if not match or match.group(1).startswith("./"):
                    continue
                with self.subTest(workflow=path.name, line=number):
                    self.assertRegex(match.group(1), r"@[0-9a-f]{40}$")



if __name__ == "__main__":
    unittest.main()
