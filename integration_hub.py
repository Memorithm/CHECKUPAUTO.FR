from pathlib import Path
from urllib.parse import quote, urlencode
from email.utils import parseaddr
import datetime
import json
import os
import secrets
import tempfile

import requests

from google_ads_probe import (
    GOOGLE_ADS_SCOPE,
    GoogleAdsProbeError,
    GoogleAdsProbeHTTPError,
    verify_access as verify_google_ads_access,
)

PRIVATE_DIR = Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))
INTEGRATION_DIR = PRIVATE_DIR / "integrations"
CLIENT_FILE = INTEGRATION_DIR / "google-oauth-client.json"
TOKEN_FILE = INTEGRATION_DIR / "google-oauth-token.json"
SETTINGS_FILE = INTEGRATION_DIR / "google-settings.json"
STATE_FILE = INTEGRATION_DIR / "google-oauth-state.json"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
ANALYTICS_METADATA_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}/metadata"
BUSINESS_PROFILE_SCOPE = "https://www.googleapis.com/auth/business.manage"
BUSINESS_PROFILE_ACCOUNT_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/{account_name}"
TAG_MANAGER_SCOPE = "https://www.googleapis.com/auth/tagmanager.readonly"
TAG_MANAGER_ACCOUNT_URL = "https://tagmanager.googleapis.com/tagmanager/v2/accounts/{account_id}"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

CONNECTORS = {
    "search_console": {
        "label": "Google Search Console",
        "category": "Découverte",
        "description": "Indexation, performances de recherche, sitemaps et inspection d’URL.",
        "scopes": ["https://www.googleapis.com/auth/webmasters"],
        "mode": "oauth_or_service_account",
    },
    "business_profile": {
        "label": "Google Business Profile",
        "category": "Référencement local",
        "description": "Fiche établissement, informations locales et avis Google.",
        "scopes": [BUSINESS_PROFILE_SCOPE],
        "mode": "oauth_plus_setting",
        "setting": "businessAccountId",
    },
    "analytics": {
        "label": "Google Analytics 4",
        "category": "Mesure",
        "description": "Audience, acquisition et conversions via la Google Analytics Data API.",
        "scopes": [ANALYTICS_SCOPE],
        "mode": "oauth_plus_setting",
        "setting": "analyticsPropertyId",
    },
    "tag_manager": {
        "label": "Google Tag Manager",
        "category": "Mesure",
        "description": "Lecture des conteneurs et supervision des balises.",
        "scopes": [TAG_MANAGER_SCOPE],
        "mode": "oauth_plus_setting",
        "setting": "tagManagerAccountId",
    },
    "google_ads": {
        "label": "Google Ads",
        "category": "Publicité",
        "description": "Campagnes, dépenses et conversions publicitaires.",
        "scopes": [GOOGLE_ADS_SCOPE],
        "mode": "oauth_plus_setting",
        "setting": "googleAdsDeveloperToken",
    },
    "maps_places": {
        "label": "Google Maps / Places",
        "category": "Local",
        "description": "Recherche locale, Places et fonctions cartographiques.",
        "scopes": [],
        "mode": "api_key",
        "setting": "mapsApiKey",
    },
    "gmail": {
        "label": "Gmail",
        "category": "Communication",
        "description": "Envoi de messages opérationnels depuis le compte autorisé.",
        "scopes": ["https://www.googleapis.com/auth/gmail.send"],
        "mode": "oauth_plus_setting",
        "setting": "gmailSender",
    },
    "calendar": {
        "label": "Google Calendar",
        "category": "Organisation",
        "description": "Lecture et gestion des événements utiles à l’exploitation.",
        "scopes": [CALENDAR_SCOPE],
        "mode": "oauth",
    },
    "drive": {
        "label": "Google Drive",
        "category": "Documents",
        "description": "Accès limité aux fichiers explicitement utilisés avec CheckupAuto.",
        "scopes": [DRIVE_SCOPE],
        "mode": "oauth",
    },
}

SETTING_KEYS = {
    "mapsApiKey",
    "googleAdsDeveloperToken",
    "analyticsPropertyId",
    "businessAccountId",
    "tagManagerAccountId",
    "gmailSender",
}


class IntegrationError(RuntimeError):
    pass


