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
        self.assertEqual(state["tableCount"],85)
        self.assertTrue(state["mappingComplete"])
        self.assertEqual(state["subjectExecutionRequiredCount"],23)
        self.assertEqual(state["executionGapCount"],10)
        self.assertEqual(
            state["executionGapTables"],
            ["booking_conversions","consent_receipts","notification_delivery","payment_binding","referral_accounts","referral_ledger","referral_rewards","referral_wallet_owner","review_followup","withdrawal_requests"],
        )
        self.assertFalse(state["privacyExecutionCoverageAsserted"])
        self.assertEqual(state["state"],"mapped_with_execution_gaps")
        self.assertNotIn("subjectRelation", state)
        self.assertNotIn("adapter", state)

    def test_every_required_subject_table_is_wired_or_explicit_gap(self):
        data=catalog.load()
        required=[row for row in data["tables"] if row["subjectExecutionRequired"]]
        self.assertEqual(len(required),23)
        self.assertEqual(
            sorted(row["table"] for row in required if row["executionState"]!="wired"),
            ["booking_conversions","consent_receipts","notification_delivery","payment_binding","referral_accounts","referral_ledger","referral_rewards","referral_wallet_owner","review_followup","withdrawal_requests"],
        )
        for row in required:
            self.assertIn(row["executionState"],{"wired","partial","unmapped"})

    def test_promotion_attempts_contain_no_customer_subject(self):
        row=next(row for row in catalog.load()["tables"]
                 if row["table"]=="booking_demand_promotion_attempts")
        self.assertEqual(row["module"],"booking_demand.py")
        self.assertEqual(row["subjectRelation"],"none")
        self.assertEqual(row["executionState"],"not_applicable")
        self.assertFalse(row["subjectExecutionRequired"])

    def test_checkout_acceptance_intents_are_transient_and_retention_governed(self):
        row=next(
            item for item in catalog.load()["tables"]
            if item["table"]=="checkout_acceptance_intents"
        )
        self.assertEqual(row["subjectRelation"],"transient")
        self.assertEqual(row["executionState"],"retention_only")
        self.assertEqual(row["adapter"],"retention_enforcement")
        self.assertFalse(row["subjectExecutionRequired"])

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
