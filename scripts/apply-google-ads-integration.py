from pathlib import Path

PATH = Path("integration_hub.py")
text = PATH.read_text()


def replace_once(old, new):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one integration anchor, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    "import requests\n",
    "import requests\n\nfrom google_ads_probe import (\n"
    "    GOOGLE_ADS_SCOPE,\n"
    "    GoogleAdsProbeError,\n"
    "    GoogleAdsProbeHTTPError,\n"
    "    verify_access as verify_google_ads_access,\n"
    ")\n",
)

replace_once(
    '        "scopes": ["https://www.googleapis.com/auth/adwords"],\n',
    '        "scopes": [GOOGLE_ADS_SCOPE],\n',
)

probe_anchor = "\n\ndef _apply_analytics_probe(row, cfg):\n"
probe_code = '''

def google_ads_access_probe(developer_token=None):
    developer = str(
        developer_token or settings().get("googleAdsDeveloperToken") or ""
    ).strip()
    if not developer:
        raise IntegrationError("Jeton développeur Google Ads requis.")
    token = google_access_token([GOOGLE_ADS_SCOPE])
    try:
        return verify_google_ads_access(
            token,
            developer,
            request_get=requests.get,
            timeout=20,
        )
    except GoogleAdsProbeHTTPError as exc:
        raise IntegrationHTTPError(
            "Vérification Google Ads impossible.",
            status=exc.status,
            retry_after=exc.retry_after,
            retryable=exc.retryable,
        ) from exc
    except GoogleAdsProbeError as exc:
        raise IntegrationError("Réponse Google Ads invalide.") from exc
'''
replace_once(probe_anchor, probe_code + probe_anchor)

apply_anchor = "\n\ndef _apply_calendar_probe(row):\n"
apply_code = '''

def _apply_google_ads_probe(row, cfg):
    try:
        probe = google_ads_access_probe(cfg.get("googleAdsDeveloperToken"))
    except IntegrationHTTPError as exc:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "unavailable" if exc.retryable else "failed"
        row["detail"] = (
            "Configuration présente · vérification API Google Ads indisponible"
            if exc.retryable
            else "API Google Ads joignable · accès refusé"
        )
    except IntegrationError:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "failed"
        row["detail"] = "Configuration Google Ads invalide ou non vérifiable"
    else:
        count = int(probe.get("accessibleCustomerCount") or 0)
        row["probe"] = {"accessibleCustomerCount": count}
        if not probe.get("usable"):
            row["connected"] = False
            row["state"] = "attention"
            row["verification"] = "failed"
            row["detail"] = "API Google Ads vérifiée · aucun compte accessible"
        else:
            row["connected"] = True
            row["state"] = "connected"
            row["verification"] = "verified"
            row["detail"] = "API Google Ads vérifiée"
    return row
'''
replace_once(apply_anchor, apply_code + apply_anchor)

replace_once(
    '''            elif key == "tag_manager":
                _apply_tag_manager_probe(row, cfg)
            elif key == "calendar":
''',
    '''            elif key == "tag_manager":
                _apply_tag_manager_probe(row, cfg)
            elif key == "google_ads":
                _apply_google_ads_probe(row, cfg)
            elif key == "calendar":
''',
)

PATH.write_text(text)
