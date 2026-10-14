import io
import contextlib
import errno
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import passenger_wsgi as wsgi


class FakeResponse:
    status = 200
    reason = "OK"

    def __init__(self, body=b"hello"):
        self.body = io.BytesIO(body)

    def getheaders(self):
        return [
            ("Content-Type", "text/plain"),
            ("Content-Length", "5"),
            ("Connection", "close"),
        ]

    def read(self, size=-1):
        return self.body.read(size)


class FakeConnection:
    instances = []

    def __init__(self, host, port, timeout=0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.request_args = None
        self.closed = False
        self.response = FakeResponse()
        type(self).instances.append(self)

    def request(self, method, target, body=None, headers=None):
        self.request_args = (method, target, body, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class PassengerWSGITest(unittest.TestCase):
    def setUp(self):
        FakeConnection.instances.clear()

    def test_stale_loopback_thread_is_replaced_before_oauth_request(self):
        old_server = mock.Mock()
        old_server.server_address = ("127.0.0.1", 1234)
        dead_thread = mock.Mock()
        dead_thread.is_alive.return_value = False
        new_server = mock.Mock()
        new_server.server_address = ("127.0.0.1", 5678)
        new_thread = mock.Mock()
        new_thread.is_alive.return_value = True
        with mock.patch.multiple(
            wsgi, _BACKEND_SERVER=old_server, _BACKEND_THREAD=dead_thread,
            _BACKEND_PID=9999,
        ), mock.patch("passenger_wsgi.os.getpid", return_value=9999), \
             mock.patch("passenger_wsgi.admin_server", create=True) as ignored:
            # admin_server is imported inside _ensure_backend; patch the real
            # module's setup functions to avoid touching customer databases.
            import admin_server
            with mock.patch.object(admin_server, "configure_internal_proxy"), \
                 mock.patch.object(admin_server, "initialize_runtime"), \
                 mock.patch("passenger_wsgi.ThreadingHTTPServer", return_value=new_server), \
                 mock.patch("passenger_wsgi.threading.Thread", return_value=new_thread), \
                 mock.patch("passenger_wsgi.os.chdir"), \
                 mock.patch("passenger_wsgi._runtime_initialization_lock",
                            return_value=contextlib.nullcontext()) as startup_lock:
                self.assertEqual(wsgi._ensure_backend(), ("127.0.0.1", 5678))
                startup_lock.assert_called_once()
                old_server.server_close.assert_called_once()
                new_thread.start.assert_called_once()
                self.assertEqual(wsgi._BACKEND_PID, 9999)

    def test_startup_lock_also_covers_admin_import_and_eager_security_db(self):
        import builtins
        import admin_server

        original_import = builtins.__import__
        active = []
        imported = []
        lock_dirs = []
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 4456)
        thread = mock.Mock()

        @contextlib.contextmanager
        def monitored_lock(directory):
            self.assertFalse(active)
            lock_dirs.append(Path(directory))
            active.append(True)
            try:
                yield
            finally:
                active.pop()

        def verify_import(name, *args, **kwargs):
            if name == "admin_server":
                imported.append(name)
                self.assertTrue(active, "admin_server imported before SQLite lock")
            return original_import(name, *args, **kwargs)

        def verify_initialize(*, background):
            self.assertFalse(background)
            self.assertTrue(active, "schema initializers outside SQLite lock")
            return {"coreReady": False}

        def verify_bind(*args, **kwargs):
            self.assertFalse(active, "lock held during loopback bind")
            return server

        with mock.patch.multiple(
            wsgi, _BACKEND_SERVER=None, _BACKEND_THREAD=None, _BACKEND_PID=None,
        ), mock.patch.dict(wsgi.os.environ, {"CYBERCHECK_DATA_DIR": "relative-runtime"}), \
             mock.patch("passenger_wsgi.os.getpid", return_value=9001), \
             mock.patch("passenger_wsgi.os.chdir"), \
             mock.patch("passenger_wsgi._runtime_initialization_lock",
                        side_effect=monitored_lock), \
             mock.patch("passenger_wsgi._runtime_release_marker_sha",
                        return_value="a" * 40), \
             mock.patch("passenger_wsgi._runtime_database_identities",
                        return_value={}), \
             mock.patch("passenger_wsgi.ThreadingHTTPServer",
                        side_effect=verify_bind), \
             mock.patch("passenger_wsgi.threading.Thread", return_value=thread), \
             mock.patch.object(admin_server, "configure_internal_proxy"), \
             mock.patch.object(admin_server, "initialize_runtime",
                               side_effect=verify_initialize):
            with mock.patch("builtins.__import__", side_effect=verify_import):
                self.assertEqual(wsgi._ensure_backend(), ("127.0.0.1", 4456))

        self.assertEqual(imported, ["admin_server"])
        self.assertEqual(lock_dirs, [wsgi._ROOT / "relative-runtime"])
        self.assertEqual(active, [])
        thread.start.assert_called_once()

    def test_live_loopback_is_reused_without_initializing_database(self):
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 4455)
        thread = mock.Mock()
        thread.is_alive.return_value = True
        with mock.patch.multiple(
            wsgi, _BACKEND_SERVER=server, _BACKEND_THREAD=thread,
            _BACKEND_PID=42,
        ), mock.patch("passenger_wsgi.os.getpid", return_value=42), \
             mock.patch("passenger_wsgi.ThreadingHTTPServer") as constructor:
            self.assertEqual(wsgi._ensure_backend(), ("127.0.0.1", 4455))
            constructor.assert_not_called()
            server.server_close.assert_not_called()

    def test_passenger_error_logs_no_sensitive_query_parameters(self):
        captured = {}
        def start(status, headers):
            captured["status"] = status
        with mock.patch("passenger_wsgi.migration_write_freeze.status",
                        return_value={"active": False}), \
             mock.patch("passenger_wsgi._ensure_backend",
                        side_effect=RuntimeError("private Google state secret")), \
             mock.patch("passenger_wsgi.sys.stderr", new_callable=io.StringIO) as log:
            result = wsgi.application({
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/auth/customer/google",
                "QUERY_STRING": "mobile=1&code_challenge=private-PKCE",
            }, start)
        self.assertEqual(captured["status"], "503 Service Unavailable")
        self.assertEqual(b"".join(result),
                         b'{"ok":false,"error":"passenger_bridge_failed"}')
        self.assertIn("stage=backend_start", log.getvalue())
        self.assertIn("class=RuntimeError", log.getvalue())
        self.assertNotIn("private", log.getvalue())
        self.assertNotIn("code_challenge", log.getvalue())

    def test_sqlite_failure_code_is_logged_without_private_error_message(self):
        import sqlite3
        captured = {}
        def start(status, headers):
            captured["status"] = status
        error = sqlite3.OperationalError("database path /private/customer.sqlite is locked")
        error.sqlite_errorname = "SQLITE_BUSY"
        with mock.patch("passenger_wsgi.migration_write_freeze.status",
                        return_value={"active": False}), \
             mock.patch("passenger_wsgi._ensure_backend", side_effect=error), \
             mock.patch("passenger_wsgi.sys.stderr", new_callable=io.StringIO) as log:
            body = b"".join(wsgi.application({
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/auth/customer/google",
            }, start))
        self.assertEqual(captured["status"], "503 Service Unavailable")
        self.assertIn(b"passenger_bridge_failed", body)
        self.assertIn("sqlite=SQLITE_BUSY", log.getvalue())
        self.assertNotIn("/private/", log.getvalue())
        self.assertNotIn("customer.sqlite", log.getvalue())

    def test_runtime_init_lock_creates_private_regular_file(self):
        with tempfile.TemporaryDirectory() as root:
            with wsgi._runtime_initialization_lock(root):
                lock = Path(root) / ".passenger-runtime-init.lock"
                self.assertTrue(lock.is_file())
                self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
            with wsgi._runtime_initialization_lock(root):
                pass

    def test_runtime_init_lock_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / ".passenger-runtime-init.lock"
            path.symlink_to(Path(root) / "target")
            with self.assertRaises(OSError):
                with wsgi._runtime_initialization_lock(root):
                    pass
            self.assertFalse((Path(root) / "target").exists())

    def test_runtime_init_lock_retries_sqlite_contention(self):
        with tempfile.TemporaryDirectory() as root:
            real_flock = wsgi.fcntl.flock
            attempts = []
            def temporary_busy(fd, operation):
                if operation & wsgi.fcntl.LOCK_NB and not attempts:
                    attempts.append(1)
                    raise BlockingIOError(errno.EAGAIN, "temporarily busy")
                return real_flock(fd, operation)
            with mock.patch("passenger_wsgi.fcntl.flock", side_effect=temporary_busy), \
                 mock.patch("passenger_wsgi.time.sleep") as sleep:
                with wsgi._runtime_initialization_lock(root):
                    pass
            self.assertEqual(len(attempts), 1)
            sleep.assert_called_once_with(0.05)

    def test_ready_marker_matches_exact_release_and_database_identity(self):
        with tempfile.TemporaryDirectory() as root:
            marker = wsgi._runtime_ready_marker(root)
            first = {"database-digest": [1, 100]}
            wsgi._write_runtime_marker(marker, "a" * 40, first)
            self.assertTrue(wsgi._runtime_marker_matches(marker, "a" * 40, first))
            self.assertFalse(wsgi._runtime_marker_matches(marker, "b" * 40, first))
            self.assertFalse(wsgi._runtime_marker_matches(
                marker, "a" * 40, {"database-digest": [1, 101]},
            ))
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)

    def test_ready_marker_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as root:
            marker = wsgi._runtime_ready_marker(root)
            target = Path(root) / "other"
            target.write_text('{"sha":"a"}')
            marker.symlink_to(target)
            self.assertFalse(wsgi._runtime_marker_matches(
                marker, "a" * 40, {"database-digest": [1, 100]},
            ))
            self.assertTrue(target.exists())

    def test_database_identity_invalidates_marker_after_database_replacement(self):
        import types
        with tempfile.TemporaryDirectory() as root:
            modules = []
            for index in range(6):
                db = Path(root) / f"db{index}.sqlite3"
                db.write_bytes(b"test")
                modules.append(types.SimpleNamespace(DB=db))
            runtime = types.SimpleNamespace(
                analytics=modules[0], referrals=modules[1],
                notifications=modules[2], mobile_devices=modules[3],
                reminder_dispatch=modules[4], booking=modules[5],
                booking_test=types.SimpleNamespace(), reviews=types.SimpleNamespace(),
                withdrawals=types.SimpleNamespace(),
                retention_enforcement=types.SimpleNamespace(),
                security=types.SimpleNamespace(),
                security_alerts=types.SimpleNamespace(),
            )
            first = wsgi._runtime_database_identities(runtime)
            self.assertEqual(len(first), 6)
            marker = wsgi._runtime_ready_marker(root)
            wsgi._write_runtime_marker(marker, "a" * 40, first)
            self.assertTrue(wsgi._runtime_marker_matches(marker, "a" * 40, first))
            old = modules[0].DB
            replacement = Path(root) / "replacement.sqlite3"
            replacement.write_bytes(b"new")
            replacement.replace(old)
            second = wsgi._runtime_database_identities(runtime)
            self.assertFalse(wsgi._runtime_marker_matches(marker, "a" * 40, second))

    def test_internal_headers_cannot_be_spoofed_by_request(self):
        headers = wsgi._request_headers({
            "REMOTE_ADDR": "203.0.113.42",
            "HTTP_HOST": "www.checkupauto.fr",
            "HTTP_X_CHECKUPAUTO_PROXY_TOKEN": "attacker",
            "HTTP_X_CHECKUPAUTO_CLIENT_IP": "127.0.0.1",
            "HTTP_CONNECTION": "keep-alive",
        })
        self.assertEqual(headers["X-CheckupAuto-Client-IP"], "203.0.113.42")
        self.assertEqual(headers["X-CheckupAuto-Proxy-Token"], wsgi._PROXY_TOKEN)
        self.assertNotEqual(headers["X-CheckupAuto-Proxy-Token"], "attacker")
        self.assertNotIn("Connection", headers)

    def test_invalid_remote_address_falls_back_to_loopback(self):
        self.assertEqual(
            wsgi._client_ip({"REMOTE_ADDR": "not-an-ip"}),
            "127.0.0.1",
        )

    def test_request_target_preserves_query_without_using_shell(self):
        target = wsgi._request_target({
            "PATH_INFO": "/api/mobile/bootstrap",
            "QUERY_STRING": "a=1&b=2",
        })
        self.assertEqual(target, "/api/mobile/bootstrap?a=1&b=2")

    def test_body_length_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "volumineux"):
            wsgi._request_body({
                "CONTENT_LENGTH": "131073",
                "wsgi.input": io.BytesIO(b""),
            })

    def test_truncated_body_is_rejected_before_loopback_request(self):
        with self.assertRaisesRegex(ValueError, "incomplet"):
            wsgi._request_body({
                "CONTENT_LENGTH": "5",
                "wsgi.input": io.BytesIO(b"abc"),
            })

    def test_positive_body_length_requires_wsgi_input(self):
        with self.assertRaisesRegex(ValueError, "flux WSGI absent"):
            wsgi._request_body({"CONTENT_LENGTH": "1"})

    def test_client_content_length_is_not_forwarded_verbatim(self):
        headers = wsgi._request_headers({
            "HTTP_CONTENT_LENGTH": "999999",
            "CONTENT_LENGTH": "3",
            "HTTP_HOST": "www.checkupauto.fr",
        })
        self.assertNotIn("Content-Length", headers)

    @mock.patch("passenger_wsgi._ensure_backend", return_value=("127.0.0.1", 12345))
    @mock.patch("passenger_wsgi.http.client.HTTPConnection", FakeConnection)
    def test_application_proxies_request_and_filters_response_headers(self, _backend):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        result = wsgi.application({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/",
            "QUERY_STRING": "",
            "REMOTE_ADDR": "198.51.100.12",
            "HTTP_HOST": "www.checkupauto.fr",
            "wsgi.input": io.BytesIO(b""),
        }, start_response)

        body = b"".join(result)
        self.assertEqual(body, b"hello")
        self.assertEqual(captured["status"], "200 OK")
        self.assertNotIn(
            "connection",
            {name.lower() for name, _value in captured["headers"]},
        )
        connection = FakeConnection.instances[-1]
        self.assertTrue(connection.closed)
        method, target, request_body, headers = connection.request_args
        self.assertEqual(method, "GET")
        self.assertEqual(target, "/")
        self.assertEqual(request_body, b"")
        self.assertEqual(headers["X-CheckupAuto-Client-IP"], "198.51.100.12")

    def test_migration_freeze_rejects_mutating_request_before_backend(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        with mock.patch(
            "passenger_wsgi.migration_write_freeze.status",
            return_value={"active":True,"valid":True,"state":"frozen"},
        ), mock.patch("passenger_wsgi._ensure_backend") as backend:
            result=wsgi.application({
                "REQUEST_METHOD":"POST",
                "PATH_INFO":"/contact",
                "CONTENT_LENGTH":"999999999",
                "REMOTE_ADDR":"203.0.113.8",
            },start_response)
        body=b"".join(result)
        backend.assert_not_called()
        self.assertEqual(captured["status"],"503 Service Unavailable")
        self.assertEqual(captured["headers"]["Retry-After"],"120")
        self.assertEqual(captured["headers"]["X-CheckupAuto-Migration-Freeze"],"active")
        self.assertIn(b"migration_write_frozen",body)

    def test_migration_freeze_keeps_only_explicit_read_only_surface(self):
        with mock.patch(
            "passenger_wsgi.migration_write_freeze.status",
            return_value={"active":True,"valid":True,"state":"frozen"},
        ):
            for method,path in (("GET","/"),("HEAD","/cgv"),("OPTIONS","/contact")):
                with self.subTest(method=method,path=path):
                    self.assertIsNone(wsgi._write_freeze_response(
                        {"REQUEST_METHOD":method,"PATH_INFO":path},
                        lambda _status,_headers: None,
                    ))

    def test_migration_freeze_rejects_transactional_get_before_backend(self):
        captured={}
        def start_response(status,headers):
            captured["status"]=status
            captured["headers"]=dict(headers)
        with mock.patch(
            "passenger_wsgi.migration_write_freeze.status",
            return_value={"active":True,"valid":True,"state":"frozen"},
        ), mock.patch("passenger_wsgi._ensure_backend") as backend:
            result=wsgi.application({
                "REQUEST_METHOD":"GET",
                "PATH_INFO":"/go/booking",
                "REMOTE_ADDR":"203.0.113.8",
            },start_response)
        backend.assert_not_called()
        self.assertEqual(captured["status"],"503 Service Unavailable")
        self.assertIn(b"migration_write_frozen",b"".join(result))

    def test_bootstrap_fast_path_matches_canonical_payload_without_backend(self):
        import json
        import mobile_bootstrap
        import site_config_store

        expected = mobile_bootstrap.status(site_config_store.load())
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                response = {}
                def start(status, headers):
                    response["status"] = status
                    response["headers"] = dict(headers)
                with mock.patch(
                    "passenger_wsgi.migration_write_freeze.status",
                    return_value={"active": False},
                ), mock.patch("passenger_wsgi._ensure_backend") as backend:
                    result = wsgi.application({
                        "REQUEST_METHOD": method,
                        "PATH_INFO": "/api/mobile/bootstrap",
                        "REMOTE_ADDR": "203.0.113.5",
                    }, start)
                backend.assert_not_called()
                self.assertEqual(response["status"], "200 OK")
                self.assertEqual(response["headers"]["Cache-Control"], "no-store")
                self.assertEqual(response["headers"]["X-Content-Type-Options"], "nosniff")
                body = b"".join(result)
                if method == "GET":
                    self.assertEqual(json.loads(body), expected)
                else:
                    self.assertEqual(body, b"")

    def test_bootstrap_freeze_precedence_and_post_fallback(self):
        for method in ("GET", "POST"):
            with self.subTest(method=method):
                response = {}
                def start(status, headers):
                    response["status"] = status
                with mock.patch(
                    "passenger_wsgi.migration_write_freeze.status",
                    return_value={"active": True, "valid": True},
                ), mock.patch("passenger_wsgi.migration_write_freeze.request_allowed",
                              return_value=False), mock.patch("passenger_wsgi._ensure_backend") as backend:
                    body = b"".join(wsgi.application({
                        "REQUEST_METHOD": method,
                        "PATH_INFO": "/api/mobile/bootstrap",
                    }, start))
                self.assertEqual(response["status"], "503 Service Unavailable")
                self.assertIn(b"migration_write_frozen", body)
                backend.assert_not_called()

    def test_bootstrap_invalid_config_fails_closed_without_backend(self):
        captured = {}
        def start(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        with mock.patch("passenger_wsgi.migration_write_freeze.status",
                        return_value={"active": False}), mock.patch(
                            "site_config_store.load", side_effect=ValueError("invalid")
                        ), mock.patch("passenger_wsgi._ensure_backend") as backend:
            body = b"".join(wsgi.application({
                "REQUEST_METHOD": "GET",
                "PATH_INFO": "/api/mobile/bootstrap",
            }, start))
        backend.assert_not_called()
        self.assertEqual(captured["status"], "503 Service Unavailable")
        self.assertEqual(captured["headers"]["Cache-Control"], "no-store")
        self.assertNotIn(b"invalid", body)
        self.assertIn(b"mobile_bootstrap_unavailable", body)

    def test_invalid_wsgi_request_returns_sanitized_400(self):
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        with mock.patch("passenger_wsgi._ensure_backend", return_value=("127.0.0.1", 12345)):
            result = wsgi.application({
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/api/events",
                "CONTENT_LENGTH": "invalid",
                "REMOTE_ADDR": "203.0.113.8",
                "wsgi.input": io.BytesIO(b""),
            }, start_response)
        body = b"".join(result)
        self.assertEqual(captured["status"], "400 Bad Request")
        self.assertIn(b"invalid_wsgi_request", body)


if __name__ == "__main__":
    unittest.main()
