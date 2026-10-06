from pathlib import Path
import subprocess
import unittest


ROOT=Path(__file__).resolve().parent
SCRIPT=ROOT/"deploy/hostinger/finalize-migration-state.sh"


class HostingerStagingMigrationFinalizeTest(unittest.TestCase):
    def test_finalize_script_is_valid_shell(self):
        result=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_finalize_requires_explicit_confirmation_and_healthy_frozen_runtime(self):
        text=SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ACTIVATE_MIGRATED_STATE",text)
        freeze_check=text.index("HOSTINGER_MIGRATION_PRE_FINALIZE_FREEZE_VERIFIED")
        health_check=text.index("HOSTINGER_MIGRATION_FROZEN_RUNTIME_NOT_HEALTHY")
        stop=text.index("docker compose stop web")
        self.assertLess(freeze_check,health_check)
        self.assertLess(health_check,stop)

    def test_unfreeze_occurs_only_offline_with_fail_closed_rollback_armed(self):
        text=SCRIPT.read_text(encoding="utf-8")
        stop=text.index("docker compose stop web")
        rollback=text.index("rollback()")
        trap=text.index("trap rollback ERR")
        unfreeze=text.index("unfreeze --confirm UNFREEZE")
        offline_init=text.index("initialize_runtime(background=False)")
        start=text.index("docker compose up -d --no-deps web")
        self.assertLess(stop,rollback)
        self.assertLess(rollback,trap)
        self.assertLess(trap,unfreeze)
        self.assertLess(unfreeze,offline_init)
        self.assertLess(offline_init,start)
        self.assertIn("freeze --reason hostinger_finalize_failed",text)
        self.assertIn("HOSTINGER_MIGRATION_FINALIZE_ROLLED_BACK_TO_FREEZE",text)

    def test_finalize_requires_verified_import_rollback_state(self):
        text=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('IMPORT_RECEIPT="$ROOT/migration-last-import.json"',text)
        receipt=text.index("HOSTINGER_MIGRATION_IMPORT_RECEIPT_INVALID")
        previous=text.index("HOSTINGER_MIGRATION_ROLLBACK_STATE_VERIFIED")
        freeze=text.index("HOSTINGER_MIGRATION_PRE_FINALIZE_FREEZE_VERIFIED")
        self.assertLess(receipt,previous)
        self.assertLess(previous,freeze)
        self.assertIn(r"\.migration-previous-[0-9a-f]{32}",text)

    def test_success_revalidates_https_exact_release_and_inactive_freeze(self):
        text=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"https://$HOST/"',text)
        self.assertIn("cybercheck-deployment-provenance.bin",text)
        self.assertIn('"gitSha":expected',text)
        self.assertIn('"source":"remoteops-approved-git-archive"',text)
        self.assertIn('state.get("state")!="inactive"',text)
        unfreeze_verified=text.index("HOSTINGER_MIGRATION_UNFREEZE_VERIFIED")
        purge=text.index("HOSTINGER_MIGRATION_ROLLBACK_STATE_PURGED")
        success=text.index("HOSTINGER_MIGRATION_STATE_ACTIVE=")
        self.assertLess(unfreeze_verified,purge)
        self.assertLess(purge,success)
        self.assertIn("shutil.rmtree(previous)",text)
        self.assertIn("receipt.unlink()",text)


if __name__=="__main__":
    unittest.main()
