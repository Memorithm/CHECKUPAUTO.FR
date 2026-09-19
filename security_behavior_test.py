import runpy
import unittest
from unittest.mock import patch


class SecurityBehaviorImportTest(unittest.TestCase):
    def test_import_does_not_open_runtime_database(self):
        with patch(
            "sqlite3.connect",
            side_effect=AssertionError("database opened during import"),
        ):
            module = runpy.run_path(
                "security_behavior.py",
                run_name="security_behavior_import_probe",
            )
        self.assertIn("init_db", module)
        self.assertIn("observe_request", module)
        self.assertIn("profiles", module)


if __name__ == "__main__":
    unittest.main()
