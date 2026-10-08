"""Read-only Mercure vehicle model reference data; no customer records or writes."""
from __future__ import annotations

import re
import requests

import mercure_admin_client as mercure


class MercureReferenceError(RuntimeError):
    pass


def models(*, centre_type: str, brand_id: str) -> list[dict]:
    if not re.fullmatch(r"[0-9]{1,8}",str(centre_type)) or not re.fullmatch(r"[0-9]{1,12}",str(brand_id)):
        raise MercureReferenceError("mercure_reference_id_invalid")
    try:
        session=mercure._session()
        response=mercure._check_auth(session.get(
            mercure.BASE+"/admin/modeles/"+str(centre_type)+"/"+str(brand_id),
            timeout=15,allow_redirects=False))
        response.raise_for_status()
        records=response.json()
    except Exception as exc:
        raise MercureReferenceError("mercure_reference_unavailable") from exc
    if not isinstance(records,list) or len(records)>10000:
        raise MercureReferenceError("mercure_reference_invalid")
    result=[]
    for item in records:
        if not isinstance(item,dict):
            raise MercureReferenceError("mercure_reference_invalid")
        identifier=str(item.get("id",""))
        label=item.get("libele")
        if not re.fullmatch(r"[0-9]{1,12}",identifier) or not isinstance(label,str) or not label.strip():
            raise MercureReferenceError("mercure_reference_invalid")
        result.append({"id":identifier,"label":label.strip()[:120]})
    return result
