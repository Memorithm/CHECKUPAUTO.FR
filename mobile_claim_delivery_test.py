import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlparse, parse_qs
import xml.etree.ElementTree as ET

import mobile_claim_delivery as delivery
import mobile_devices
import reminder_dispatch


class MobileClaimDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_mobile = (mobile_devices.DATA_DIR, mobile_devices.DB)
        self.old_reminder = (reminder_dispatch.DATA_DIR, reminder_dispatch.DB)
        mobile_devices.DATA_DIR = root / "mobile"
        mobile_devices.DB = mobile_devices.DATA_DIR / "mobile.sqlite3"
        reminder_dispatch.DATA_DIR = root / "reminder"
        reminder_dispatch.DB = reminder_dispatch.DATA_DIR / "reminder.sqlite3"
        self.config = {"seo": {"canonicalUrl": "https://www.checkupauto.fr/"}}
        reminder_dispatch.init_db()
        reminder_dispatch._upsert([
            {
                "vehicleId": "vehicle-77",
                "clientKind": "account",
                "clientId": "client-42",
                "dueDate": "2027-03-15",
                "appointmentId": "rdv-12",
            }
        ])
        self.env = mock.patch.dict(
            os.environ, {delivery.APP_ID_PREFIX_ENV: "ABCDE12345"}, clear=False
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        mobile_devices.DATA_DIR, mobile_devices.DB = self.old_mobile
        reminder_dispatch.DATA_DIR, reminder_dispatch.DB = self.old_reminder
        self.tmp.cleanup()

    def test_aasa_is_scoped_to_claim_path_and_real_bundle_identifier(self):
        state = delivery.status(self.config)
        self.assertTrue(state["ready"])
        self.assertEqual(
            state["appIdentifier"], "ABCDE12345.fr.checkupauto.reminder"
        )
        body = json.loads(delivery.association_document(self.config))
        detail = body["applinks"]["details"][0]
        self.assertEqual(
            detail["appIDs"], ["ABCDE12345.fr.checkupauto.reminder"]
        )
        self.assertEqual(detail["components"][0]["/"], "/app/claim")

    def test_issue_uses_authoritative_inventory_and_keeps_raw_claim_hash_only(self):
        claim = delivery.issue_for_vehicle(self.config, "vehicle-77", 900)
        self.assertEqual(
            set(claim),
            {"vehicleId", "dueDate", "claimUrl", "expiresAt", "qrDataUrl"},
        )
        self.assertEqual(claim["vehicleId"], "vehicle-77")
        parsed = urlparse(claim["claimUrl"])
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "www.checkupauto.fr")
        self.assertEqual(parsed.path, "/app/claim")
        token = parse_qs(parsed.fragment)["token"][0]
        with mobile_devices.connect() as db:
            row = db.execute(
                "SELECT token_hash,client_id FROM mobile_vehicle_claim"
            ).fetchone()
        self.assertEqual(
            row["token_hash"], hashlib.sha256(token.encode()).hexdigest()
        )
        self.assertNotEqual(row["token_hash"], token)
        self.assertNotIn("client-42", json.dumps(claim))

        prefix = "data:image/svg+xml;base64,"
        self.assertTrue(claim["qrDataUrl"].startswith(prefix))
        svg = base64.b64decode(claim["qrDataUrl"][len(prefix):])
        ET.fromstring(svg)

    def test_unknown_vehicle_cannot_create_claim(self):
        with self.assertRaises(LookupError):
            delivery.issue_for_vehicle(self.config, "vehicle-404")
        self.assertEqual(mobile_devices.status()["pendingClaims"], 0)

    def test_missing_app_identifier_prefix_blocks_customer_qr_issuance(self):
        with mock.patch.dict(
            os.environ, {delivery.APP_ID_PREFIX_ENV: ""}, clear=False
        ):
            self.assertFalse(delivery.status(self.config)["ready"])
            with self.assertRaises(RuntimeError):
                delivery.association_document(self.config)
            with self.assertRaises(RuntimeError):
                delivery.issue_for_vehicle(self.config, "vehicle-77")

    def test_candidates_do_not_expose_customer_identifier(self):
        rows = delivery.candidates(10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["vehicleId"], "vehicle-77")
        self.assertEqual(rows[0]["appointmentId"], "rdv-12")
        self.assertNotIn("clientId", rows[0])
        self.assertNotIn("clientKind", rows[0])

    def test_claim_landing_does_not_read_or_forward_fragment(self):
        page = delivery.claim_landing_html(self.config).decode()
        self.assertIn(
            'name="robots" content="noindex,nofollow,noarchive"', page
        )
        self.assertIn("name=\"referrer\" content=\"no-referrer\"", page)
        self.assertIn("/app?src=claim", page)
        self.assertNotIn("location.hash", page)
        self.assertNotIn("/api/events", page)
        self.assertNotIn("claimToken", page)

    def test_canonical_domain_is_strict(self):
        bad = {"seo": {"canonicalUrl": "https://checkupauto.fr/"}}
        self.assertFalse(delivery.status(bad)["ready"])
        with self.assertRaises(ValueError):
            delivery.claim_landing_html(bad)


if __name__ == "__main__":
    unittest.main()
