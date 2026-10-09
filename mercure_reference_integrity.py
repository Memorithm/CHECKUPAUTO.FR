"""Reject ambiguous provider reference dropdowns before customer selection."""
from __future__ import annotations
import unicodedata

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
        normalized=" ".join(unicodedata.normalize("NFKC",label).casefold().split())
        if any(ord(c)<32 or ord(c)==127 for c in label):
            raise MercureReferenceIntegrityError("mercure_reference_invalid")
        if identifier in ids or normalized in labels:
            raise MercureReferenceIntegrityError("mercure_reference_ambiguous")
        ids.add(identifier)
        labels.add(normalized)
        result.append({"id":identifier,"label":label.strip()})
    return result


def selectable(rows: object) -> list[dict]:
    """Keep only unambiguous labels; never choose one of two provider identities.

    A duplicate provider ID is malformed. Duplicate normalized labels are valid
    provider data, but cannot be selected safely by this label-based customer UI.
    """
    from collections import Counter
    if not isinstance(rows,list) or len(rows)>10000:
        raise MercureReferenceIntegrityError("mercure_reference_invalid")
    normalized=[validate([item])[0] for item in rows]
    ids=[item["id"] for item in normalized]
    if len(ids)!=len(set(ids)):
        raise MercureReferenceIntegrityError("mercure_reference_ambiguous")
    def label_key(row):return " ".join(unicodedata.normalize("NFKC",row["label"]).casefold().split())
    counts=Counter(label_key(item) for item in normalized)
    return [item for item in normalized if counts[label_key(item)]==1]
