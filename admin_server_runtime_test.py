import os
from pathlib import Path
import runpy
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent


class AdminServerRuntimeTest(unittest.TestCase):
    def load_server(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        private = root / "private"
        private.mkdir()
        (private / "admin-password").write_text("test-password\n", encoding="utf-8")
        env = {
            "CYBERCHECK_PRIVATE_DIR": str(private),
            "CYBERCHECK_DATA_DIR": str(root / "data"),
            "CYBERCHECK_SECURITY_DIR": str(root / "security"),
            "CYBERCHECK_INTEGRITY_DIR": str(root / "integrity"),
            "CYBERCHECK_GSC_CREDENTIALS_PATH": str(private / "gsc.json"),
            "CYBERCHECK_SITE_CONFIG_PATH": str(root / "data" / "site-config.json"),
        }
        with mock.patch.dict(os.environ, env, clear=False):
            namespace = runpy.run_path(str(ROOT / "admin_server.py"))
        return tmp, namespace

    def test_internal_proxy_accepts_forwarded_ip_only_with_loopback_and_secret(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)
        ns["configure_internal_proxy"]("A" * 48)

        good = types.SimpleNamespace(
            client_address=("127.0.0.1", 1234),
            headers={
                "X-CheckupAuto-Proxy-Token": "A" * 48,
                "X-CheckupAuto-Client-IP": "203.0.113.77",
            },
        )
        self.assertEqual(ns["_security_client_ip"](good), "203.0.113.77")

        wrong_secret = types.SimpleNamespace(
            client_address=("127.0.0.1", 1234),
            headers={
                "X-CheckupAuto-Proxy-Token": "B" * 48,
                "X-CheckupAuto-Client-IP": "203.0.113.77",
            },
        )
        self.assertEqual(ns["_security_client_ip"](wrong_secret), "127.0.0.1")

        non_loopback = types.SimpleNamespace(
            client_address=("198.51.100.2", 1234),
            headers={
                "X-CheckupAuto-Proxy-Token": "A" * 48,
                "X-CheckupAuto-Client-IP": "203.0.113.77",
            },
        )
        self.assertEqual(ns["_security_client_ip"](non_loopback), "198.51.100.2")

    def test_invalid_internal_proxy_token_is_rejected(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(ValueError):
            ns["configure_internal_proxy"]("short")
        with self.assertRaises(ValueError):
            ns["configure_internal_proxy"]("A" * 40 + "!")

    def test_passenger_initialization_does_not_start_background_workers(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)

        modules = {}
        for name in (
            "analytics",
            "referrals",
            "notifications",
            "mobile_devices",
            "reminder_dispatch",
            "booking",
            "booking_test",
            "reviews",
            "withdrawals",
            "retention_enforcement",
            "security",
            "security_alerts",
            "competitive",
            "mobile_authoritative_sync",
            "mobile_reminder_dispatch",
            "security_integrity",
            "security_ai",
        ):
            modules[name] = mock.Mock(name=name)
            ns[name] = modules[name]

        ns["_RUNTIME_CORE_READY"] = False
        ns["_RUNTIME_BACKGROUND_READY"] = False
        fn = ns["initialize_runtime"]
        fn.__globals__.update(ns)

        with mock.patch.object(
            ns["migration_write_freeze"],
            "status",
            return_value={"active":False,"valid":True,"state":"inactive"},
        ), mock.patch.object(ns["os"], "chdir"):
            first = fn(background=False)
            second = fn(background=False)

        self.assertTrue(first["coreReady"])
        self.assertFalse(first["backgroundReady"])
        self.assertEqual(second, first)

        for name in (
            "booking_test",
            "reviews",
            "reminder_dispatch",
            "mobile_authoritative_sync",
            "mobile_reminder_dispatch",
            "security_alerts",
            "retention_enforcement",
            "security_integrity",
            "security_ai",
        ):
            modules[name].start.assert_not_called()

        self.assertEqual(modules["analytics"].init_db.call_count, 1)
        self.assertEqual(modules["security"].init_db.call_count, 1)
        self.assertEqual(modules["reviews"].init_db.call_count, 1)
        self.assertEqual(modules["withdrawals"].init_db.call_count, 1)
        self.assertEqual(modules["retention_enforcement"].init_db.call_count, 1)

        with mock.patch.object(
            ns["migration_write_freeze"],
            "status",
            return_value={"active":False,"valid":True,"state":"inactive"},
        ), mock.patch.object(ns["os"], "chdir"):
            result = fn(background=True)
        self.assertTrue(result["backgroundReady"])
        modules["booking_test"].start.assert_called_once_with(300)
        modules["reviews"].start.assert_called_once_with()
        modules["security_alerts"].start.assert_called_once_with(120)
        modules["retention_enforcement"].start.assert_called_once_with(3600)

        with mock.patch.object(
            ns["migration_write_freeze"],
            "status",
            return_value={"active":False,"valid":True,"state":"inactive"},
        ), mock.patch.object(ns["os"], "chdir"):
            fn(background=True)
        self.assertEqual(modules["security_alerts"].start.call_count, 1)
        self.assertEqual(modules["retention_enforcement"].start.call_count, 1)


    def test_frozen_runtime_skips_core_and_background_initialization(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)

        modules={}
        for name in (
            "analytics","referrals","notifications","mobile_devices","reminder_dispatch",
            "booking","booking_test","reviews","withdrawals","retention_enforcement",
            "security","security_alerts","competitive","mobile_authoritative_sync",
            "mobile_reminder_dispatch","security_integrity","security_ai",
        ):
            modules[name]=mock.Mock(name=name)
            ns[name]=modules[name]

        ns["_RUNTIME_CORE_READY"]=False
        ns["_RUNTIME_BACKGROUND_READY"]=False
        fn=ns["initialize_runtime"]
        fn.__globals__.update(ns)

        with mock.patch.object(
            ns["migration_write_freeze"],
            "status",
            return_value={"active":True,"valid":True,"state":"frozen"},
        ), mock.patch.object(ns["os"],"chdir") as chdir:
            result=fn(background=True)

        self.assertEqual(result,{
            "coreReady":False,
            "backgroundReady":False,
            "writeFrozen":True,
        })
        chdir.assert_not_called()
        for module in modules.values():
            for method in ("init_db","start","seed_public_baseline","seed_review_baseline"):
                getattr(module,method).assert_not_called()

    def test_server_bind_address_defaults_to_loopback(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)
        host, port = ns["server_bind_address"]({})
        self.assertEqual((host, port), ("127.0.0.1", 8765))

    def test_server_bind_address_allows_container_binding(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)
        host, port = ns["server_bind_address"]({
            "CYBERCHECK_BIND_HOST": "0.0.0.0",
            "CYBERCHECK_BIND_PORT": "9876",
        })
        self.assertEqual((host, port), ("0.0.0.0", 9876))

    def test_server_bind_address_rejects_unexpected_values(self):
        tmp, ns = self.load_server()
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(ValueError):
            ns["server_bind_address"]({"CYBERCHECK_BIND_HOST": "example.com"})
        with self.assertRaises(ValueError):
            ns["server_bind_address"]({"CYBERCHECK_BIND_PORT": "70000"})



if __name__ == "__main__":
    unittest.main()
