"""Native email/password customer sign-in and registration.

Reuse the audited web password verifier (including lockouts) and verified e-mail
registration pipeline. Passwords are never returned or stored by this module.
"""
from __future__ import annotations

import hmac

import customer_accounts
import customer_password_auth
import email_gateway


class MobileEmailAuthInvalid(ValueError):
    pass


class MobileEmailAuthUnavailable(RuntimeError):
    pass


def _fields(payload: object, expected: set[str]) -> dict[str, str]:
    if type(payload) is not dict or set(payload) != expected:
        raise MobileEmailAuthInvalid("mobile_email_payload_invalid")
    limits = {"email": 254, "password": 128, "passwordConfirm": 128}
    if any(type(payload[key]) is not str or not 1 <= len(payload[key]) <= limits[key]
           for key in expected):
        raise MobileEmailAuthInvalid("mobile_email_payload_invalid")
    return payload


def sign_in(payload: object, *, client_key: str = "") -> dict:
    values = _fields(payload, {"email", "password"})
    # Exactly the same password verifier and account/client lockouts as web login.
    account = customer_password_auth.authenticate(
        values["email"], values["password"], client_key=client_key
    )
    session = customer_accounts.issue_session(account["accountId"])
    return {"ok": True, "accountId": account["accountId"],
            "sessionToken": session["token"], "expiresAt": session["expiresAt"]}


def register(payload: object, *, send_confirmation) -> dict:
    values = _fields(payload, {"email", "password", "passwordConfirm"})
    if not hmac.compare_digest(values["password"], values["passwordConfirm"]):
        raise MobileEmailAuthInvalid("mobile_email_password_mismatch")
    if not callable(send_confirmation):
        raise MobileEmailAuthUnavailable("mobile_email_delivery_unavailable")
    if not email_gateway.configured():
        raise MobileEmailAuthUnavailable("mobile_email_delivery_unavailable")
    result = customer_password_auth.begin_registration(
        values["email"], None, values["password"]
    )
    # Same single-use verification/reset email as the existing browser form.
    # No token, account-existence flag or password is ever sent to the mobile app.
    send_confirmation(result)
    return {"ok": True, "verificationRequired": True}
