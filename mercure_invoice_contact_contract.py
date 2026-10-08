"""Validate billing contact independently of vehicle and appointment data."""
from __future__ import annotations
import re

class MercureInvoiceContactError(ValueError):
    pass

def validate(contact: object) -> dict:
    if not isinstance(contact,dict):
        raise MercureInvoiceContactError("invoice_contact_missing")
    fields=("surname","givenName","address","postalCode","city","phone","email")
    result={}
    for key in fields:
        value=contact.get(key)
        if not isinstance(value,str) or not value.strip() or len(value)>254 or any(ord(c)<32 for c in value):
            raise MercureInvoiceContactError("invoice_contact_incomplete")
        result[key]=value.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",result["email"]):
        raise MercureInvoiceContactError("invoice_email_invalid")
    return result
