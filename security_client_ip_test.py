import os
import unittest
from unittest.mock import patch

import security_guard as security


class SecurityClientIpTest(unittest.TestCase):
    """S-04: forwarding headers are honoured only from configured trusted proxies."""

    def env(self, **values):
        clean = {k: v for k, v in values.items() if v is not None}
        ctx = patch.dict(os.environ, clean, clear=False)
        ctx.start(); self.addCleanup(ctx.stop)
        for key in (security.TRUSTED_PROXIES_ENV, security.CLIENT_IP_HEADER_ENV):
            if key not in clean:
                os.environ.pop(key, None)

    def test_direct_client_cannot_choose_its_identity_with_headers(self):
        self.env()
        for headers in (
            {"CF-Connecting-IP": "198.51.100.7"},
            {"X-Forwarded-For": "198.51.100.8"},
            {"CF-Connecting-IP": "198.51.100.9", "X-Forwarded-For": "198.51.100.10"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(security.client_ip(headers, "203.0.113.5"), "203.0.113.5")

    def test_spoofed_headers_do_not_produce_distinct_rate_limit_buckets(self):
        self.env()
        ips = {security.client_ip({"CF-Connecting-IP": f"198.51.100.{n}"}, "203.0.113.5") for n in range(1, 20)}
        self.assertEqual(ips, {"203.0.113.5"})

    def test_local_cloudflare_tunnel_connector_is_trusted_by_default(self):
        self.env()
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "198.51.100.7"}, "127.0.0.1"), "198.51.100.7")
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "2001:db8::1"}, "::1"), "2001:db8::1")
        # X-Forwarded-For is not the configured header by default.
        self.assertEqual(security.client_ip({"X-Forwarded-For": "198.51.100.7"}, "127.0.0.1"), "127.0.0.1")
        # Garbage in the trusted header falls back to the peer.
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "not-an-ip"}, "127.0.0.1"), "127.0.0.1")

    def test_trust_can_be_disabled_entirely(self):
        self.env(**{security.TRUSTED_PROXIES_ENV: "none"})
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "198.51.100.7"}, "127.0.0.1"), "127.0.0.1")
        self.env(**{security.TRUSTED_PROXIES_ENV: "10.0.0.0/8", security.CLIENT_IP_HEADER_ENV: "none"})
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "198.51.100.7"}, "10.1.2.3"), "10.1.2.3")

    def test_reverse_proxy_x_forwarded_for_uses_rightmost_entry(self):
        self.env(**{security.TRUSTED_PROXIES_ENV: "172.16.0.0/12", security.CLIENT_IP_HEADER_ENV: "x-forwarded-for"})
        headers = {"X-Forwarded-For": "1.1.1.1, 198.51.100.44", "CF-Connecting-IP": "9.9.9.9"}
        self.assertEqual(security.client_ip(headers, "172.18.0.4"), "198.51.100.44")
        # Same headers from an untrusted peer are ignored.
        self.assertEqual(security.client_ip(headers, "203.0.113.5"), "203.0.113.5")

    def test_invalid_configuration_entries_are_ignored(self):
        self.env(**{security.TRUSTED_PROXIES_ENV: "bogus, 10.0.0.0/8", security.CLIENT_IP_HEADER_ENV: "x-real-ip"})
        self.assertEqual(len(security.trusted_proxy_networks()), 1)
        self.assertEqual(security.client_ip_header(), "none")
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "198.51.100.7"}, "10.0.0.2"), "10.0.0.2")

    def test_missing_peer_never_trusts_headers(self):
        self.env()
        self.assertEqual(security.client_ip({"CF-Connecting-IP": "198.51.100.7"}, ""), "unknown")


if __name__ == "__main__":
    unittest.main()
