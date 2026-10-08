"""Read-only parsing of provider brand and energy dropdown reference values."""
from __future__ import annotations

from html.parser import HTMLParser
import re

import mercure_admin_client as mercure


SELECT_IDS={"marque","marque_add","energie","energie_add"}


class _SelectParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current=None
        self.option=None
        self.result={key:[] for key in SELECT_IDS}

    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=="select":
            key=values.get("id")
            self.current=key if key in SELECT_IDS else None
        elif tag=="option" and self.current:
            self.option={"id":values.get("value",""),"label":""}

    def handle_data(self,data):
        if self.option is not None:
            self.option["label"]+=data

    def handle_endtag(self,tag):
        if tag=="option" and self.option is not None:
            item=self.option
            self.option=None
            if self.current and re.fullmatch(r"[0-9]{1,12}",item["id"]):
                label=item["label"].strip()
                if label:
                    self.result[self.current].append({"id":item["id"],"label":label[:120]})
        elif tag=="select":
            self.current=None
            self.option=None


def parse_references(html: str) -> dict:
    if not isinstance(html,str) or len(html)>5000000:
        raise ValueError("mercure_reference_page_invalid")
    parser=_SelectParser()
    parser.feed(html)
    if not parser.result["marque"] or not parser.result["energie"]:
        raise ValueError("mercure_reference_dropdown_missing")
    return parser.result


def fetch_references() -> dict:
    session=mercure._session()
    response=mercure._check_auth(session.get(mercure.BASE+"/admin/calendrier",
                                            timeout=20,allow_redirects=False))
    response.raise_for_status()
    return parse_references(response.text)
