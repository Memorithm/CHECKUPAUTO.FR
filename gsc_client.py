from pathlib import Path
from urllib.parse import quote
import datetime, json, os, tempfile
import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
import integration_hub as integrations

SCOPES = ['https://www.googleapis.com/auth/webmasters']
WEBMASTERS = 'https://www.googleapis.com/webmasters/v3'
INSPECTION = 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect'
CREDS = Path('/root/.config/cybercheck/gsc-service-account.json')

class GSCError(RuntimeError):
    pass

def credential_info():
    if CREDS.exists():
        data = json.loads(CREDS.read_text())
        return {'configured': True, 'mode': 'service_account', 'clientEmail': data.get('client_email'), 'projectId': data.get('project_id')}
    if integrations.has_usable_scopes(SCOPES):
        info = integrations.oauth_client_info()
        return {'configured': True, 'mode': 'oauth', 'clientEmail': 'Compte Google OAuth', 'projectId': info.get('projectId')}
    return {'configured': False, 'mode': None, 'clientEmail': None, 'projectId': None}

def save_credentials(payload):
    if not isinstance(payload, dict) or payload.get('type') != 'service_account':
        raise GSCError('Le fichier doit être un compte de service Google valide.')
    required = ('client_email', 'private_key', 'token_uri', 'project_id')
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise GSCError('Champs Google manquants : ' + ', '.join(missing))
    CREDS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='gsc-', suffix='.json', dir=str(CREDS.parent))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(payload, f)
            f.write('\n')
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
    if CREDS.exists():
        creds = service_account.Credentials.from_service_account_file(str(CREDS), scopes=SCOPES)
        creds.refresh(GoogleAuthRequest())
        return creds.token
    try:
        return integrations.google_access_token(SCOPES)
    except integrations.IntegrationError as exc:
        raise GSCError(str(exc)) from exc

def _request(method, url, **kwargs):
    headers = dict(kwargs.pop('headers', {}))
    headers['Authorization'] = 'Bearer ' + _access_token()
    if 'json' in kwargs:
        headers['Content-Type'] = 'application/json'
    try:
        r = requests.request(method, url, headers=headers, timeout=25, **kwargs)
    except requests.RequestException as exc:
        raise GSCError('Erreur réseau Google Search Console : ' + str(exc)) from exc
    if r.status_code >= 400:
        try:
            body = r.json()
            message = body.get('error', {}).get('message') or r.text
        except Exception:
            message = r.text
        raise GSCError(f'Google Search Console HTTP {r.status_code}: {message[:500]}')
    if not r.content:
        return {}
    return r.json()

def list_properties():
    return _request('GET', WEBMASTERS + '/sites').get('siteEntry', [])
def property_status(site_url):
    props = list_properties()
    match = next((p for p in props if p.get('siteUrl') == site_url), None)
    return {'siteUrl': site_url, 'accessible': bool(match), 'permissionLevel': match.get('permissionLevel') if match else None, 'properties': props}

def _analytics_query(site_url, start, end, dimensions=None, row_limit=25):
    body = {'startDate': start, 'endDate': end, 'rowLimit': row_limit}
    if dimensions:
        body['dimensions'] = dimensions
    url = f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/searchAnalytics/query"
    return _request('POST', url, json=body)

def performance(site_url, days=28):
    days = max(1, min(int(days), 90))
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days - 1)
    start_s, end_s = start.isoformat(), end.isoformat()
    summary_rows = _analytics_query(site_url, start_s, end_s, row_limit=1).get('rows', [])
    summary = summary_rows[0] if summary_rows else {'clicks': 0, 'impressions': 0, 'ctr': 0, 'position': 0}
    queries = _analytics_query(site_url, start_s, end_s, ['query'], 25).get('rows', [])
    pages = _analytics_query(site_url, start_s, end_s, ['page'], 25).get('rows', [])
    daily = _analytics_query(site_url, start_s, end_s, ['date'], 90).get('rows', [])
    return {'startDate': start_s, 'endDate': end_s, 'summary': summary, 'topQueries': queries, 'topPages': pages, 'daily': daily}
def list_sitemaps(site_url):
    url = f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/sitemaps"
    return _request('GET', url).get('sitemap', [])

def submit_sitemap(site_url, sitemap_url):
    url = f"{WEBMASTERS}/sites/{quote(site_url, safe='')}/sitemaps/{quote(sitemap_url, safe='')}"
    _request('PUT', url)
    return {'submitted': True, 'sitemapUrl': sitemap_url}

def inspect_url(site_url, inspection_url, language='fr-FR'):
    body = {'inspectionUrl': inspection_url, 'siteUrl': site_url, 'languageCode': language}
    return _request('POST', INSPECTION, json=body)
