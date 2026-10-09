import contextlib
import unittest
from unittest.mock import patch, Mock
import mercure_vl_provider_metadata_resolver as resolver


class Tests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        observed = {"centre_type": ["1"], "utilisateur": ["464"]}
        catalog = {"1763": {"duration": "40", "label": "TOUT VEHICULE HORS CAMPING CAR"}}
        for target, name, value in (
            (resolver.mercure_vl_live_metadata_options, "fetch", observed),
            (resolver.mercure, "_session", Mock()),
            (resolver.mercure, "_check_auth", Mock(text="catalog")),
            (resolver.mercure_vl_embedded_service_catalog, "extract", catalog),
        ):
            self.stack.enter_context(patch.object(target, name, return_value=value))

    def resolve(self, **kwargs):
        return resolver.resolve(service="technical", line_id="454", operator_id="464", **kwargs)

    def test_missing_line_evidence_remains_fail_closed(self):
        with self.assertRaisesRegex(resolver.MercureVlMetadataResolutionError, "line_evidence_required"):
            self.resolve()

    def test_line_without_availability_is_rejected(self):
        with self.assertRaisesRegex(resolver.MercureVlMetadataResolutionError, "slot_evidence_required"):
            self.resolve(line_evidence={"observed": True, "lineId": "454", "slotAvailable": False})

    def test_different_line_is_rejected(self):
        with self.assertRaisesRegex(resolver.MercureVlMetadataResolutionError, "slot_evidence_required"):
            self.resolve(line_evidence={"observed": True, "lineId": "455", "slotAvailable": True})

    def test_truthy_values_cannot_replace_boolean_evidence(self):
        for key in ("observed", "slotAvailable"):
            for value in (1, "true", [], None):
                with self.subTest(key=key, value=value):
                    evidence = {"observed": True, "lineId": "454", "slotAvailable": True}
                    evidence[key] = value
                    with self.assertRaises(resolver.MercureVlMetadataResolutionError):
                        self.resolve(line_evidence=evidence)

    def test_qualified_server_evidence_preserves_provider_metadata(self):
        result = self.resolve(line_evidence={"observed": True, "lineId": "454", "slotAvailable": True})
        self.assertEqual(result["metadata"]["line_id"], "454")
        self.assertEqual(result["metadata"]["service_id"], "1763")
        self.assertEqual(result["metadata"]["duration"], "40")
        self.assertNotIn("bookingEnabled", result)
