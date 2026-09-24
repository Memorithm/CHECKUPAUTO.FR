import unittest
from unittest import mock

import production_readiness as readiness


CANONICAL = "https://www.checkupauto.fr/"


def _config(*, indexing_enabled=None, canonical=CANONICAL):
    seo = {"canonicalUrl": canonical}
    if indexing_enabled is not None:
        seo["indexingEnabled"] = indexing_enabled
    return {"seo": seo}


class ProductionReadinessPublicSurfaceTest(unittest.TestCase):
    def test_invalid_canonical_fails_without_network(self):
        with mock.patch.object(readiness.public_surface_provenance, "probe") as probe:
            item = readiness._public_site(
                _config(indexing_enabled=True, canonical="https://rdv.checkupauto.fr/")
            )
        probe.assert_not_called()
        self.assertEqual(item["state"], "degraded")
        self.assertTrue(item["critical"])
        self.assertFalse(item["metrics"]["canonicalValid"])
        self.assertTrue(item["metrics"]["activationRequested"])
        self.assertEqual(item["metrics"]["publicSurfaceProbeState"], "canonical_url_invalid")
        self.assertFalse(item["metrics"]["publicSurfaceVerified"])

    def test_probe_is_deferred_before_public_activation(self):
        with mock.patch.object(readiness.public_surface_provenance, "probe") as probe:
            item = readiness._public_site(_config(indexing_enabled=False))
        probe.assert_not_called()
        self.assertEqual(item["state"], "ready")
        self.assertTrue(item["critical"])
        self.assertTrue(item["metrics"]["canonicalValid"])
        self.assertFalse(item["metrics"]["activationRequested"])
        self.assertEqual(item["metrics"]["publicSurfaceProbeState"], "deferred")
        self.assertFalse(item["metrics"]["publicSurfaceVerified"])

    def test_verified_surface_is_ready_for_activation(self):
        with mock.patch.object(
            readiness.public_surface_provenance,
            "probe",
            return_value={"ok": True, "state": "verified"},
        ) as probe:
            item = readiness._public_site(_config(indexing_enabled=True))
        probe.assert_called_once_with(CANONICAL)
        self.assertEqual(item["state"], "ready")
        self.assertTrue(item["metrics"]["activationRequested"])
        self.assertEqual(item["metrics"]["publicSurfaceProbeState"], "verified")
        self.assertTrue(item["metrics"]["publicSurfaceVerified"])

    def test_redirected_surface_blocks_activation(self):
        with mock.patch.object(
            readiness.public_surface_provenance,
            "probe",
            return_value={"ok": False, "state": "redirected"},
        ):
            item = readiness._public_site(_config(indexing_enabled=True))
        self.assertEqual(item["state"], "degraded")
        self.assertEqual(item["metrics"]["publicSurfaceProbeState"], "redirected")
        self.assertFalse(item["metrics"]["publicSurfaceVerified"])

    def test_probe_exception_is_fail_closed_and_sanitized(self):
        secret = "PRIVATE_TOKEN=do-not-leak"
        with mock.patch.object(
            readiness.public_surface_provenance,
            "probe",
            side_effect=RuntimeError(secret),
        ):
            item = readiness._public_site(_config(indexing_enabled=True))
        self.assertEqual(item["state"], "degraded")
        self.assertEqual(item["metrics"]["publicSurfaceProbeState"], "probe_error")
        self.assertNotIn(secret, repr(item))

    def test_unknown_probe_state_is_sanitized(self):
        secret = "PRIVATE_TOKEN=do-not-leak"
        with mock.patch.object(
            readiness.public_surface_provenance,
            "probe",
            return_value={"ok": False, "state": secret},
        ):
            item = readiness._public_site(_config(indexing_enabled=True))
        self.assertEqual(item["state"], "degraded")
        self.assertEqual(item["metrics"]["publicSurfaceProbeState"], "invalid_probe_result")
        self.assertNotIn(secret, repr(item))


if __name__ == "__main__":
    unittest.main()
