from pathlib import Path
import subprocess
import unittest


ROOT=Path(__file__).resolve().parent
SCRIPT=ROOT/"deploy/hostinger/import-migration-state.sh"


class HostingerStagingMigrationImportTest(unittest.TestCase):
    def test_import_script_is_valid_shell(self):
        result=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_running_container_is_refused_before_any_import(self):
        text=SCRIPT.read_text(encoding="utf-8")
        inspect=text.index("docker inspect")
        refusal=text.index("HOSTINGER_MIGRATION_IMPORT_REFUSED_CONTAINER_RUNNING")
        verify=text.index('"$tool" verify')
        do_import=text.index('"$tool" import')
        self.assertLess(inspect,refusal)
        self.assertLess(refusal,verify)
        self.assertLess(verify,do_import)

    def test_snapshot_is_confined_and_import_keeps_runtime_frozen(self):
        text=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('INCOMING_ROOT="$ROOT/migration-incoming"',text)
        self.assertIn('"$INCOMING_ROOT"/*',text)
        self.assertIn('--target-root "$STATE"',text)
        self.assertIn("--uid 10001",text)
        self.assertIn("--gid 10001",text)
        self.assertIn("migration_write_freeze.status()",text)
        self.assertIn('state.get("state")!="frozen"',text)
        self.assertNotIn("docker compose up",text)
        self.assertNotIn("migration_write_freeze.release",text)
        self.assertNotIn("unlink",text)


if __name__=="__main__":
    unittest.main()
