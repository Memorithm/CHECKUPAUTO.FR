import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

import booking_signoff_evidence as signoff
import customer_booking_activation_evidence
import in_site_booking_readiness as readiness
import mercure_step5_customer_journey
import mercure_step6_production_signoff

KEY = b"k" * 48
NOW = dt.datetime(2026, 10, 11, 9, 0, tzinfo=dt.timezone.utc)


def document(**overrides):
    doc = {
        "schema": signoff.SCHEMA,
        "issuedAt": "2026-10-10T08:00:00+00:00",
        "expiresAt": "2026-11-10T08:00:00+00:00",
        "approvedBy": "Tarek Zekriti",
        "provider": {"lineId": "454", "operatorId": "464"},
        "step5": {key: True for key in mercure_step5_customer_journey.REQUIRED},
        "step6": {key: True for key in mercure_step6_production_signoff.REQUIRED},
        "activation": {key: True for key in customer_booking_activation_evidence.REQUIRED},
    }
    doc.update(overrides)
    doc["signature"] = signoff.compute_signature(doc, KEY)
    return doc


class SignoffVerifyTest(unittest.TestCase):
    def verify(self, doc, **kw):
        return signoff.verify(doc, key=KEY, line_id=kw.get("line", "454"),
                              operator_id=kw.get("operator", "464"), now=kw.get("now", NOW))

    def test_complete_signed_document_is_valid(self):
        self.assertTrue(self.verify(document())["valid"])

    def test_tampered_document_is_rejected(self):
        doc = document()
        doc["step6"]["rollback"] = False
        with self.assertRaisesRegex(signoff.BookingSignoffError, "signature"):
            self.verify(doc)

    def test_wrong_key_is_rejected(self):
        doc = document()
        with self.assertRaisesRegex(signoff.BookingSignoffError, "signature"):
            signoff.verify(doc, key=b"x" * 48, line_id="454", operator_id="464", now=NOW)

    def test_incomplete_checklists_are_rejected_even_when_signed(self):
        for section, module in (("step5", mercure_step5_customer_journey),
                                ("step6", mercure_step6_production_signoff),
                                ("activation", customer_booking_activation_evidence)):
            values = {key: True for key in module.REQUIRED}
            values[module.REQUIRED[0]] = False
            with self.subTest(section=section):
                with self.assertRaisesRegex(signoff.BookingSignoffError, section + "_incomplete"):
                    self.verify(document(**{section: values}))

    def test_expired_and_future_documents_are_rejected(self):
        with self.assertRaisesRegex(signoff.BookingSignoffError, "expired"):
            self.verify(document(), now=dt.datetime(2026, 11, 10, 8, 0, tzinfo=dt.timezone.utc))
        with self.assertRaisesRegex(signoff.BookingSignoffError, "not_yet_valid"):
            self.verify(document(), now=dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc))

    def test_validity_window_is_bounded(self):
        with self.assertRaisesRegex(signoff.BookingSignoffError, "dates"):
            self.verify(document(expiresAt="2027-06-01T00:00:00+00:00"))

    def test_evidence_is_bound_to_configured_line_and_operator(self):
        with self.assertRaisesRegex(signoff.BookingSignoffError, "provider_mismatch"):
            self.verify(document(), line="455")
        with self.assertRaisesRegex(signoff.BookingSignoffError, "provider_mismatch"):
            self.verify(document(), operator="1")

    def test_unknown_or_missing_fields_are_rejected(self):
        doc = document()
        doc["extra"] = True
        with self.assertRaisesRegex(signoff.BookingSignoffError, "invalid"):
            self.verify(doc)
        doc = document()
        del doc["approvedBy"]
        with self.assertRaisesRegex(signoff.BookingSignoffError, "invalid"):
            self.verify(doc)

    def test_non_boolean_checklist_values_are_rejected(self):
        values = {key: True for key in mercure_step6_production_signoff.REQUIRED}
        values["monitoring"] = "true"
        with self.assertRaisesRegex(signoff.BookingSignoffError, "step6"):
            self.verify(document(step6=values))

    def test_short_key_is_refused(self):
        with self.assertRaises(signoff.BookingSignoffError):
            signoff.compute_signature(document(), b"short")


class ReadinessFromConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = {
            "CYBERCHECK_PRIVATE_DIR": str(self.dir),
            "CHECKUPAUTO_IN_SITE_BOOKING_ENABLED": "true",
            "CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED": "true",
            "CHECKUPAUTO_MERCURE_VL_LINE_ID": "454",
            "CHECKUPAUTO_MERCURE_VL_OPERATOR_ID": "464",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def write_evidence(self, doc=None, key=KEY, mode=0o600):
        (self.dir / signoff.DEFAULT_FILE_NAME).write_text(json.dumps(doc or document()))
        key_path = self.dir / signoff.DEFAULT_KEY_NAME
        key_path.write_bytes(key)
        os.chmod(key_path, mode)

    def test_default_environment_is_closed(self):
        status = readiness.public_status(environ={}, now=NOW)
        self.assertFalse(status["bookingEnabled"])
        self.assertIn("real_mercure_booking_connector_unqualified", status["blockers"])
        self.assertEqual(readiness.declared_capabilities(environ={}), readiness.BookingCapabilities())

    def test_flags_without_evidence_stay_closed(self):
        status = readiness.public_status(environ=self.env, now=NOW)
        self.assertFalse(status["bookingEnabled"])
        state = readiness.activation_state(self.env, NOW)
        self.assertEqual(state["signoffReason"], "booking_signoff_missing")

    def test_valid_evidence_and_all_flags_enable(self):
        self.write_evidence()
        status = readiness.public_status(environ=self.env, now=NOW)
        self.assertTrue(status["bookingEnabled"])
        self.assertEqual(status["blockers"], [])
        self.assertFalse(status["externalMercureRedirectAllowed"])

    def test_each_flag_is_required(self):
        self.write_evidence()
        for name, value in (("CHECKUPAUTO_IN_SITE_BOOKING_ENABLED", "false"),
                            ("CHECKUPAUTO_IN_SITE_BOOKING_ENABLED", "1"),
                            ("CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED", ""),
                            ("CHECKUPAUTO_MERCURE_VL_LINE_ID", "455"),
                            ("CHECKUPAUTO_MERCURE_VL_OPERATOR_ID", "abc")):
            with self.subTest(name=name, value=value):
                env = {**self.env, name: value}
                self.assertFalse(readiness.public_status(environ=env, now=NOW)["bookingEnabled"])

    def test_group_readable_key_is_refused(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions")
        self.write_evidence(mode=0o644)
        self.assertFalse(readiness.public_status(environ=self.env, now=NOW)["bookingEnabled"])
        self.assertEqual(readiness.activation_state(self.env, NOW)["signoffReason"],
                         "booking_signoff_key_permissions_invalid")

    def test_expired_evidence_closes_again(self):
        self.write_evidence()
        later = dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc)
        self.assertFalse(readiness.public_status(environ=self.env, now=later)["bookingEnabled"])

    def test_payment_capabilities_are_never_claimed(self):
        self.write_evidence()
        caps = readiness.declared_capabilities(self.env, NOW)
        self.assertFalse(caps.payment_required)
        self.assertFalse(caps.embedded_payment_qualified)
        self.assertFalse(caps.payment_result_verified)

    def test_verifier_never_writes_files(self):
        before = sorted(p.name for p in self.dir.iterdir())
        readiness.public_status(environ=self.env, now=NOW)
        self.assertEqual(before, sorted(p.name for p in self.dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
