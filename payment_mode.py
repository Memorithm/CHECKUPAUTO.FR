from __future__ import annotations
from urllib.parse import urlparse

PAYLINE="payline"
MERCUREWEB_DELEGATED="mercureweb-delegated"
ALLOWED_MODES={PAYLINE,MERCUREWEB_DELEGATED}
MERCUREWEB_ORIGIN="https://rdv.checkupauto.fr/"


def status(config: object) -> dict:
    root=config if isinstance(config,dict) else {}
    business=root.get("business") if isinstance(root.get("business"),dict) else {}
    mode=str(business.get("bookingMode") or PAYLINE).strip().lower()
    raw_url=str(business.get("bookingUrl") or "").strip()
    if mode not in ALLOWED_MODES:
        return {"mode":mode,"valid":False,"delegated":False,"bookingUrl":""}
    if mode==MERCUREWEB_DELEGATED:
        try:
            parsed=urlparse(raw_url)
            valid=(
                parsed.scheme=="https"
                and (parsed.hostname or "").lower()=="rdv.checkupauto.fr"
                and parsed.port in (None,443)
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and parsed.path in ("","/")
            )
        except (TypeError,ValueError):
            valid=False
        return {
            "mode":mode,
            "valid":valid,
            "delegated":valid,
            "bookingUrl":MERCUREWEB_ORIGIN if valid else "",
        }
    return {"mode":mode,"valid":True,"delegated":False,"bookingUrl":raw_url}
