"""Private Mercure booking writer contract. No live provider write is enabled.

Implementations must provide a provider-assigned reference and an independent
authoritative calendar read. Never use the synthetic test writer for customers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class MercureBookingWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class BookingWriteRequest:
    request_key: str
    account_id: str
    vehicle_id: str
    service: str
    date: str
    time: str
    price_cents: int


@dataclass(frozen=True)
class BookingWriteReceipt:
    provider_reference: str
    accepted: bool


class BookingWriter(Protocol):
    def create_once(self, request: BookingWriteRequest) -> BookingWriteReceipt:
        """Return provider evidence; on timeout caller must reconcile, never retry blindly."""
        ...


class UnqualifiedMercureWriter:
    """Explicit production default until a real Mercure API is homologated."""

    def create_once(self, request: BookingWriteRequest) -> BookingWriteReceipt:
        raise MercureBookingWriteError("mercure_booking_writer_unqualified")


def writer() -> BookingWriter:
    # No environment flag or browser input can enable a synthetic write.
    return UnqualifiedMercureWriter()
