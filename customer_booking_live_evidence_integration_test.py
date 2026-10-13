"""Composed route tests with explicit provider fixtures; not production acceptance."""
import contextlib
import datetime as dt
import unittest
from unittest.mock import Mock, patch

import customer_http as http
import customer_booking_http_trusted_context as context
import customer_booking_create_api as create_api
import customer_booking_server_execution as execution
import mercure_vl_provider_metadata_resolver as resolver
import mercure_vl_provider_writer_factory as factory
import mercure_vl_live_slot_evidence as live
import mercure_vl_payment_policy_source as policy_source
from customer_booking_http_contract_test import Handler


def slot_fixture():
    return {"service":"technical", "serviceId":"1763", "duration":"40",
            "date":"2026-10-12", "time":"09:00", "lineId":"454", "centreType":"1",
            "observed":True, "slotAvailable":True, "slotHeld":False, "priceCents":8000,
            "source":"mercure-single-vl-resource-and-live-availability",
            "checkedAt":dt.datetime.now(dt.timezone.utc).isoformat()}


class BoundEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = slot_fixture()
        self.kw = dict(payload={"service":"technical", "date":"2026-10-12", "time":"09:00"},
                       metadata={"line_id":"454", "service_id":"1763", "duration":"40"}, price_cents=8000)

    def test_fresh_evidence_is_bound_to_exact_request_and_quote(self):
        live.validate_bound_snapshot(snapshot=self.snapshot, **self.kw)

    def test_evidence_cannot_be_reused_for_a_different_slot_or_line(self):
        for key, value in (("date","2026-10-13"),("time","09:40"),("lineId","455"),
                           ("serviceId","1771"),("duration","20"),("slotAvailable",1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                live.validate_bound_snapshot(snapshot=self.snapshot | {key:value}, **self.kw)

    def test_changed_quote_and_truthy_price_are_rejected(self):
        for amount in (7999, True, "8000"):
            with self.subTest(amount=amount), self.assertRaisesRegex(ValueError, "quote_changed"):
                live.validate_bound_snapshot(snapshot=self.snapshot | {"priceCents":amount}, **self.kw)

    def test_stale_future_naive_or_missing_timestamp_is_rejected(self):
        now = dt.datetime.now(dt.timezone.utc)
        for stamp in ((now-dt.timedelta(seconds=90)).isoformat(),
                      (now+dt.timedelta(minutes=1)).isoformat(), now.replace(tzinfo=None).isoformat(), None):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(ValueError, "stale"):
                live.validate_bound_snapshot(snapshot=self.snapshot | {"checkedAt":stamp}, **self.kw)


class ProviderCompositionTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config = {"lineId":"454", "operatorId":"464", "enabled":True}
        self.policy = {"service":"technical", "providerVerified":True, "paymentRequired":True}
        for obj, name, value in (
            (resolver.mercure_vl_live_metadata_options, "fetch", {"centre_type":["1"],"utilisateur":["464"]}),
            (resolver.mercure, "_session", Mock()),
            (resolver.mercure, "_check_auth", Mock(text="catalog")),
            (resolver.mercure_vl_embedded_service_catalog, "extract", {
                "1763":{"duration":"40","label":"TOUT VEHICULE HORS CAMPING CAR"}}),
        ):
            self.stack.enter_context(patch.object(obj, name, return_value=value))
        self.slot_loader = self.stack.enter_context(patch.object(live,"load",return_value=slot_fixture()))

    def test_context_routes_request_date_and_time_to_live_evidence(self):
        with patch.object(policy_source,"load",return_value=self.policy) as payment:
            executor, trusted = context.prepare(service="technical", date="2026-10-12", time="09:00",
                                                server_config=self.config)
        payment.assert_called_once_with(service="technical")
        self.slot_loader.assert_called_once_with(service="technical",date="2026-10-12",time="09:00",line_id="454")
        self.assertTrue(callable(executor))
        self.assertIsNone(trusted["payment_evidence"])
        observed = trusted["observed_metadata"]
        self.assertEqual(observed["ligne_id"], ["454"])
        self.assertEqual(observed["prestation"], ["1763"])
        self.assertEqual(observed["duree"], ["40"])
        with patch.object(factory,"MercureVlWriteAdapter") as adapter:
            factory.create(appointment={},metadata=trusted["metadata"],observed_metadata=observed,
                           expected_service_label=trusted["service_label"],authorized=True)
        adapter.assert_called_once()

    def test_live_source_cannot_be_overridden_with_caller_booleans(self):
        with self.assertRaisesRegex(ValueError,"override_forbidden"):
            resolver.resolve(service="technical",line_id="454",operator_id="464",date="2026-10-12",time="09:00",
                             line_evidence={"observed":True,"slotAvailable":True,"lineId":"454"})
        self.slot_loader.assert_not_called()

    def test_booking_is_not_written_before_verified_online_payment(self):
        executor, trusted = context.prepare(service="technical",date="2026-10-12",time="09:00",
                                            server_config=self.config,payment_policy=self.policy)
        payload={"service":"technical","date":"2026-10-12","time":"09:00","vehicleId":"v1",
                 "requestKey":"booking-integration-key-000001"}
        account={"accountId":"a1","vehicles":[{"vehicleId":"v1"}]}
        preflight={"service":"technical","date":"2026-10-12","time":"09:00","priceCents":8000,"bookingEnabled":True}
        with patch.object(create_api.customer_booking_api,"preflight",return_value=preflight), \
             patch.object(create_api.in_site_booking_readiness,"public_status",return_value={"bookingEnabled":True}), \
             patch.object(execution.mercure_vl_booking_coordinator,"create_and_verify") as writer:
            with self.assertRaisesRegex(create_api.BookingCreateUnavailable,"verified_prepayment_required"):
                create_api.create(payload,account=account,executor=executor,trusted_context=trusted)
        writer.assert_not_called()
        self.assertEqual(self.slot_loader.call_count,1)


class EffectiveHttpRouteTests(unittest.TestCase):
    def setUp(self):
        self.stack=contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.payload={"service":"technical","date":"2026-10-12","time":"09:00","vehicleId":"v1",
                      "requestKey":"booking-http-integration-000001"}
        self.stack.enter_context(patch.object(http,"_account",return_value=("token",{"accountId":"a1"})))
        self.stack.enter_context(patch.object(http,"_same_origin",return_value=True))
        self.stack.enter_context(patch.object(http.customer_accounts,"verify_csrf",return_value=True))
        self.stack.enter_context(patch.object(http.customer_accounts,"list_vehicles",return_value=[{"vehicleId":"v1"}]))
        self.stack.enter_context(patch.object(http.customer_booking_server_config_source,"load",return_value={
            "enabled":True,"lineId":"454","operatorId":"464"}))

    def handle(self,payload):
        handler=Handler(payload)
        handler.path="/api/customer/booking/create"
        self.assertTrue(http.handle(handler))
        return handler.response

    def test_provider_online_payment_refusal_returns_503_without_write(self):
        with patch.object(policy_source,"load",side_effect=policy_source.MercurePaymentPolicyError(
                "booking_online_payment_unavailable")), \
             patch.object(resolver,"resolve") as metadata, \
             patch.object(execution.mercure_vl_booking_coordinator,"create_and_verify") as writer:
            response=self.handle(self.payload)
        self.assertEqual(response["status"],503)
        self.assertEqual(response["json"]["error"],"booking_provider_not_qualified")
        metadata.assert_not_called()
        writer.assert_not_called()

    def test_browser_cannot_inject_payment_or_line_authority(self):
        for field in ("lineId","payment_policy","payment_evidence","slot_evidence"):
            with self.subTest(field=field), patch.object(policy_source,"load") as payment:
                response=self.handle(self.payload | {field:{"providerVerified":True}})
            self.assertEqual(response["status"],422)
            payment.assert_not_called()

    def test_effective_route_forwards_slot_not_payment_claims(self):
        with patch.object(context,"prepare",return_value=(Mock(),{})) as prepare, \
             patch.object(create_api,"create",return_value={"ok":True,"confirmed":False}):
            response=self.handle(self.payload)
        self.assertEqual(response["status"],200)
        self.assertEqual(prepare.call_args.kwargs["date"],self.payload["date"])
        self.assertEqual(prepare.call_args.kwargs["time"],self.payload["time"])
        self.assertNotIn("payment_policy",prepare.call_args.kwargs)
        self.assertNotIn("payment_evidence",prepare.call_args.kwargs)


class LastWriteBoundaryTests(unittest.TestCase):
    def test_changed_or_missing_evidence_never_reaches_writer(self):
        payload={"service":"technical","date":"2026-10-12","time":"09:00","vehicleId":"v1",
                 "requestKey":"booking-write-boundary-000001"}
        preflight={"service":"technical","date":"2026-10-12","time":"09:00","priceCents":8000,"bookingEnabled":True}
        for snapshot in (None, slot_fixture() | {"priceCents":7999}, slot_fixture() | {"lineId":"455"}):
            with self.subTest(snapshot=snapshot), \
                 patch.object(execution.customer_booking_api,"preflight",return_value=preflight), \
                 patch.object(execution.mercure_vl_booking_coordinator,"create_and_verify") as writer:
                with self.assertRaises(execution.CustomerBookingExecutionError):
                    execution.execute(payload=payload,account={"accountId":"a1"},vehicle={"vehicleId":"v1"},
                        metadata={"line_id":"454","service_id":"1763","duration":"40"},observed_metadata={},
                        service_label="CT",server_authorized=True,payment_authorizer=lambda **kwargs:{"authorized":True},
                        slot_evidence=snapshot)
                writer.assert_not_called()
