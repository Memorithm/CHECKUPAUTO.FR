import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import retention_enforcement

ROOT=Path(__file__).resolve().parent
BASELINE=ROOT/"fixtures/compliance-technical-retention-baseline.json"
WORKFLOW=ROOT/".github/workflows/compliance-147-technical-retention.yml"
SCRIPT=ROOT/"scripts/checkupauto-compliance-seed-technical-retention.py"
SPEC=importlib.util.spec_from_file_location("checkupauto_compliance_seed_technical_retention",SCRIPT)
seed=importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(seed)


class Compliance147TechnicalRetentionTest(unittest.TestCase):
    def test_baseline_contains_only_three_nonlegal_rules(self):
        data=json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"],seed.SCHEMA)
        rows={row["ruleId"]:row for row in data["rules"]}
        self.assertEqual(set(rows),{"review_followup","reminder_targets","security_telemetry"})
        self.assertEqual(rows["review_followup"]["activeDays"],2)
        self.assertEqual(rows["reminder_targets"]["activeDays"],730)
        self.assertEqual(rows["security_telemetry"]["activeDays"],30)
        self.assertTrue(all(row["legalReviewConfirmed"] is False for row in rows.values()))
        self.assertTrue(all(not retention_enforcement.CONFIGURABLE_RULES[r].get("legalReviewRequired") for r in rows))
        self.assertEqual(data.get("automaticEventRules"),["checkout_acceptance_transient"])
        self.assertIn("checkout_acceptance_transient",retention_enforcement.AUTO_RULES)
        self.assertNotIn("checkout_acceptance_transient",retention_enforcement.CONFIGURABLE_RULES)

    def test_sources_remain_grounded_in_product_windows(self):
        review=(ROOT/"review_followup.py").read_text(encoding="utf-8")
        reminder=(ROOT/"reminder_dispatch.py").read_text(encoding="utf-8")
        security=(ROOT/"security_guard.py").read_text(encoding="utf-8")
        self.assertIn("LOOKBACK_HOURS=36",review)
        self.assertIn("BACKFILL_DAYS = 730",reminder)
        self.assertIn("STATUS_MAX_DAYS = 30",security)
        self.assertIn("min(int(days), STATUS_MAX_DAYS)",security)

    def test_apply_is_idempotent_and_leaves_legal_rules_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            first=seed.apply(db)
            second=seed.apply(db)
            self.assertEqual(first["changedRuleIds"],["reminder_targets","review_followup","security_telemetry"])
            self.assertEqual(second["changedRuleIds"],[])
            self.assertEqual(first["readyRuleCount"],15)
            self.assertFalse(first["retentionBound"])
            for rule_id in (
                "booking_conversions","contract_consent_receipts","withdrawal_evidence",
                "rights_requests_and_audit","referral_ledger",
            ):
                self.assertFalse(retention_enforcement.policy(rule_id,db)["configured"])

    def test_existing_conflict_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            retention_enforcement.save_policy({
                "ruleId":"review_followup",
                "activeDays":7,
                "justification":"Existing operator policy deliberately differs.",
                "legalReviewConfirmed":False,
                "enabled":True,
            },db)
            with self.assertRaisesRegex(RuntimeError,"conflicts"):
                seed.apply(db)

    def test_workflow_is_exact_runtime_backed_up_and_no_purge(self):
        source=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ops/compliance-147-technical-retention",source)
        self.assertIn("runtime revision does not match current main",source)
        self.assertIn("StrictHostKeyChecking=yes",source)
        self.assertIn("compliance-before-technical-retention-",source)
        self.assertIn("technical retention apply failed and backup restored",source)
        self.assertIn('"purgeExecuted":False',source)
        self.assertNotIn("retention_enforcement.run_once",source)


if __name__=="__main__":
    unittest.main()
