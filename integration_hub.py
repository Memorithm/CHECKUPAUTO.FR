from pathlib import Path
from urllib.parse import urlencode
from email.utils import parseaddr
import datetime
import json
import os
import secrets
import tempfile

import requests

PRIVATE_DIR = Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))
INTEGRATION_DIR = PRIVATE_DIR / "integrations"
CLIENT_FILE = INTEGRATION_DIR / "google-oauth-client.json"
TOKEN_FILE = INTEGRATION_DIR / "google-oauth-token.json"
SETTINGS_FILE = INTEGRATION_DIR / "google-settings.json"
STATE_FILE = INTEGRATION_DIR / "google-oauth-state.json"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

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
        "scopes": ["https://www.googleapis.com/auth/business.manage"],
        "mode": "oauth",
    },
    "analytics": {
        "label": "Google Analytics 4",
        "category": "Mesure",
        "description": "Audience, acquisition et conversions via la Google Analytics Data API.",
        "scopes": ["https://www.googleapis.com/auth/analytics.readonly"],
        "mode": "oauth",
    },
    "tag_manager": {
        "label": "Google Tag Manager",
        "category": "Mesure",
        "description": "Lecture des conteneurs et supervision des balises.",
        "scopes": ["https://www.googleapis.com/auth/tagmanager.readonly"],
        "mode": "oauth",
    },
    "google_ads": {
        "label": "Google Ads",
        "category": "Publicité",
        "description": "Campagnes, dépenses et conversions publicitaires.",
        "scopes": ["https://www.googleapis.com/auth/adwords"],
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
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        "mode": "oauth",
    },
    "drive": {
        "label": "Google Drive",
        "category": "Documents",
        "description": "Accès limité aux fichiers explicitement utilisés avec CheckupAuto.",
        "scopes": ["https://www.googleapis.com/auth/drive.file"],
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


def _client_payload(payload):
    if not isinstance(payload, dict):
        raise IntegrationError("Le fichier OAuth Google est invalide.")
    cfg = payload.get("web") or payload.get("installed") or payload
    if not isinstance(cfg, dict):
        raise IntegrationError("Le fichier OAuth Google est invalide.")
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise IntegrationError("client_id et client_secret Google sont requis.")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "project_id": str(cfg.get("project_id") or "").strip(),
        "auth_uri": str(cfg.get("auth_uri") or AUTH_URL),
        "token_uri": str(cfg.get("token_uri") or TOKEN_URL),
    }


def save_oauth_client(payload):
    clean = _client_payload(payload)
    _atomic_json(CLIENT_FILE, clean)
    return oauth_client_info()


def oauth_client_info():
    cfg = _load(CLIENT_FILE)
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
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


def status(legacy_search_console=None):
    legacy_search_console = legacy_search_console or {}
    scopes = _granted_scopes()
    cfg = settings()
    client = oauth_client_info()
    token = _load(TOKEN_FILE)
    rows = []
    for key, meta in CONNECTORS.items():
        required = set(meta.get("scopes") or [])
        oauth_ok = bool(required) and required.issubset(scopes)
        extra_ok = True
        if meta.get("setting"):
            extra_ok = bool(cfg.get(meta["setting"]))
        if key == "search_console":
            legacy_ok = bool(legacy_search_console.get("configured"))
            connected = oauth_ok or legacy_ok
            state = "connected" if connected else "available"
            detail = "Compte de service Search Console actif" if legacy_ok and not oauth_ok else ("OAuth Google autorisé" if oauth_ok else "À connecter")
        elif meta["mode"] == "api_key":
            connected = extra_ok
            state = "connected" if connected else "available"
            detail = "Clé API configurée" if connected else "Clé API requise"
        else:
            connected = oauth_ok and extra_ok
            if oauth_ok and not extra_ok:
                state = "attention"
                detail = "OAuth autorisé · paramètre complémentaire requis"
            else:
                state = "connected" if connected else "available"
                detail = "Connecté" if connected else "À connecter"
        rows.append({
            "id": key,
            "label": meta["label"],
            "category": meta["category"],
            "description": meta["description"],
            "mode": meta["mode"],
            "connected": connected,
            "state": state,
            "detail": detail,
            "requiredScopes": list(meta.get("scopes") or []),
        })
    return {
        "provider": "google",
        "oauthClient": client,
        "oauthAuthorized": bool(token.get("refresh_token") or token.get("access_token")),
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
    redirect_uri = base_url.rstrip("/") + "/api/integrations/google/oauth/callback"
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
        raise IntegrationError("Google a refusé l’autorisation : " + str(error))
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
    redirect_uri = base_url.rstrip("/") + "/api/integrations/google/oauth/callback"
    if pending.get("redirect_uri") != redirect_uri:
        raise IntegrationError("URI de redirection OAuth incohérente.")
    client = _load(CLIENT_FILE)
    try:
        response = requests.post(
            client.get("token_uri") or TOKEN_URL,
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
        try:
            message = response.json().get("error_description") or response.json().get("error")
        except Exception:
            message = response.text[:300]
        raise IntegrationError(f"Échange OAuth Google refusé : {message}")
    incoming = response.json()
    previous = _load(TOKEN_FILE)
    if not incoming.get("refresh_token") and previous.get("refresh_token"):
        incoming["refresh_token"] = previous["refresh_token"]
    previous_scopes = _granted_scopes()
    new_scopes = set(str(incoming.get("scope") or "").split())
    incoming["scope"] = " ".join(sorted(previous_scopes | new_scopes))
    now = datetime.datetime.now(datetime.timezone.utc)
    incoming["connected_at"] = now.isoformat()
    if incoming.get("expires_in"):
        incoming["expires_at"] = (now + datetime.timedelta(seconds=max(0, int(incoming["expires_in"]) - 30))).isoformat()
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
            client.get("token_uri") or TOKEN_URL,
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
    incoming = response.json()
    token.update(incoming)
    token["refresh_token"] = refresh
    if not token.get("scope"):
        token["scope"] = " ".join(sorted(_granted_scopes()))
    now = datetime.datetime.now(datetime.timezone.utc)
    if incoming.get("expires_in"):
        token["expires_at"] = (now + datetime.timedelta(seconds=max(0, int(incoming["expires_in"]) - 30))).isoformat()
    _atomic_json(TOKEN_FILE, token)
    if not token.get("access_token"):
        raise IntegrationError("Google n’a pas retourné de jeton d’accès.")
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
