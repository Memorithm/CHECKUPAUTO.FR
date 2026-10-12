import base64
import json
import socket
import unittest
from dataclasses import replace
from unittest.mock import patch

import payment_payline_config as payline


def fixture():
    # Explicitly synthetic; no merchant contract/account identifier is used.
    return {"environment": "sandbox", "merchantId": "00000012345678",
            "accessKey": "synthetic-fixture-key:+/=_-", "contractNumber": "TEST_CONTRACT_01",
            "publicOrigin": "https://sandbox.example"}


class PaylineConfigurationTest(unittest.TestCase):
    def test_explicit_api_fields_are_accepted_without_normalizing_identifiers(self):
        config = payline.PaylineSandboxConfig.from_mapping(fixture())
        self.assertEqual(config.merchant_id, "00000012345678")
        self.assertEqual(config.contract_number, "TEST_CONTRACT_01")
        self.assertEqual(config.environment, "sandbox")

    def test_acquiring_sheet_never_becomes_api_configuration(self):
        values = {"platform": "Payline Monext", "TPE": "1111111", "BIN": "11111111111",
                  "NLSA": "999", "Merchant ID MC": "1111111", "currency": "EUR"}
        with self.assertRaisesRegex(payline.PaylineConfigurationError, "^payline_explicit_api_fields_required$"):
            payline.PaylineSandboxConfig.from_mapping(values)

    def test_missing_api_fields_are_not_inferred(self):
        for name in payline.REQUIRED_FIELDS:
            values = fixture(); del values[name]
            with self.subTest(field=name), self.assertRaises(payline.PaylineConfigurationError):
                payline.PaylineSandboxConfig.from_mapping(values)

    def test_aliases_and_endpoint_overrides_are_refused(self):
        for name in ("TPE", "merchantID", "bankCode", "Merchant ID MC", "endpoint", "live"):
            values = {**fixture(), name: "private-submitted-value"}
            with self.subTest(field=name), self.assertRaises(payline.PaylineConfigurationError) as caught:
                payline.PaylineSandboxConfig.from_mapping(values)
            self.assertNotIn("private-submitted-value", str(caught.exception))

    def test_ambiguous_environment_is_refused(self):
        for environment in ("live", "prod", "homologation", "Sandbox", "Production", "", True, None):
            with self.subTest(environment=environment), self.assertRaises(payline.PaylineConfigurationError):
                payline.PaylineSandboxConfig.from_mapping({**fixture(), "environment": environment})

    def test_invalid_input_types_are_refused(self):
        for values in (None, [], True, "input"):
            with self.subTest(values=values), self.assertRaises(payline.PaylineConfigurationError):
                payline.PaylineSandboxConfig.from_mapping(values)
        for name in ("merchantId", "accessKey", "contractNumber", "publicOrigin"):
            for value in (True, 123, None):
                with self.subTest(field=name, value=value), self.assertRaises(payline.PaylineConfigurationError):
                    payline.PaylineSandboxConfig.from_mapping({**fixture(), name: value})

    def test_empty_oversized_and_control_character_values_are_refused(self):
        cases = {"merchantId": ["", "1" * 33, "1:2", " 123", "123\n"],
                 "accessKey": ["", "x" * 257, "secret\r\nInjected:value", "white space", "clé"],
                 "contractNumber": ["", "x" * 21, "../contract", "contract\x00" ]}
        for name, invalid in cases.items():
            for value in invalid:
                with self.subTest(field=name, value=value), self.assertRaises(payline.PaylineConfigurationError):
                    payline.PaylineSandboxConfig.from_mapping({**fixture(), name: value})

    def test_public_origin_must_be_a_clean_https_origin(self):
        for origin in ("http://sandbox.example", "https://user:key@sandbox.example", "https://sandbox.example/path",
                       "https://sandbox.example?query", "https://sandbox.example#fragment", "https://sandbox.example?",
                       "https://sandbox.example:", "https://sandbox.example:1234", "https://[bad",
                       "https://sandbox.example\n", "https://sand\\box.example", "https://-bad.example"):
            with self.subTest(origin=origin), self.assertRaises(payline.PaylineConfigurationError):
                payline.PaylineSandboxConfig.from_mapping({**fixture(), "publicOrigin": origin})
        for origin in ("https://sandbox.example", "https://sandbox.example/", "https://sandbox.example:443"):
            payline.PaylineSandboxConfig.from_mapping({**fixture(), "publicOrigin": origin})

    def test_endpoint_follows_explicit_environment(self):
        config = payline.PaylineSandboxConfig.from_mapping(fixture())
        self.assertEqual(config.webpayment_endpoint, "https://homologation.payline.com/V4/services/WebPaymentAPI")
        self.assertEqual(config.directpayment_endpoint, "https://homologation.payline.com/V4/services/DirectPaymentAPI")
        live = replace(config, environment="production")
        self.assertEqual(live.webpayment_endpoint, "https://services.payline.com/V4/services/WebPaymentAPI")
        self.assertEqual(live.directpayment_endpoint, "https://services.payline.com/V4/services/DirectPaymentAPI")
        self.assertEqual(payline.preflight(live)["providerEnvironment"], "production")

    def test_authentication_uses_api_merchant_id_not_contract_number(self):
        config = payline.PaylineSandboxConfig.from_mapping(fixture())
        scheme, value = config.authentication_headers()["Authorization"].split(" ", 1)
        self.assertEqual(scheme, "Basic")
        self.assertEqual(base64.b64decode(value).decode("ascii"), fixture()["merchantId"] + ":" + fixture()["accessKey"])
        self.assertNotIn(config.contract_number, base64.b64decode(value).decode("ascii"))

    def test_repr_and_preflight_do_not_expose_credentials_or_identifiers(self):
        config = payline.PaylineSandboxConfig.from_mapping(fixture())
        report = repr(config) + json.dumps(payline.preflight(config))
        for name in ("merchantId", "accessKey", "contractNumber", "publicOrigin"):
            self.assertNotIn(fixture()[name], report)
        self.assertNotIn(config.authentication_headers()["Authorization"], report)

    def test_well_formed_configuration_does_not_open_any_operational_gate(self):
        report = payline.preflight(payline.PaylineSandboxConfig.from_mapping(fixture()))
        self.assertTrue(report["configurationSyntaxValid"])
        self.assertTrue(report["transportImplemented"])
        self.assertTrue(report["httpCallbacksBound"])
        self.assertTrue(report["checkoutBound"])
        for gate in ("credentialsVerified", "contractBindingVerified",
                     "livePaymentsEnabled", "ready"):
            self.assertIs(report[gate], False)
        self.assertEqual(report["provider"], "payline")
        self.assertIn("contract_binding_unverified", report["blockingReasons"])
        self.assertNotIn("checkout_not_bound", report["blockingReasons"])

    def test_missing_configuration_is_explicit_and_does_not_use_environment(self):
        with patch.dict("os.environ", {"PAYLINE_MERCHANT_ID": "123456789", "PAYLINE_ACCESS_KEY": "fixture"}):
            report = payline.preflight()
        self.assertFalse(report["configurationSyntaxValid"])
        self.assertIn("explicit_api_configuration_missing", report["blockingReasons"])
        with self.assertRaises(payline.PaylineConfigurationError):
            payline.preflight(fixture())

    def test_preflight_has_no_network_side_effect(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            config = payline.PaylineSandboxConfig.from_mapping(fixture())
            payline.preflight(config)
            config.authentication_headers()


if __name__ == "__main__":
    unittest.main()