class IntegrationHTTPError(IntegrationError):
    def __init__(self, message, *, status=0, retry_after="", retryable=False):
        self.status = int(status or 0)
        self.retry_after = str(retry_after or "")[:80]
        self.retryable = bool(retryable)
        super().__init__(str(message or "Erreur HTTP d’intégration")[:180])


def _ensure_dir():
    INTEGRATION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(INTEGRATION_DIR, 0o700)
    except OSError:
        pass


def _load(path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else ({} if default is None else default)
    except Exception:
        return {} if default is None else default


def _atomic_json(path, payload):
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(prefix=path.stem + "-", suffix=".json", dir=str(INTEGRATION_DIR))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _web_redirect_uris(client):
    if not isinstance(client, dict) or client.get("client_type") != "web":
        return set()
    raw = client.get("redirect_uris")
    if not isinstance(raw, list):
        return set()
    return {str(value).strip() for value in raw if isinstance(value, str) and value.strip()}


def _client_payload(payload):
    if not isinstance(payload, dict):
        raise IntegrationError("Le fichier OAuth Google est invalide.")
    cfg = payload.get("web")
    if not isinstance(cfg, dict):
        if isinstance(payload.get("installed"), dict):
            raise IntegrationError("Utilisez un client OAuth Google de type Application Web.")
        raise IntegrationError("Le fichier OAuth Google doit contenir une configuration web.")
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise IntegrationError("client_id et client_secret Google sont requis.")
    token_uri = str(cfg.get("token_uri") or TOKEN_URL).strip()
    if token_uri != TOKEN_URL:
        raise IntegrationError("token_uri OAuth Google non approuvée.")
    raw_redirects = cfg.get("redirect_uris")
    if not isinstance(raw_redirects, list):
        raise IntegrationError("Le client OAuth Google Web doit déclarer ses URI de redirection.")
    redirect_uris = []
    for value in raw_redirects:
        if not isinstance(value, str):
            raise IntegrationError("URI de redirection OAuth Google invalide.")
        uri = value.strip()
        if not uri or len(uri) > 2048:
            raise IntegrationError("URI de redirection OAuth Google invalide.")
        if uri not in redirect_uris:
            redirect_uris.append(uri)
    if not redirect_uris:
        raise IntegrationError("Le client OAuth Google Web doit déclarer ses URI de redirection.")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "project_id": str(cfg.get("project_id") or "").strip(),
        "auth_uri": AUTH_URL,
        "token_uri": TOKEN_URL,
        "client_type": "web",
        "redirect_uris": redirect_uris,
    }


def oauth_redirect_uri(base_url):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + "/api/integrations/google/oauth/callback"


def save_oauth_client(payload):
    clean = _client_payload(payload)
    _atomic_json(CLIENT_FILE, clean)
    return oauth_client_info()


def oauth_client_info(base_url=""):
    cfg = _load(CLIENT_FILE)
    redirects = _web_redirect_uris(cfg)
    expected_redirect = oauth_redirect_uri(base_url)
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "webClientVerified": bool(redirects),
        "redirectUriAllowed": bool(expected_redirect and expected_redirect in redirects),
        "redirectUriCount": len(redirects),
        "clientIdSuffix": cfg.get("client_id", "")[-18:] if cfg.get("client_id") else None,
        "projectId": cfg.get("project_id") or None,
    }


def settings():
    return _load(SETTINGS_FILE)


def settings_info():
    data = settings()
    return {
        "mapsApiKeyConfigured": bool(data.get("mapsApiKey")),
        "googleAdsDeveloperTokenConfigured": bool(data.get("googleAdsDeveloperToken")),
        "analyticsPropertyId": data.get("analyticsPropertyId") or "",
        "businessAccountId": data.get("businessAccountId") or "",
        "tagManagerAccountId": data.get("tagManagerAccountId") or "",
        "gmailSender": data.get("gmailSender") or "",
    }


