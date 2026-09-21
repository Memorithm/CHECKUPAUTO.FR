import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock

import deployment_center as center
import deployment_executor as executor
import deployment_transport as transport


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "scripts" / "checkupauto-deployctl.py"
SHA = "a" * 40
PREVIOUS_SHA = "b" * 40


def load_cli():
    spec = importlib.util.spec_from_file_location("checkupauto_deployctl_test_module", CLI)
    if spec is None or spec.loader is None:
        raise RuntimeError("CLI module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeploymentCLIExecutionTest(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.target = center.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
            "rootPath": ".private-checkupauto",
            "webRootPath": "www/checkupauto",
        })
        self.credential = transport.SSHCredential(identity_file="/tmp/id_ed25519")

    def test_stored_target_preserves_custom_web_root(self):
        restored = self.cli._stored_target({"target": self.target.public_dict()})
        self.assertEqual(restored.root_path, ".private-checkupauto")
        self.assertEqual(restored.web_root_path, "www/checkupauto")

    def test_parser_exposes_install_update_and_rollback(self):
        for command in ("install", "update", "rollback"):
            with self.subTest(command=command):
                args = self.cli.parser().parse_args([
                    command,
                    "--name", "production",
                    "--known-hosts", "/tmp/known_hosts",
                    "--sha", SHA,
                ])
                self.assertEqual(args.command, command)
                self.assertEqual(args.sha, SHA)

    def test_result_payload_does_not_expose_remote_release_path(self):
        result = executor.DeploymentExecutionResult(
            action="update",
            sha=SHA,
            previous_sha=PREVIOUS_SHA,
            staged=True,
            release_path="/home/private-user/.checkupauto/releases/" + SHA,
            archive_sha256="c" * 64,
            file_count=50,
            readiness_state="ready",
            activation_allowed=True,
            blocker_count=0,
        )
        payload = self.cli._result_payload(result)
        encoded = json.dumps(payload)
        self.assertNotIn("private-user", encoded)
        self.assertNotIn("release_path", encoded)
        self.assertEqual(payload["release"]["archiveSha256"], "c" * 64)

    def test_update_command_executes_one_click_orchestrator(self):
        result = executor.DeploymentExecutionResult(
            action="update",
            sha=SHA,
            previous_sha=PREVIOUS_SHA,
            staged=True,
            release_path="ignored",
            archive_sha256="c" * 64,
            file_count=50,
            readiness_state="ready",
            activation_allowed=True,
            blocker_count=0,
        )
        args = self.cli.parser().parse_args([
            "update",
            "--name", "production",
            "--known-hosts", "/tmp/known_hosts",
            "--sha", SHA,
        ])
        output = io.StringIO()
        with mock.patch.object(
            self.cli,
            "_stored_context",
            return_value=(self.target, self.credential),
        ), mock.patch.object(
            self.cli,
            "execute_deployment",
            return_value=result,
        ) as execute, contextlib.redirect_stdout(output):
            status = args.func(args)
        self.assertEqual(status, 0)
        self.assertEqual(execute.call_args.args[0], "update")
        self.assertEqual(execute.call_args.args[5], SHA)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["sha"], SHA)
        self.assertTrue(payload["readiness"]["activationAllowed"])


if __name__ == "__main__":
    unittest.main()
