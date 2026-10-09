"""Explicit qualification contract for a future live VL writer; no network writes."""
from mercure_booking_write_contract import BookingWriter

def verify_writer(writer, *, qualified=False):
    if qualified is not True:
        raise ValueError("mercure_writer_not_homologated")
    if not callable(getattr(writer,"create_once",None)):
        raise ValueError("mercure_writer_create_missing")
    if not callable(getattr(writer,"read_identity",None)):
        raise ValueError("mercure_writer_identity_reader_missing")
    return writer
