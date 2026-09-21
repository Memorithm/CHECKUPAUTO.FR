import unittest

import deployment_center as deploy


SHA = "a" * 40


class DeploymentCenterTest(unittest.TestCase):
    def test_planethoster_profiles_use_expected_ssh_defaults(self):
        profiles = deploy.provider_profiles()
        self.assertEqual(profiles["planethoster-n0c"]["defaultPort"], 5022)
        self.assertEqual(profiles["planethoster-cpanel"]["defaultPort"], 2908)
        self.assertEqual(profiles["planethoster-n0c"]["runtime"], "passenger")
        self.assertTrue(profiles["planethoster-n0c"]["sharedHosting"])

    def test_planethoster_target_defaults_to_public_html(self):
        target = deploy.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
        })
        self.assertEqual(target.port, 5022)
        self.assertEqual(target.root_path, "public_html")
        self.assertEqual(target.auth_mode, "key")

    def test_cpanel_target_defaults_to_legacy_port(self):
        target = deploy.validate_target({
            "provider": "planethoster-cpanel",
            "host": "192.0.2.4",
            "username": "centre",
            "domain": "checkupauto.fr",
            "authMode": "password",
        })
        self.assertEqual(target.port, 2908)
        self.assertEqual(target.auth_mode, "password")

    def test_rejects_unknown_provider_and_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "profil"):
            deploy.validate_target({
                "provider": "unknown",
                "host": "example.net",
                "username": "user",
                "domain": "example.net",
            })
        with self.assertRaisesRegex(ValueError, "répertoire"):
            deploy.validate_target({
                "provider": "planethoster-n0c",
                "host": "example.net",
                "username": "user",
                "domain": "example.net",
                "rootPath": "../public_html",
            })

    def test_shared_host_rejects_absolute_root(self):
        with self.assertRaisesRegex(ValueError, "relatif"):
            deploy.validate_target({
                "provider": "planethoster-n0c",
                "host": "example.net",
                "username": "user",
                "domain": "example.net",
                "rootPath": "/home/user/public_html",
            })

    def test_rejects_malformed_connection_parameters(self):
        cases = [
            {"host": "bad host", "domain": "example.net", "username": "user"},
            {"host": "example.net", "domain": "localhost", "username": "user"},
            {"host": "example.net", "domain": "example.net", "username": "bad user"},
            {"host": "example.net", "domain": "example.net", "username": "user", "port": 70000},
        ]
        for changes in cases:
            payload = {
                "provider": "generic-ssh",
                "host": "example.net",
                "domain": "example.net",
                "username": "user",
            }
            payload.update(changes)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                deploy.validate_target(payload)

    def test_planethoster_blocks_activation_without_wsgi_adapter(self):
        target = deploy.validate_target({
            "provider": "planethoster-n0c",
            "host": "example.net",
            "username": "user",
            "domain": "example.net",
        })
        report = deploy.assess(
            target,
            deploy.CapabilityReport(
                python_version="Python 3.12.8",
                passenger=True,
                symlink=True,
                writable_root=True,
                free_disk_mb=4096,
                passenger_wsgi_adapter=False,
            ),
        )
        self.assertFalse(report["ok"])
        self.assertIn("passenger_wsgi_adapter", report["blockers"])
        self.assertNotIn("passenger", report["blockers"])

    def test_planethoster_is_ready_when_runtime_requirements_are_met(self):
        target = deploy.validate_target({
            "provider": "planethoster-n0c",
            "host": "example.net",
            "username": "user",
            "domain": "example.net",
        })
        report = deploy.assess(
            target,
            deploy.CapabilityReport(
                python_version="Python 3.12.8",
                passenger=True,
                cron=True,
                symlink=True,
                writable_root=True,
                free_disk_mb=4096,
                passenger_wsgi_adapter=True,
                shared_host_tick=True,
            ),
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["state"], "ready")

    def test_planethoster_requires_cron_for_periodic_tasks(self):
        target = deploy.validate_target({
            "provider": "planethoster-n0c",
            "host": "example.net",
            "username": "user",
            "domain": "example.net",
        })
        report = deploy.assess(
            target,
            deploy.CapabilityReport(
                python_version="Python 3.12.8",
                passenger=True,
                cron=False,
                symlink=True,
                writable_root=True,
                free_disk_mb=4096,
                passenger_wsgi_adapter=True,
                shared_host_tick=True,
            ),
        )
        self.assertFalse(report["ok"])
        self.assertIn("cron", report["blockers"])

    def test_planethoster_requires_shared_tick_even_with_wsgi(self):
        target = deploy.validate_target({
            "provider": "planethoster-n0c",
            "host": "example.net",
            "username": "user",
            "domain": "example.net",
        })
        report = deploy.assess(
            target,
            deploy.CapabilityReport(
                python_version="Python 3.12.8",
                passenger=True,
                cron=True,
                symlink=True,
                writable_root=True,
                free_disk_mb=4096,
                passenger_wsgi_adapter=True,
                shared_host_tick=False,
            ),
        )
        self.assertFalse(report["ok"])
        self.assertIn("shared_host_tick", report["blockers"])

    def test_systemd_profile_requires_systemd_not_passenger(self):
        target = deploy.validate_target({
            "provider": "linux-systemd",
            "host": "203.0.113.9",
            "username": "deploy",
            "domain": "example.net",
        })
        report = deploy.assess(
            target,
            deploy.CapabilityReport(
                python_version="3.12.3",
                systemd=True,
                passenger=False,
                symlink=True,
                writable_root=True,
                free_disk_mb=2048,
            ),
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["runtime"], "systemd")

    def test_installation_layout_is_release_scoped(self):
        target = deploy.validate_target({
            "provider": "generic-ssh",
            "host": "example.net",
            "username": "deploy",
            "domain": "example.net",
            "rootPath": "checkupauto",
        })
        layout = deploy.installation_layout(target, SHA)
        self.assertEqual(layout["release"], f"checkupauto/releases/{SHA}")
        self.assertEqual(layout["current"], "checkupauto/current")
        self.assertEqual(layout["private"], "checkupauto/shared/private")
        self.assertEqual(layout["integrity"], "checkupauto/shared/integrity")

    def test_blocked_plan_never_reaches_upload_or_activation(self):
        target = deploy.validate_target({
            "provider": "planethoster-n0c",
            "host": "example.net",
            "username": "deploy",
            "domain": "example.net",
        })
        plan = deploy.installation_plan(
            target,
            SHA,
            deploy.CapabilityReport(
                python_version="3.12",
                passenger=True,
                symlink=True,
                writable_root=True,
                free_disk_mb=2048,
            ),
        )
        self.assertFalse(plan["assessment"]["ok"])
        self.assertEqual([item["id"] for item in plan["actions"]], ["connect", "probe"])
        self.assertFalse(plan["secrets"]["persistInRepository"])
        self.assertFalse(plan["secrets"]["passwordInPlan"])

    def test_invalid_release_sha_is_rejected(self):
        target = deploy.validate_target({
            "provider": "generic-ssh",
            "host": "example.net",
            "username": "deploy",
            "domain": "example.net",
        })
        with self.assertRaisesRegex(ValueError, "SHA"):
            deploy.installation_layout(target, "main")


if __name__ == "__main__":
    unittest.main()
