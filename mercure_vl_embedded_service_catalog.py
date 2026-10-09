"""Extract provider-embedded VL services; never trust unverified dynamic options."""
from __future__ import annotations
import json
import re

_PATTERN=re.compile(
    r'function\s+prestationAndClientByCentreType\s*\([^)]*\)\s*\{[\s\S]*?'
    r'const\s+prestations\s*=\s*(\[[\s\S]*?\])\s*;',re.MULTILINE)


def extract(html: str) -> dict:
    if not isinstance(html,str) or len(html)>5_000_000:
        raise ValueError("mercure_catalog_html_invalid")
    match=_PATTERN.search(html)
    if match is None:
        raise ValueError("mercure_catalog_not_found")
    try:
        items=json.loads(match.group(1))
    except (ValueError,TypeError) as exc:
        raise ValueError("mercure_catalog_invalid") from exc
    if not isinstance(items,list) or len(items)>500:
        raise ValueError("mercure_catalog_invalid")
    result={}
    for item in items:
        if not isinstance(item,dict):
            raise ValueError("mercure_catalog_invalid")
        if item.get("centre_type_id")!=1:
            continue
        identifier=item.get("id")
        duration=item.get("duree")
        if type(identifier) is not int or type(duration) is not int or not (0<duration<=240):
            raise ValueError("mercure_catalog_invalid")
        key=str(identifier)
        if key in result:
            raise ValueError("mercure_catalog_duplicate")
        result[key]={"duration":str(duration),
                     "label":str(item.get("type_visite_libele_long") or "")}
    if not result:
        raise ValueError("mercure_vl_catalog_empty")
    return result
