"""Reject ambiguous provider reference dropdowns before customer selection."""
from __future__ import annotations

class MercureReferenceIntegrityError(ValueError):
    pass

def validate(rows: object) -> list[dict]:
    if not isinstance(rows,list) or len(rows)>10000:
        raise MercureReferenceIntegrityError("mercure_reference_invalid")
    ids=set()
    labels=set()
    result=[]
    for item in rows:
        if not isinstance(item,dict):
            raise MercureReferenceIntegrityError("mercure_reference_invalid")
        identifier=item.get("id")
        label=item.get("label")
        if not isinstance(identifier,str) or not identifier.isascii() or not identifier.isdecimal() or not 1<=len(identifier)<=12 or not isinstance(label,str) or not label.strip() or len(label)>120:
            raise MercureReferenceIntegrityError("mercure_reference_invalid")
        normalized=" ".join(label.casefold().split())
        if identifier in ids or normalized in labels:
            raise MercureReferenceIntegrityError("mercure_reference_ambiguous")
        ids.add(identifier)
        labels.add(normalized)
        result.append({"id":identifier,"label":label.strip()})
    return result
