from pathlib import Path
import unittest


class SecurityCIJavaScriptCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = Path(".github/workflows/security-ci.yml").read_text(encoding="utf-8")

    def test_all_tracked_javascript_is_syntax_checked(self):
        self.assertIn("git ls-files '*.js'", self.workflow)
        self.assertIn('node --check "$file"', self.workflow)
        self.assertIn('while IFS= read -r file; do', self.workflow)

    def test_new_compliance_register_script_is_covered_by_glob(self):
        scripts = [path.as_posix() for path in Path('.').rglob('*.js') if '.git' not in path.parts]
        self.assertIn('admin/compliance-registers.js', scripts)
        self.assertNotIn('node --check admin/compliance.js\n', self.workflow)


if __name__ == "__main__":
    unittest.main()
