from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import datetime
import json
import os
import tempfile

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

import integration_hub as integrations

SCOPES = ['https://www.googleapis.com/auth/webmasters']
WEBMASTERS = 'https://www.googleapis.com/webmasters/v3'
INSPECTION = 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REPORTING_TZ = ZoneInfo('America/Los_Angeles')
CREDS = Path(os.environ.get('CYBERCHECK_GSC_CREDENTIALS_PATH', '/root/.config/cybercheck/gsc-service-account.json'))


class GSCError(RuntimeError):
    def __init__(self, message, *, status=0, retry_after='', retryable=False):
        self.status = int(status or 0)
        self.retry_after = str(retry_after or '')[:80]
        self.retryable = bool(retryable)
        super().__init__(str(message or 'Erreur Google Search Console')[:180])


def _valid_service_account_payload(data):
    if not isinstance(data, dict) or data.get('type') != 'service_account':
        return False
    required = ('client_email', 'private_key', 'project_id')
    if any(not str(data.get(key) or '').strip() for key in required):
        return False
    return str(data.get('token_uri') or '').strip() == TOKEN_URL


def _read_service_account():
    if not CREDS.exists():
        return None, False
    try:
        data = json.loads(CREDS.read_text())
    except (OSError, TypeError, ValueError):
        return None, True
    if not _valid_service_account_payload(data):
        return None, True
    return data, False


def _oauth_info_if_usable():
    try:
        if not integrations.has_usable_scopes(SCOPES):
            return None
        return integrations.oauth_client_info()
    except OSError:
        return None


def credential_info():
    data, static_invalid = _read_service_account()
    if data is not None:
        return {
            'configured': True,
            'mode': 'service_account',
            'clientEmail': data.get('client_email'),
            'projectId': data.get('project_id'),
            'serviceAccountInvalid': False,
        }
    oauth_info = _oauth_info_if_usable()
    if oauth_info is not None:
        return {
            'configured': True,
            'mode': 'oauth',
            'clientEmail': 'Compte Google OAuth',
            'projectId': oauth_info.get('projectId'),
            'serviceAccountInvalid': static_invalid,
        }
    if static_invalid:
        return {
            'configured': False,
            'mode': 'service_account_invalid',
            'clientEmail': None,
            'projectId': None,
            'serviceAccountInvalid': True,
        }
    return {
        'configured': False,
        'mode': None,
        'clientEmail': None,
        'projectId': None,
        'serviceAccountInvalid': False,
    }


def save_credentials(payload):
    if not isinstance(payload, dict) or payload.get('type') != 'service_account':
        raise GSCError('Le fichier doit être un compte de service Google valide.')
    required = ('client_email', 'private_key', 'token_uri', 'project_id')
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise GSCError('Champs Google manquants : ' + ', '.join(missing))
    if str(payload.get('token_uri') or '').strip() != TOKEN_URL:
        raise GSCError('token_uri Google non approuvée.')
    CREDS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='gsc-', suffix='.json', dir=str(CREDS.parent))
    try:
        with os.fdopen(fd, 'w') as file_obj:
            json.dump(payload, file_obj)
            file_obj.write('\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, CREDS)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return credential_info()


def remove_credentials():
    if CREDS.exists():
        CREDS.unlink()
    return credential_info()


def _access_token():
    data, _static_invalid = _read_service_account()
    if data is not None:
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(CREDS),
                scopes=SCOPES,
            )
            creds.refresh(GoogleAuthRequest())
            token = creds.token
        except Exception as exc:
            raise GSCError(
                'Authentification du compte de service Search Console impossible.',
                retryable=True,
            ) from exc
        if not token:
            raise GSCError(
                'Le compte de service Search Console n’a pas retourné de jeton d’accès.'
            )
        return token
    try:
        return integrations.google_access_token(SCOPES)
    except integrations.IntegrationHTTPError as exc:
        raise GSCError(
            'Autorisation Google Search Console temporairement indisponible.',
            status=exc.status,
            retry_after=exc.retry_after,
            retryable=exc.retryable,
        ) from exc
    except integrations.IntegrationError as exc:
        raise GSCError('Autorisation Google Search Console indisponible.') from exc


def _request(method, url, **kwargs):
    headers = dict(kwargs.pop('headers', {}))
    headers['Authorization'] = 'Bearer ' + _access_token()
    if 'json' in kwargs:
        headers['Content-Type'] = 'application/json'
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=25,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise GSCError(
            'Connexion à Google Search Console impossible.',
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        status_code = int(response.status_code)
        raise GSCError(
            'Google Search Console a refusé la requête.',
            status=status_code,
            retry_after=response.headers.get('Retry-After', ''),
            retryable=status_code in {429, 500, 502, 503, 504},
        )
    if not response.content:
        return {}
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise GSCError('Réponse Google Search Console invalide.') from exc
    if not isinstance(payload, dict):
        raise GSCError('Réponse Google Search Console invalide.')
    return payload


def list_properties():
    return _request('GET', WEBMASTERS + '/sites').get('siteEntry', [])


def property_status(site_url):
    props = list_properties()
    match = next((p for p in props if p.get('siteUrl') == site_url), None)
    return {
        'siteUrl': site_url,
        'accessible': bool(match),
        'permissionLevel': match.get('permissionLevel') if match else None,
        'properties': props,
    }


def _analytics_query(site_url, start, end, dimensions=None, row_limit=25):
    body = {'startDate': start, 'endDate': end, 'rowLimit': row_limit}
    if dimensions:
        body['dimensions'] = dimensions
    url = f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/searchAnalytics/query"
    return _request('POST', url, json=body)


def reporting_today(now=None):
    current = now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    return current.astimezone(REPORTING_TZ).date()


def performance(site_url, days=28):
    days = max(1, min(int(days), 90))
    end = reporting_today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days - 1)
    start_s, end_s = start.isoformat(), end.isoformat()
    summary_rows = _analytics_query(site_url, start_s, end_s, row_limit=1).get('rows', [])
    summary = summary_rows[0] if summary_rows else {
        'clicks': 0,
        'impressions': 0,
        'ctr': 0,
        'position': 0,
    }
    queries = _analytics_query(site_url, start_s, end_s, ['query'], 25).get('rows', [])
    pages = _analytics_query(site_url, start_s, end_s, ['page'], 25).get('rows', [])
    daily = _analytics_query(site_url, start_s, end_s, ['date'], 90).get('rows', [])
    return {
        'startDate': start_s,
        'endDate': end_s,
        'summary': summary,
        'topQueries': queries,
        'topPages': pages,
        'daily': daily,
    }


def list_sitemaps(site_url):
    url = f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/sitemaps"
    return _request('GET', url).get('sitemap', [])


def submit_sitemap(site_url, sitemap_url):
    url = f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/sitemaps/{quote(sitemap_url, safe='')}"
    _request('PUT', url)
    return {'submitted': True, 'sitemapUrl': sitemap_url}


def inspect_url(site_url, inspection_url, language='fr-FR'):
    body = {
        'inspectionUrl': inspection_url,
        'siteUrl': site_url,
        'languageCode': language,
    }
    return _request('POST', INSPECTION, json=body)
