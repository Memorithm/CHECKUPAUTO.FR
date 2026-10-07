import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock
import importlib.util

ROOT=Path(__file__).resolve().parent
SCRIPT=ROOT/"scripts"/"checkupauto-planethoster-legacy-staging-deploy.py"
spec=importlib.util.spec_from_file_location("legacy_deploy",SCRIPT)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class LegacyStagingDeployTest(unittest.TestCase):
    def test_target_is_exact_existing_planethoster_staging(self):
        self.assertEqual(m.TARGET["host"],"nodels49-eu.n0c.com")
        self.assertEqual(m.TARGET["port"],5022)
        self.assertEqual(m.TARGET["domain"],"test.checkupauto.fr")
        self.assertEqual(m.TARGET["rootPath"],".checkupauto-test")
        self.assertEqual(m.TARGET["webRootPath"],"test.checkupauto.fr")

    def test_activation_preserves_legacy_adapter_and_has_rollback(self):
        text=m._activation_program("a"*40,"1"*64)
        self.assertIn('checkupauto-test-application',text)
        self.assertIn('checkupauto-update-safety.py',text)
        self.assertIn('"backup"',text)
        self.assertIn('os.replace(incoming, current)',text)
        self.assertIn('os.replace(rollback, current)',text)
        self.assertIn('_prepare_static(release, "incoming")',text)
        self.assertIn('_prepare_static(previous, "rollback")',text)
        self.assertIn('_activate_static(static_new)',text)
        self.assertIn('_activate_static(static_rollback)',text)
        self.assertIn('touch_restart()',text)
        self.assertNotIn('.htaccess',text)
        self.assertNotIn('admin-password',text)

    def test_activation_http_verification_pins_origin_but_keeps_tls_hostname(self):
        text=m._activation_program("f"*40,"2"*64)
        self.assertIn('origin_ip = "185.221.181.53"', text)
        self.assertIn('socket.create_connection((origin_ip, 443)', text)
        self.assertIn('context.wrap_socket(raw, server_hostname=domain)', text)
        self.assertIn('"Host: " + domain', text)
        self.assertIn('origin_get("/api/app/status"', text)
        self.assertIn('origin_get("/api/public/deployment-provenance"', text)
        self.assertIn('provenance.get("gitSha") != SHA', text)
        self.assertIn('"deployment provenance mismatch"', text)
        self.assertIn('"style.css", "app.js", "consent.js", "assets/cybercheck-runtime-marker.bin"', text)
        self.assertIn('hashlib.sha256(static_body).digest()', text)
        self.assertIn('"static asset digest mismatch: " + public_path', text)
        self.assertNotIn('request.urlopen("https://" + domain + "/api/app/status"', text)

    def test_activation_checks_all_legal_routes_and_phase2(self):
        text=m._activation_program("b"*40,"3"*64)
        for path in ("/mentions-legales","/confidentialite","/cookies","/cgv","/retractation"):
            self.assertIn(path,text)
        self.assertIn("legacy-rdv-2026-10-04",text)
        self.assertIn("mercureweb-2022-legacy",text)
        self.assertIn("compliance_admin.snapshot()",text)
        self.assertIn("phase2Blockers",text)

    @mock.patch.object(m.deployment_transport,"ssh_arguments",return_value=["ssh","target"])
    @mock.patch.object(m.subprocess,"run")
    def test_explicit_n0c_runtime_qualification_requires_alt_python_and_adapter(self,run,_ssh):
        capabilities=m.deployment_center.CapabilityReport()
        run.return_value=subprocess.CompletedProcess(
            [],0,stdout="Python 3.12.12\npassenger_adapter=1\n",stderr=""
        )
        result=m._qualify_n0c_legacy_runtime(
            m.deployment_center.validate_target(m.TARGET),
            "/tmp/hosts",
            m.deployment_transport.SSHCredential(identity_file="/tmp/key"),
            capabilities,
        )
        self.assertEqual(result.python_version,"Python 3.12.12")
        self.assertTrue(result.passenger)
        self.assertIn("/opt/alt/python312/bin/python3",run.call_args.kwargs["input"])
        self.assertIn("checkupauto-test-application/passenger_wsgi.py",run.call_args.kwargs["input"])

    def test_activation_compliance_snapshot_uses_release_virtualenv(self):
        text=m._activation_program("9"*40,"4"*64)
        self.assertIn('[str(release / ".venv/bin/python"), "-c", compliance_code]',text)
        self.assertIn('cwd=release',text)
        self.assertIn('env=env',text)
        self.assertIn('"compliance snapshot failed"',text)
        self.assertIn('rebaseline_verified_release',text)
        self.assertIn('ARCHIVE_SHA256',text)
        self.assertIn('"integrity rebaseline failed"',text)
        self.assertNotIn('sys.path.insert(0, str(release))\n    import compliance_admin',text)


    def test_activation_pins_incoming_archive_but_accepts_verified_previous_digest(self):
        text=m._activation_program("7"*40,"8"*64)
        self.assertIn("def marker(path, expected_archive_sha256=None):",text)
        self.assertIn("marker(release, ARCHIVE_SHA256)",text)
        self.assertIn("marker(previous)",text)
        self.assertIn('fail("release marker digest mismatch")',text)
        self.assertNotIn("marker(previous, ARCHIVE_SHA256)",text)

    def test_activation_progress_is_bounded(self):
        text=m._activation_program("c"*40,"5"*64)
        for step in ("preflight","backup","import","switch","static","restart","http_verify","compliance","integrity","rollback"):
            self.assertIn(m._ACTIVATION_STEP_PREFIX+step,text)
        self.assertEqual(
            m._last_activation_step(
                "noise\n"+m._ACTIVATION_STEP_PREFIX+"switch\nprivate-error\n"+m._ACTIVATION_STEP_PREFIX+"rollback\n"
            ),
            "switch",
        )
        self.assertEqual(m._last_activation_step("private-error"),"unknown")
        self.assertEqual(
            m._last_activation_step(m._ACTIVATION_STEP_PREFIX+"/home/private"),
            "unknown",
        )

    def test_invalid_sha_is_rejected(self):
        with self.assertRaises(ValueError):
            m._activation_program("bad","1"*64)
        with self.assertRaises(ValueError):
            m._activation_program("a"*40,"bad")
        with self.assertRaises(ValueError):
            m.deploy("bad","/tmp/key","/tmp/hosts")

    def test_parse_result_accepts_only_tagged_success(self):
        good=m._RESULT_PREFIX+json.dumps({"ok":True,"state":"activated","sha":"c"*40})
        self.assertEqual(m._parse_result(good)["state"],"activated")
        with self.assertRaises(RuntimeError):
            m._parse_result('{"ok":true}')
        with self.assertRaises(RuntimeError):
            m._parse_result(m._RESULT_PREFIX+'{"ok":false}')

    @mock.patch.object(m.deployment_update,"update_status")
    @mock.patch.object(m.deployment_release,"stage_release")
    @mock.patch.object(m.deployment_transport,"probe_target")
    @mock.patch.object(m.deployment_transport,"ssh_arguments")
    @mock.patch.object(m.deployment_center,"assess")
    @mock.patch.object(m.subprocess,"run")
    def test_deploy_stages_and_activates_only_update_available(self,run,assess,ssh_args,probe,stage,status):
        sha="d"*40
        probe.return_value=mock.Mock()
        assess.return_value={"ok":True,"blockers":[]}
        status.return_value={"state":"update_available"}
        stage.return_value=mock.Mock(sha=sha,archive_sha256="6"*64)
        ssh_args.return_value=["ssh","target"]
        run.return_value=subprocess.CompletedProcess(
            [],0,stdout=m._RESULT_PREFIX+json.dumps({"ok":True,"state":"activated","sha":sha}),stderr=""
        )
        with mock.patch.object(m,"_qualify_n0c_legacy_runtime",return_value=probe.return_value):
            result=m.deploy(sha,"/tmp/key","/tmp/hosts")
        self.assertEqual(result["state"],"activated")
        stage.assert_called_once()
        run.assert_called_once()
        self.assertIn("/opt/alt/python312/bin/python3",run.call_args.args[0])

    @mock.patch.object(m.deployment_update,"update_status",return_value={"state":"diverged"})
    @mock.patch.object(m.deployment_transport,"probe_target",return_value=mock.Mock())
    @mock.patch.object(m.deployment_center,"assess",return_value={"ok":True,"blockers":[]})
    def test_diverged_remote_is_never_deployed(self,_assess,_probe,_status):
        with mock.patch.object(m,"_qualify_n0c_legacy_runtime",return_value=_probe.return_value):
            with self.assertRaisesRegex(RuntimeError,"diverged"):
                m.deploy("e"*40,"/tmp/key","/tmp/hosts")

if __name__=="__main__":
    unittest.main()