def _valid_email(value):
    raw = str(value or "").strip()
    if not raw or len(raw) > 254 or any(ord(ch) < 32 for ch in raw):
        return False
    name, address = parseaddr(raw)
    if name and address != raw:
        return False
    if address != raw or address.count("@") != 1:
        return False
    local, domain = address.rsplit("@", 1)
    return bool(local and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def _valid_analytics_property_id(value):
    raw = str(value or "").strip()
    return bool(raw and raw != "0" and raw.isascii() and raw.isdigit())


def _normalize_business_account_id(value):
    raw = str(value or "").strip()
    if raw.startswith("accounts/"):
        identifier = raw[len("accounts/"):]
    else:
        identifier = raw
    if not identifier or not identifier.isascii() or not identifier.isdigit():
        return ""
    return "accounts/" + identifier


def _normalize_tag_manager_account_id(value):
    raw = str(value or "").strip()
    if raw.startswith("accounts/"):
        identifier = raw[len("accounts/"):]
    else:
        identifier = raw
    if (
        not identifier
        or len(identifier) > 200
        or "/" in identifier
        or any(ord(ch) < 32 for ch in identifier)
    ):
        return ""
    return "accounts/" + identifier


def save_settings(payload):
    if not isinstance(payload, dict):
        raise IntegrationError("Paramètres Google invalides.")
    current = settings()
    for key in SETTING_KEYS:
        if key not in payload:
            continue
        value = str(payload.get(key) or "").strip()
        if len(value) > 500:
            raise IntegrationError(f"{key} est trop long.")
        if key == "gmailSender" and value and not _valid_email(value):
            raise IntegrationError("Adresse d’envoi Gmail invalide.")
        if key == "analyticsPropertyId" and value and not _valid_analytics_property_id(value):
            raise IntegrationError("Identifiant de propriété Google Analytics invalide.")
        if key == "businessAccountId" and value:
            value = _normalize_business_account_id(value)
            if not value:
                raise IntegrationError("Identifiant de compte Google Business Profile invalide.")
        if key == "tagManagerAccountId" and value:
            value = _normalize_tag_manager_account_id(value)
            if not value:
                raise IntegrationError("Identifiant de compte Google Tag Manager invalide.")
        if value:
            current[key] = value
        else:
            current.pop(key, None)
    _atomic_json(SETTINGS_FILE, current)
    return settings_info()


def _granted_scopes():
    token = _load(TOKEN_FILE)
    raw = token.get("scope") or token.get("scopes") or []
    if isinstance(raw, str):
        return {x for x in raw.split() if x}
    if isinstance(raw, list):
        return {str(x) for x in raw if x}
    return set()


def _token_expiry(token):
    raw = str((token or {}).get("expires_at") or "").strip()
    if not raw:
        return None
    try:
        expiry = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=datetime.timezone.utc)
    return expiry.astimezone(datetime.timezone.utc)


def oauth_health():
    """Return a secret-free local assessment of the persisted Google OAuth session."""
    token = _load(TOKEN_FILE)
    client = oauth_client_info()
    scopes = sorted(_granted_scopes())
    has_access = bool(token.get("access_token"))
    has_refresh = bool(token.get("refresh_token"))
    expiry = _token_expiry(token)
    now = datetime.datetime.now(datetime.timezone.utc)
    cached_access_valid = bool(
        has_access
        and expiry is not None
        and expiry > now + datetime.timedelta(seconds=30)
    )
    refreshable = bool(has_refresh and client.get("configured"))
    usable = cached_access_valid or refreshable

    if not has_access and not has_refresh:
        state = "awaiting_authorization"
    elif refreshable:
        state = "ready"
    elif cached_access_valid:
        state = "ready_cached"
    elif has_refresh and not client.get("configured"):
        state = "oauth_client_missing"
    elif has_access and expiry is None:
        state = "reauthorization_required"
    else:
        state = "token_expired"

    return {
        "usable": usable,
        "state": state,
        "refreshable": refreshable,
        "cachedAccessValid": cached_access_valid,
        "scopeCount": len(scopes),
    }


def has_usable_scopes(required):
    required = set(required or [])
    return bool(oauth_health().get("usable")) and required.issubset(_granted_scopes())


