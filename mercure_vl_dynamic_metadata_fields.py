"""Read-only Mercure VL form field classification, not provider value qualification."""
from __future__ import annotations
from html.parser import HTMLParser

FIELDS=("ligne_id","prestation","duree")


class _Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields={}

    def handle_starttag(self,tag,attrs):
        if tag not in ("input","select"):
            return
        props=dict(attrs)
        identifier=props.get("id") or props.get("name")
        if identifier not in FIELDS:
            return
        field_type="select" if tag=="select" else props.get("type","text")
        self.fields.setdefault(identifier,set()).add(field_type)


def classify(html: str) -> dict:
    if not isinstance(html,str) or len(html)>5_000_000:
        raise ValueError("mercure_form_invalid")
    parser=_Form()
    parser.feed(html)
    return {field:sorted(parser.fields.get(field,set())) for field in FIELDS}


def readiness(classification: dict) -> dict:
    expected={"ligne_id":"number","prestation":"select","duree":"number"}
    if not isinstance(classification,dict):
        raise ValueError("mercure_classification_invalid")
    missing=[field for field,kind in expected.items()
             if classification.get(field)!=[kind]]
    return {"structureObserved":not missing,"missingOrAmbiguous":missing,
            "valuesQualified":False,"customerWriteEnabled":False}
