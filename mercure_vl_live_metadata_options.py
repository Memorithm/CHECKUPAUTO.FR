"""Extract selectable VL metadata from authenticated Mercure HTML, without writes."""
from __future__ import annotations
from html.parser import HTMLParser

import mercure_admin_client as mercure

FIELDS=("centre_type","ligne_id","utilisateur","prestation","duree")


class _Options(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active=None
        self.options={key:set() for key in FIELDS}

    def handle_starttag(self,tag,attrs):
        attributes=dict(attrs)
        if tag=="select":
            identifier=attributes.get("id") or attributes.get("name")
            self.active=identifier if identifier in self.options else None
        elif tag=="option" and self.active:
            value=attributes.get("value")
            if isinstance(value,str) and value.isascii() and value.isdecimal():
                self.options[self.active].add(value)

    def handle_endtag(self,tag):
        if tag=="select":
            self.active=None


def extract(html: str) -> dict:
    if not isinstance(html,str) or len(html)>5_000_000:
        raise ValueError("mercure_form_invalid")
    parser=_Options()
    parser.feed(html)
    return {key:sorted(values) for key,values in parser.options.items()}


def fetch() -> dict:
    session=mercure._session()
    response=mercure._check_auth(session.get(
        mercure.BASE+"/admin/calendrier",timeout=20,allow_redirects=False))
    response.raise_for_status()
    return extract(response.text)