def analytics_property_probe(property_id=None):
    raw = str(property_id or settings().get("analyticsPropertyId") or "").strip()
    if not _valid_analytics_property_id(raw):
        raise IntegrationError("Identifiant de propriété Google Analytics invalide.")
    token = google_access_token([ANALYTICS_SCOPE])
    try:
        response = requests.get(
            ANALYTICS_METADATA_URL.format(property_id=raw),
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationHTTPError(
            "Connexion à Google Analytics impossible.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google Analytics a refusé la vérification de la propriété.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse Google Analytics invalide.") from exc
    expected_name = f"properties/{raw}/metadata"
    if (
        not isinstance(payload, dict)
        or payload.get("name") != expected_name
        or not isinstance(payload.get("dimensions"), list)
        or not isinstance(payload.get("metrics"), list)
    ):
        raise IntegrationError("Réponse Google Analytics invalide.")
    return {
        "connected": True,
        "verification": "verified",
        "dimensionCount": len(payload["dimensions"]),
        "metricCount": len(payload["metrics"]),
    }


def business_profile_account_probe(account_id=None):
    account_name = _normalize_business_account_id(
        account_id or settings().get("businessAccountId") or ""
    )
    if not account_name:
        raise IntegrationError("Identifiant de compte Google Business Profile invalide.")
    token = google_access_token([BUSINESS_PROFILE_SCOPE])
    try:
        response = requests.get(
            BUSINESS_PROFILE_ACCOUNT_URL.format(account_name=account_name),
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationHTTPError(
            "Connexion à Google Business Profile impossible.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google Business Profile a refusé la vérification du compte.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse Google Business Profile invalide.") from exc
    if not isinstance(payload, dict) or payload.get("name") != account_name:
        raise IntegrationError("Réponse Google Business Profile invalide.")
    return {"connected": True, "verification": "verified"}


def tag_manager_account_probe(account_id=None):
    account_name = _normalize_tag_manager_account_id(
        account_id or settings().get("tagManagerAccountId") or ""
    )
    if not account_name:
        raise IntegrationError("Identifiant de compte Google Tag Manager invalide.")
    identifier = account_name[len("accounts/"):]
    token = google_access_token([TAG_MANAGER_SCOPE])
    try:
        response = requests.get(
            TAG_MANAGER_ACCOUNT_URL.format(account_id=quote(identifier, safe="")),
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationHTTPError(
            "Connexion à Google Tag Manager impossible.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google Tag Manager a refusé la vérification du compte.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse Google Tag Manager invalide.") from exc
    if not isinstance(payload, dict):
        raise IntegrationError("Réponse Google Tag Manager invalide.")
    response_path = str(payload.get("path") or "").strip()
    response_account_id = str(payload.get("accountId") or "").strip()
    if not response_path and not response_account_id:
        raise IntegrationError("Réponse Google Tag Manager invalide.")
    if response_path and response_path != account_name:
        raise IntegrationError("Réponse Google Tag Manager incohérente.")
    if response_account_id and response_account_id != identifier:
        raise IntegrationError("Réponse Google Tag Manager incohérente.")
    return {"connected": True, "verification": "verified"}


def calendar_events_probe():
    token = google_access_token([CALENDAR_SCOPE])
    try:
        response = requests.get(
            CALENDAR_EVENTS_URL,
            headers={"Authorization": "Bearer " + token},
            params={"maxResults": 1},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationHTTPError(
            "Connexion à Google Calendar impossible.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google Calendar a refusé la vérification du calendrier principal.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse Google Calendar invalide.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "calendar#events"
        or ("items" in payload and not isinstance(payload.get("items"), list))
    ):
        raise IntegrationError("Réponse Google Calendar invalide.")
    return {"connected": True, "verification": "verified"}


def drive_files_probe():
    token = google_access_token([DRIVE_SCOPE])
    try:
        response = requests.get(
            DRIVE_FILES_URL,
            headers={"Authorization": "Bearer " + token},
            params={"pageSize": 1, "fields": "kind,files(id)"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationHTTPError(
            "Connexion à Google Drive impossible.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google Drive a refusé la vérification de l’accès aux fichiers.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse Google Drive invalide.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "drive#fileList"
        or ("files" in payload and not isinstance(payload.get("files"), list))
    ):
        raise IntegrationError("Réponse Google Drive invalide.")
    return {"connected": True, "verification": "verified"}


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


def _apply_analytics_probe(row, cfg):
    try:
        probe = analytics_property_probe(cfg.get("analyticsPropertyId"))
    except IntegrationHTTPError as exc:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "unavailable" if exc.retryable else "failed"
        row["detail"] = (
            "Configuration présente · vérification API Google Analytics indisponible"
            if exc.retryable
            else "API Google Analytics joignable · propriété non accessible"
        )
    except IntegrationError:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "failed"
        row["detail"] = "Configuration Google Analytics invalide ou non vérifiable"
    else:
        row["connected"] = True
        row["state"] = "connected"
        row["verification"] = "verified"
        row["detail"] = "API Google Analytics vérifiée"
        row["probe"] = {
            "dimensionCount": int(probe.get("dimensionCount") or 0),
            "metricCount": int(probe.get("metricCount") or 0),
        }
    return row


def _apply_business_profile_probe(row, cfg):
    try:
        business_profile_account_probe(cfg.get("businessAccountId"))
    except IntegrationHTTPError as exc:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "unavailable" if exc.retryable else "failed"
        row["detail"] = (
            "Configuration présente · vérification API Business Profile indisponible"
            if exc.retryable
            else "API Business Profile joignable · compte non accessible"
        )
    except IntegrationError:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "failed"
        row["detail"] = "Configuration Business Profile invalide ou non vérifiable"
    else:
        row["connected"] = True
        row["state"] = "connected"
        row["verification"] = "verified"
        row["detail"] = "API Google Business Profile vérifiée"
    return row


def _apply_tag_manager_probe(row, cfg):
    try:
        tag_manager_account_probe(cfg.get("tagManagerAccountId"))
    except IntegrationHTTPError as exc:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "unavailable" if exc.retryable else "failed"
        row["detail"] = (
            "Configuration présente · vérification API Tag Manager indisponible"
            if exc.retryable
            else "API Tag Manager joignable · compte non accessible"
        )
    except IntegrationError:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "failed"
        row["detail"] = "Configuration Tag Manager invalide ou non vérifiable"
    else:
        row["connected"] = True
        row["state"] = "connected"
        row["verification"] = "verified"
        row["detail"] = "API Google Tag Manager vérifiée"
    return row


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


def _apply_calendar_probe(row):
    try:
        calendar_events_probe()
    except IntegrationHTTPError as exc:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "unavailable" if exc.retryable else "failed"
        row["detail"] = (
            "Configuration présente · vérification API Google Calendar indisponible"
            if exc.retryable
            else "API Google Calendar joignable · calendrier principal non accessible"
        )
    except IntegrationError:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "failed"
        row["detail"] = "Configuration Google Calendar invalide ou non vérifiable"
    else:
        row["connected"] = True
        row["state"] = "connected"
        row["verification"] = "verified"
        row["detail"] = "API Google Calendar vérifiée"
    return row


def _apply_drive_probe(row):
    try:
        drive_files_probe()
    except IntegrationHTTPError as exc:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "unavailable" if exc.retryable else "failed"
        row["detail"] = (
            "Configuration présente · vérification API Google Drive indisponible"
            if exc.retryable
            else "API Google Drive joignable · fichiers non accessibles"
        )
    except IntegrationError:
        row["connected"] = False
        row["state"] = "attention"
        row["verification"] = "failed"
        row["detail"] = "Configuration Google Drive invalide ou non vérifiable"
    else:
        row["connected"] = True
        row["state"] = "connected"
        row["verification"] = "verified"
        row["detail"] = "API Google Drive vérifiée"
    return row


def status(legacy_search_console=None, base_url="", *, verify_remote=None):
    legacy_search_console = legacy_search_console or {}
    scopes = _granted_scopes()
    cfg = settings()
    client = oauth_client_info(base_url)
    health = oauth_health()
    if verify_remote is None:
        verify_remote = bool(base_url)
    rows = []
    for key, meta in CONNECTORS.items():
        required = set(meta.get("scopes") or [])
        scope_granted = bool(required) and required.issubset(scopes)
        oauth_ok = bool(health.get("usable")) and scope_granted
        oauth_stale = scope_granted and not bool(health.get("usable"))
        extra_ok = True
        if meta.get("setting"):
            extra_ok = bool(cfg.get(meta["setting"]))
        if key == "search_console":
            legacy_ok = bool(legacy_search_console.get("configured"))
            connected = oauth_ok or legacy_ok
            if connected:
                state = "connected"
                detail = "Compte de service Search Console actif" if legacy_ok and not oauth_ok else "OAuth Google autorisé"
            elif oauth_stale:
                state = "attention"
                detail = "Autorisation OAuth présente · session à renouveler"
            else:
                state = "available"
                detail = "À connecter"
        elif meta["mode"] == "api_key":
            connected = False
            if extra_ok:
                state = "attention"
                detail = "Clé API configurée · vérification distante non exécutée"
            else:
                state = "available"
                detail = "Clé API requise"
        else:
            connected = oauth_ok and extra_ok
            if oauth_stale:
                state = "attention"
                detail = "Autorisation OAuth présente · session à renouveler"
            elif oauth_ok and not extra_ok:
                state = "attention"
                detail = "OAuth autorisé · paramètre complémentaire requis"
            else:
                state = "connected" if connected else "available"
                detail = "Connecté" if connected else "À connecter"
        row = {
            "id": key,
            "label": meta["label"],
            "category": meta["category"],
            "description": meta["description"],
            "mode": meta["mode"],
            "connected": connected,
            "state": state,
            "detail": detail,
            "requiredScopes": list(meta.get("scopes") or []),
        }
        if meta["mode"] == "api_key" and extra_ok:
            row["verification"] = "unverified"
        if row["connected"] and verify_remote:
            if key == "analytics":
                _apply_analytics_probe(row, cfg)
            elif key == "business_profile":
                _apply_business_profile_probe(row, cfg)
            elif key == "tag_manager":
                _apply_tag_manager_probe(row, cfg)
            elif key == "google_ads":
                _apply_google_ads_probe(row, cfg)
            elif key == "calendar":
                _apply_calendar_probe(row)
            elif key == "drive":
                _apply_drive_probe(row)
        rows.append(row)
    return {
        "provider": "google",
        "oauthClient": client,
        "oauthAuthorized": bool(health.get("usable")),
        "oauthHealth": health,
        "grantedScopes": sorted(scopes),
        "settings": settings_info(),
        "connectors": rows,
    }


def create_authorization_url(base_url, connector_ids):
    client = _load(CLIENT_FILE)
    if not client.get("client_id") or not client.get("client_secret"):
        raise IntegrationError("Installez d’abord le fichier client OAuth Google.")
    connector_ids = [x for x in connector_ids if x in CONNECTORS]
    scopes = []
    for key in connector_ids:
        for scope in CONNECTORS[key].get("scopes") or []:
            if scope not in scopes:
                scopes.append(scope)
    if not scopes:
        raise IntegrationError("Aucun service OAuth sélectionné.")
    redirect_uri = oauth_redirect_uri(base_url)
    allowed_redirects = _web_redirect_uris(client)
    if not allowed_redirects:
        raise IntegrationError("Réimportez un client OAuth Google de type Application Web.")
    if redirect_uri not in allowed_redirects:
        raise IntegrationError("L’URI de redirection OAuth CheckupAuto n’est pas autorisée dans le client Google.")
    state = secrets.token_urlsafe(32)
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
    _atomic_json(STATE_FILE, {
        "state": state,
        "redirect_uri": redirect_uri,
        "connectors": connector_ids,
        "expires_at": expires.isoformat(),
    })
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return {"authorizationUrl": AUTH_URL + "?" + urlencode(params), "connectors": connector_ids}


def handle_oauth_callback(base_url, state, code, error=""):
    if error:
        raise IntegrationError("Google a refusé l’autorisation OAuth.")
    pending = _load(STATE_FILE)
    expected = str(pending.get("state") or "")
    if not expected or not state or not secrets.compare_digest(expected, str(state)):
        raise IntegrationError("État OAuth Google invalide ou expiré.")
    try:
        expires = datetime.datetime.fromisoformat(str(pending.get("expires_at") or ""))
    except Exception as exc:
        raise IntegrationError("État OAuth Google invalide.") from exc
    if expires < datetime.datetime.now(datetime.timezone.utc):
        raise IntegrationError("La demande OAuth Google a expiré.")
    redirect_uri = oauth_redirect_uri(base_url)
    if pending.get("redirect_uri") != redirect_uri:
        raise IntegrationError("URI de redirection OAuth incohérente.")
    client = _load(CLIENT_FILE)
    if redirect_uri not in _web_redirect_uris(client):
        raise IntegrationError("Le client OAuth Google Web ne permet pas cette URI de redirection.")
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationError("Connexion au service OAuth Google impossible.") from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google a refusé l’échange OAuth.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        incoming = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse OAuth Google invalide.") from exc
    if not isinstance(incoming, dict):
        raise IntegrationError("Réponse OAuth Google invalide.")
    if not incoming.get("access_token"):
        raise IntegrationError("Google n’a pas retourné de jeton d’accès.")
    previous = _load(TOKEN_FILE)
    if not incoming.get("refresh_token") and previous.get("refresh_token"):
        incoming["refresh_token"] = previous["refresh_token"]
    previous_scopes = _granted_scopes()
    new_scopes = set(str(incoming.get("scope") or "").split())
    incoming["scope"] = " ".join(sorted(previous_scopes | new_scopes))
    now = datetime.datetime.now(datetime.timezone.utc)
    incoming["connected_at"] = now.isoformat()
    if incoming.get("expires_in"):
        try:
            ttl = max(0, int(incoming["expires_in"]) - 30)
        except (TypeError, ValueError) as exc:
            raise IntegrationError("Réponse OAuth Google invalide.") from exc
        incoming["expires_at"] = (now + datetime.timedelta(seconds=ttl)).isoformat()
    _atomic_json(TOKEN_FILE, incoming)
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"connected": True, "connectors": pending.get("connectors") or [], "scopes": incoming["scope"].split()}


def has_scopes(required):
    return set(required or []).issubset(_granted_scopes())


def google_access_token(required_scopes=None, *, force_refresh=False):
    required_scopes = list(required_scopes or [])
    if required_scopes and not has_scopes(required_scopes):
        raise IntegrationError("Le compte Google connecté ne possède pas les autorisations requises.")
    token = _load(TOKEN_FILE)
    access = token.get("access_token")
    expires_at = token.get("expires_at")
    if access and expires_at:
        try:
            expiry = datetime.datetime.fromisoformat(str(expires_at))
            if not force_refresh and expiry > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30):
                return access
        except Exception:
            pass
    refresh = token.get("refresh_token")
    client = _load(CLIENT_FILE)
    if not refresh or not client.get("client_id") or not client.get("client_secret"):
        if access and not force_refresh:
            return access
        raise IntegrationError("La connexion OAuth Google doit être renouvelée.")
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise IntegrationHTTPError(
            "Rafraîchissement OAuth Google impossible.",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise IntegrationHTTPError(
            "Google a refusé le rafraîchissement OAuth.",
            status=status_code,
            retry_after=response.headers.get("Retry-After", ""),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    try:
        incoming = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Réponse de rafraîchissement OAuth Google invalide.") from exc
    if not isinstance(incoming, dict):
        raise IntegrationError("Réponse de rafraîchissement OAuth Google invalide.")
    if not incoming.get("access_token"):
        raise IntegrationError("Google n’a pas retourné de nouveau jeton d’accès.")
    expires_at_value = None
    if incoming.get("expires_in"):
        try:
            ttl = max(0, int(incoming["expires_in"]) - 30)
        except (TypeError, ValueError) as exc:
            raise IntegrationError("Réponse de rafraîchissement OAuth Google invalide.") from exc
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at_value = (now + datetime.timedelta(seconds=ttl)).isoformat()
    token.update(incoming)
    token["refresh_token"] = refresh
    if not token.get("scope"):
        token["scope"] = " ".join(sorted(_granted_scopes()))
    if expires_at_value:
        token["expires_at"] = expires_at_value
    else:
        token.pop("expires_at", None)
    _atomic_json(TOKEN_FILE, token)
    return token["access_token"]


def revoke_oauth():
    token = _load(TOKEN_FILE)
    value = token.get("refresh_token") or token.get("access_token")
    if value:
        try:
            requests.post(REVOKE_URL, data={"token": value}, timeout=10)
        except requests.RequestException:
            pass
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"connected": False}
