"""HTTP contract tests: authenticated ownership, origin, CSRF and fail-closed responses."""
import io
import json
import unittest
from unittest.mock import patch

import customer_http as http


class Handler:
    def __init__(self, payload=None, command="POST"):
        self.path="/api/customer/booking/preflight"
        self.command=command
        raw=json.dumps(payload or {}).encode()
        self.rfile=io.BytesIO(raw)
        self.headers={
            "Content-Type":"application/json",
            "Content-Length":str(len(raw)),
            "Sec-Fetch-Site":"same-origin",
            "Host":"stage.example",
            "X-CheckupAuto-Customer-CSRF":"test-csrf",
        }
        self.response=None

    def _request_origin(self):
        return "https://stage.example"

    def send_json(self, obj, status=200, headers=None):
        self.response={"status":status,"json":obj}


class BookingHTTPContractTests(unittest.TestCase):
    def setUp(self):
        self.account={"accountId":"00000000-0000-4000-8000-000000000001"}
        self.payload={"service":"technical","date":"2026-10-15",
                      "time":"10:30","vehicleId":"owned-vehicle"}

    def test_anonymous_request_does_not_touch_vehicle_store_or_provider(self):
        handler=Handler(self.payload)
        with patch.object(http,"_account",return_value=("",None)), \
             patch.object(http.customer_accounts,"list_vehicles") as vehicles, \
             patch.object(http.customer_booking_api,"preflight") as provider:
            self.assertTrue(http.handle(handler))
        self.assertEqual(handler.response["status"],401)
        vehicles.assert_not_called()
        provider.assert_not_called()

    def test_csrf_rejected_before_vehicle_store_access(self):
        handler=Handler(self.payload)
        with patch.object(http,"_account",return_value=("token",self.account)), \
             patch.object(http,"_same_origin",return_value=True), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=False), \
             patch.object(http.customer_accounts,"list_vehicles") as vehicles:
            self.assertTrue(http.handle(handler))
        self.assertEqual(handler.response["status"],403)
        vehicles.assert_not_called()

    def test_preflight_uses_authoritative_account_scoped_vehicle_list(self):
        handler=Handler(self.payload)
        expected={"ok":True,"bookingConfirmed":False,"slotHeld":False}
        with patch.object(http,"_account",return_value=("token",self.account)), \
             patch.object(http,"_same_origin",return_value=True), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"list_vehicles",return_value=[
                 {"vehicleId":"owned-vehicle"}]) as vehicles, \
             patch.object(http.customer_booking_api,"preflight",return_value=expected) as preflight:
            self.assertTrue(http.handle(handler))
        vehicles.assert_called_once_with(self.account["accountId"])
        preflight.assert_called_once_with(self.payload,account={
            **self.account,"vehicles":[{"vehicleId":"owned-vehicle"}]})
        self.assertEqual(handler.response["status"],200)
        self.assertFalse(handler.response["json"]["bookingConfirmed"])

    def test_provider_failure_never_returns_success(self):
        handler=Handler(self.payload)
        with patch.object(http,"_account",return_value=("token",self.account)), \
             patch.object(http,"_same_origin",return_value=True), \
             patch.object(http.customer_accounts,"verify_csrf",return_value=True), \
             patch.object(http.customer_accounts,"list_vehicles",return_value=[]), \
             patch.object(http.customer_booking_api,"preflight",side_effect=TimeoutError):
            self.assertTrue(http.handle(handler))
        self.assertEqual(handler.response["status"],503)
        self.assertEqual(handler.response["json"]["error"],"booking_provider_unavailable")


if __name__=="__main__":
    unittest.main()
