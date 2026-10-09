"""Never replay a provider write after an ambiguous external effect."""
from __future__ import annotations


def decide(*, state: str, provider_reference: str | None = None) -> str:
    if state=="confirmed":
        return "return_confirmed"
    if state=="prepared" and not provider_reference:
        return "write_once"
    if state in ("reconciliation_required","prepared"):
        return "read_only_reconcile"
    raise ValueError("mercure_booking_state_invalid")
