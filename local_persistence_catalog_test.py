import json
import re
import unittest
from pathlib import Path

import local_persistence_catalog as catalog

ROOT=Path(__file__).resolve().parent
CREATE_RE=re.compile(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)",re.I)


def production_tables():
    found={}
    for path in ROOT.rglob("*.py"):
        rel=path.relative_to(ROOT)
        name=path.name
        if "__pycache__" in path.parts or ".ci-venv" in path.parts:
            continue
        if (
            (name.endswith("_test.py") or name.startswith("test_"))
            and name not in {"booking_test.py"}
        ) or "tests" in rel.parts:
            continue
        text=path.read_text(encoding="utf-8")
        for table in CREATE_RE.findall(text):
            found.setdefault(table,set()).add(str(rel))
    return {table:sorted(paths) for table,paths in found.items()}


class LocalPersistenceCatalogTest(unittest.TestCase):
    def test_catalog_exactly_covers_production_create_table_declarations(self):
        data=catalog.load()
        rows={row["table"]:row["module"] for row in data["tables"]}
        found=production_tables()
        self.assertEqual(set(rows),set(found))
        self.assertGreaterEqual(len(rows),70)
        for table,module in rows.items():
            self.assertIn(module,found[table],f"{table}: catalog module must declare the table")

    def test_catalog_is_technical_discovery_not_privacy_completion(self):
        state=catalog.snapshot()
        self.assertTrue(state["complete"])
        self.assertEqual(state["tableCount"],74)
        self.assertFalse(state["privacyExecutionCoverageAsserted"])
        self.assertEqual(state["state"],"catalogued")
        self.assertNotIn("privacyClass", state)
        self.assertNotIn("rightsAdapter", state)

    def test_catalog_contains_no_test_module(self):
        data=catalog.load()
        for row in data["tables"]:
            name=Path(row["module"]).name
            if name == "booking_test.py":
                continue
            self.assertFalse(name.endswith("_test.py"))
            self.assertFalse(name.startswith("test_"))


if __name__=="__main__":
    unittest.main()
