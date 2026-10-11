import ast
import html
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs

import booking_page


class BookingPageTest(unittest.TestCase):
    def test_missing_terms_is_html_without_automatic_redirect(self):
        page = booking_page.unavailable_html(terms_missing=True).decode()
        self.assertIn("<!doctype html>", page)
        self.assertIn("conditions générales de vente", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("rdv.checkupauto.fr", page)
        self.assertNotIn("booking_request_failed", page)

    def test_valid_phone_is_escaped_and_retained(self):
        page = booking_page.unavailable_html(phone="01 86 04 68 64").decode()
        self.assertIn('href="tel:0186046864"', page)
        self.assertIn("01 86 04 68 64", page)

    def test_invalid_phone_has_no_link(self):
        for phone in (None, "", "javascript:alert(1)", "++123456"):
            self.assertNotIn('href="tel:', booking_page.unavailable_html(phone=phone).decode())

    def test_markup_in_phone_is_not_interpreted(self):
        page = booking_page.unavailable_html(phone='<img src=x onerror=alert(1)>0186046864').decode()
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img", page)

    def test_generic_error_does_not_expose_internal_exception(self):
        page = booking_page.unavailable_html().decode()
        self.assertIn("Aucun rendez-vous n’a été confirmé", page)
        self.assertNotIn("Traceback", page)


class BookingRouteTest(unittest.TestCase):
    """Execute the actual checkout branch without loading private runtime data."""
    def setUp(self):
        tree = ast.parse(Path(__file__).with_name("admin_server.py").read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Handler")
        get = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == "do_GET")
        branch = next(n for n in get.body if isinstance(n, ast.If) and ast.unparse(n.test) == "path == '/go/booking'")
        function = ast.FunctionDef(name="route", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="self")], kwonlyargs=[], kw_defaults=[], defaults=[]), body=branch.body, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        self.terms_error = type("BookingTermsUnavailable", (RuntimeError,), {})
        self.booking = SimpleNamespace(BookingTermsUnavailable=self.terms_error, mercure_prestation=Mock(return_value="allowed"), require_published_terms=Mock(), create_intent=Mock(return_value={"token": "fixture"}), auto_submit_html=Mock(return_value=b"<html>review</html>"))
        self.config = Mock(return_value={"business": {"phone": "01 86 04 68 64", "bookingUrl": "https://rdv.checkupauto.fr/"}})
        self.customer_http = SimpleNamespace(
            consume_booking_confirmation=Mock(return_value={"required": False, "consumed": False}),
            booking_confirmation_url=Mock(return_value="/compte/reserver?returnTo=%2Fgo%2Fbooking"),
            _account=Mock(return_value=("", None)),
        )
        scope = dict(
            booking=self.booking,
            booking_page=booking_page,
            booking_readiness=SimpleNamespace(in_site_flag_enabled=Mock(return_value=False)),
            customer_http=self.customer_http,
            load_config=self.config,
            parsed=SimpleNamespace(query="service=Contr%C3%B4le+technique"),
            path="/go/booking",
            parse_qs=parse_qs,
            re=re,
            esc=lambda v: html.escape(str(v), quote=True),
            secrets=secrets,
        )
        exec(compile(module, "actual-checkout-branch", "exec"), scope)
        self.route = scope["route"]
        self.handler = SimpleNamespace(send_bytes=Mock(), send_json=Mock(), send_redirect=Mock())

    def test_missing_terms_is_503_html_and_creates_no_intent(self):
        self.booking.require_published_terms.side_effect = self.terms_error()
        self.route(self.handler)
        self.booking.create_intent.assert_not_called()
        self.handler.send_json.assert_not_called()
        args, kwargs = self.handler.send_bytes.call_args
        self.assertEqual(args[1:], ("text/html; charset=utf-8", 503))
        self.assertIn("conditions générales de vente", args[0].decode())
        self.assertEqual(kwargs["cache"], "no-store")

    def test_unexpected_backend_failure_is_safe_html(self):
        self.booking.create_intent.side_effect = RuntimeError("private database /root/secret")
        self.route(self.handler)
        args, _ = self.handler.send_bytes.call_args
        self.assertEqual(args[2], 503)
        self.assertNotIn(b"/root/secret", args[0])
        self.handler.send_json.assert_not_called()

    def test_config_failure_is_safe_html_without_phone(self):
        self.config.side_effect = RuntimeError("private config")
        self.route(self.handler)
        args, _ = self.handler.send_bytes.call_args
        self.assertEqual(args[2], 503)
        self.assertNotIn(b"tel:", args[0])

    def test_success_preserves_unmodified_review_page(self):
        self.route(self.handler)
        self.handler.send_bytes.assert_called_once_with(b"<html>review</html>", "text/html; charset=utf-8", cache="no-store")
        self.booking.require_published_terms.assert_called_once_with()
        self.booking.create_intent.assert_called_once()

    def test_logged_in_profile_is_passed_to_the_delegated_page(self):
        account = {"accountId": "a", "surname": "Martin"}
        self.customer_http._account.return_value = ("session", account)
        self.route(self.handler)
        self.assertIs(self.booking.auto_submit_html.call_args.kwargs["customer"], account)

    def test_flag_off_never_consults_on_site_routing(self):
        self.handler._in_site_booking_doc = Mock(side_effect=AssertionError("on-site routing"))
        self.route(self.handler)
        self.handler.send_bytes.assert_called_once_with(b"<html>review</html>", "text/html; charset=utf-8", cache="no-store")

    def test_flag_on_without_on_site_page_keeps_delegated_review_page(self):
        self.route.__globals__["booking_readiness"].in_site_flag_enabled.return_value = True
        self.handler._in_site_booking_doc = Mock(return_value=None)
        self.route(self.handler)
        self.handler._in_site_booking_doc.assert_called_once()
        self.handler.send_bytes.assert_called_once_with(b"<html>review</html>", "text/html; charset=utf-8", cache="no-store")

    def test_authenticated_customer_without_confirmation_is_redirected_before_intent(self):
        self.customer_http.consume_booking_confirmation.side_effect = PermissionError("confirmation required")
        self.route(self.handler)
        self.booking.create_intent.assert_not_called()
        self.handler.send_bytes.assert_not_called()
        self.handler.send_redirect.assert_called_once_with(
            "/compte/reserver?returnTo=%2Fgo%2Fbooking",303
        )
        self.customer_http.booking_confirmation_url.assert_called_once_with(
            "/go/booking?service=Contr%C3%B4le+technique"
        )

    def test_other_services_remain_telephone_only(self):
        self.booking.mercure_prestation.return_value = None
        self.route(self.handler)
        self.booking.require_published_terms.assert_not_called()
        self.booking.create_intent.assert_not_called()
        self.assertIn("Cette prestation se réserve par téléphone", self.handler.send_bytes.call_args.args[0].decode())


if __name__ == "__main__":
    unittest.main()