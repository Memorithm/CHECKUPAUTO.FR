from pathlib import Path
import tempfile
import unittest
from unittest import mock

import deployment_activation as activation
import deployment_center as center
import deployment_executor as executor
import deployment_release as release
import deployment_transport as transport
import deployment_update as deployment_update


SHA = "a" * 40
PREVIOUS_SHA = "b" * 40


class DeploymentExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "passenger_wsgi.py").write_text("# adapter\n", encoding="utf-8")
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "checkupauto-shared-tick.py").write_text("# tick\n", encoding="utf-8")
        self.known_hosts = self.root / "known_hosts"
        self.known_hosts.write_text("ssh.example.net ssh-ed25519 AAAATEST\n", encoding="utf-8")
        self.credential = transport.SSHCredential(identity_file=str(self.root / "id_ed25519"))
        self.target = center.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
        })

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def ready_capabilities():
        return center.CapabilityReport(
            python_version="Python 3.12.8",
            passenger=True,
            cron=True,
            symlink=True,
            writable_root=True,
            writable_web_root=True,
            free_disk_mb=4096,
            passenger_wsgi_adapter=True,
            shared_host_tick=True,
        )

    @mock.patch("deployment_executor.github_source.bootstrap_material")
    @mock.patch("deployment_executor.activation.activate_release")
    @mock.patch("deployment_executor.release.stage_release")
    @mock.patch("deployment_executor.deployment_update.classify_update")
    @mock.patch("deployment_executor.deployment_update.read_remote_state")
    @mock.patch("deployment_executor.transport.probe_target")
    def test_update_probes_stages_then_activates_exact_sha(
        self, probe, read_remote, classify_update, stage, activate, bootstrap_material
    ):
        bootstrap_material.return_value = {
            "repository": "Memorithm/CHECKUPAUTO.FR",
            "branch": "main",
            "token": "github" + "_pat_" + "T" * 40,
        }
        probe.return_value = self.ready_capabilities()
        read_remote.return_value = deployment_update.RemoteDeploymentState(
            installed=True,
            deployed_sha=PREVIOUS_SHA,
            releases=(deployment_update.RemoteRelease(PREVIOUS_SHA, 100),),
        )
        classify_update.return_value = {
            "state": "update_available",
            "updateAvailable": True,
        }
        stage.return_value = release.StageResult(
            sha=SHA,
            release_path=f"/home/checkup/.checkupauto/releases/{SHA}",
            archive_sha256="c" * 64,
            file_count=123,
        )
        activate.return_value = activation.ActivationResult(
            sha=SHA,
            previous_sha=PREVIOUS_SHA,
            readiness_state="ready",
            activation_allowed=True,
            blocker_count=0,
        )

        result = executor.execute_deployment(
            "update",
            self.target,
            self.known_hosts,
            self.credential,
            self.root,
            SHA,
            admin_password="local-admin-secret-value",
        )

        self.assertEqual(result.action, "update")
        self.assertEqual(result.sha, SHA)
        self.assertEqual(result.previous_sha, PREVIOUS_SHA)
        self.assertTrue(result.staged)
        self.assertEqual(result.archive_sha256, "c" * 64)
        self.assertEqual(result.file_count, 123)
        self.assertTrue(result.activation_allowed)
        probe.assert_called_once()
        read_remote.assert_called_once()
        classify_update.assert_called_once()
        self.assertTrue(probe.call_args.kwargs["passenger_wsgi_adapter"])
        self.assertTrue(probe.call_args.kwargs["shared_host_tick"])
        self.assertEqual(stage.call_args.args[5], SHA)
        self.assertEqual(activate.call_args.args[4], SHA)
        self.assertEqual(
            activate.call_args.kwargs["admin_password"],
            "local-admin-secret-value",
        )
        self.assertEqual(
            activate.call_args.kwargs["update_source"],
            bootstrap_material.return_value,
        )

    @mock.patch("deployment_executor.release.stage_release")
    @mock.patch("deployment_executor.transport.probe_target")
    def test_blocked_target_never_stages_release(self, probe, stage):
        probe.return_value = center.CapabilityReport(
            python_version="Python 3.12.8",
            passenger=False,
            cron=True,
            symlink=True,
            writable_root=True,
            writable_web_root=True,
            free_disk_mb=4096,
            passenger_wsgi_adapter=True,
            shared_host_tick=True,
        )
        with self.assertRaisesRegex(RuntimeError, "passenger"):
            executor.execute_deployment(
                "install",
                self.target,
                self.known_hosts,
                self.credential,
                self.root,
                SHA,
            )
        stage.assert_not_called()

    @mock.patch("deployment_executor.release.stage_release")
    @mock.patch("deployment_executor.deployment_update.read_remote_state")
    @mock.patch("deployment_executor.transport.probe_target")
    def test_install_refuses_already_installed_target(self, probe, read_remote, stage):
        probe.return_value = self.ready_capabilities()
        read_remote.return_value = deployment_update.RemoteDeploymentState(
            installed=True,
            deployed_sha=PREVIOUS_SHA,
            releases=(deployment_update.RemoteRelease(PREVIOUS_SHA, 100),),
        )
        with self.assertRaisesRegex(RuntimeError, "déjà installée"):
            executor.execute_deployment(
                "install",
                self.target,
                self.known_hosts,
                self.credential,
                self.root,
                SHA,
            )
        stage.assert_not_called()

    @mock.patch("deployment_executor.release.stage_release")
    @mock.patch("deployment_executor.deployment_update.classify_update")
    @mock.patch("deployment_executor.deployment_update.read_remote_state")
    @mock.patch("deployment_executor.transport.probe_target")
    def test_update_refuses_unsafe_remote_states(
        self, probe, read_remote, classify_update, stage
    ):
        probe.return_value = self.ready_capabilities()
        read_remote.return_value = deployment_update.RemoteDeploymentState(
            installed=True,
            deployed_sha=PREVIOUS_SHA,
            releases=(deployment_update.RemoteRelease(PREVIOUS_SHA, 100),),
        )
        for state in ("up_to_date", "remote_ahead", "diverged", "not_installed"):
            with self.subTest(state=state):
                classify_update.return_value = {
                    "state": state,
                    "updateAvailable": False,
                }
                with self.assertRaisesRegex(RuntimeError, "non autorisée"):
                    executor.execute_deployment(
                        "update",
                        self.target,
                        self.known_hosts,
                        self.credential,
                        self.root,
                        SHA,
                    )
        stage.assert_not_called()

    @mock.patch("deployment_executor.activation.rollback_release")
    @mock.patch("deployment_executor.release.stage_release")
    @mock.patch("deployment_executor.transport.probe_target")
    def test_rollback_reuses_existing_verified_release_without_staging(self, probe, stage, rollback):
        probe.return_value = self.ready_capabilities()
        rollback.return_value = activation.ActivationResult(
            sha=PREVIOUS_SHA,
            previous_sha=SHA,
            readiness_state="degraded",
            activation_allowed=False,
            blocker_count=2,
        )
        result = executor.execute_rollback(
            self.target,
            self.known_hosts,
            self.credential,
            self.root,
            PREVIOUS_SHA,
            admin_password="local-admin-secret-value",
        )
        self.assertEqual(result.action, "rollback")
        self.assertEqual(result.sha, PREVIOUS_SHA)
        self.assertFalse(result.staged)
        self.assertFalse(result.activation_allowed)
        self.assertEqual(result.blocker_count, 2)
        stage.assert_not_called()
        self.assertEqual(rollback.call_args.args[4], PREVIOUS_SHA)
        self.assertEqual(
            rollback.call_args.kwargs["admin_password"],
            "local-admin-secret-value",
        )

    @mock.patch("deployment_executor.transport.probe_target")
    def test_missing_local_runtime_contract_blocks_shared_host(self, probe):
        (self.root / "passenger_wsgi.py").unlink()
        (self.root / "scripts" / "checkupauto-shared-tick.py").unlink()
        probe.return_value = center.CapabilityReport(
            python_version="Python 3.12.8",
            passenger=True,
            cron=True,
            symlink=True,
            writable_root=True,
            writable_web_root=True,
            free_disk_mb=4096,
            passenger_wsgi_adapter=False,
            shared_host_tick=False,
        )
        with self.assertRaisesRegex(RuntimeError, "passenger_wsgi_adapter"):
            executor.probe_deployment_target(
                self.target,
                self.known_hosts,
                self.credential,
                self.root,
            )
        self.assertFalse(probe.call_args.kwargs["passenger_wsgi_adapter"])
        self.assertFalse(probe.call_args.kwargs["shared_host_tick"])

    def test_unknown_action_is_rejected_before_network_access(self):
        with mock.patch("deployment_executor.transport.probe_target") as probe:
            with self.assertRaisesRegex(ValueError, "action"):
                executor.execute_deployment(
                    "destroy",
                    self.target,
                    self.known_hosts,
                    self.credential,
                    self.root,
                    SHA,
                )
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
