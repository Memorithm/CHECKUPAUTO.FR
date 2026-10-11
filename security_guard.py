from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
import datetime
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import unquote, urlsplit
import ipaddress

import security_behavior as behavior
import security_alerts as alerts

STATE_DIR = Path(os.environ.get('CYBERCHECK_SECURITY_DIR', '/root/CyberCheckSecurity'))
DB = STATE_DIR / 'security.sqlite3'
SECRET_FILE = STATE_DIR / 'client-hmac-secret'
_LOCK = threading.RLock()
_REQ = defaultdict(deque)
_PATHS = defaultdict(deque)
_NOT_FOUND = defaultdict(deque)
_PROBES = defaultdict(deque)
_AUTH_FAIL = defaultdict(deque)
_AUTH_FAIL_BURST = {}
_AUTH_FAIL_BURST_SECONDS = 5.0
_ENDPOINT_REQ = defaultdict(deque)
_ENDPOINT_LIMITS = {'/api/geo/coverage': 6, '/api/geo/quote': 30, '/api/booking/availability': 45, '/api/events': 60, '/go/booking': 20, '/compte/reservation': 40, '/api/customer/booking/preflight': 20, '/api/customer/booking/create': 6, '/api/customer/booking/status': 40, '/api/customer/booking/vehicle-mapping': 20, '/api/booking-test/create': 10, '/api/booking-test/remove': 10, '/api/mobile/installations/register': 12, '/api/mobile/installations/delete': 12, '/api/mobile/devices/register': 12, '/api/mobile/devices/unregister': 12, '/api/mobile/claims/consume': 20, '/api/mobile/inventory': 30, '/api/mobile/reminders/sync': 30, '/api/admin/mobile/claims/issue': 12, '/api/admin/auth/2fa/setup': 4, '/api/admin/auth/2fa/confirm': 8, '/api/admin/auth/2fa/verify': 8, '/api/payments/payline/start': 8, '/api/payment-test/session': 4, '/api/payment-test/create': 4, '/api/payment-test/result': 8, '/api/payment-test/status': 12, '/api/payment-test/remove': 6, '/api/customer/reports': 6, '/compte/connexion': 10, '/compte/inscription': 4, '/compte/mot-de-passe-oublie': 4, '/compte/reinitialiser': 6, '/api/customer/vehicles': 20, '/api/customer/vehicles/delete': 10, '/api/mobile/auth/exchange': 10, '/api/mobile/auth/apple': 10, '/api/mobile/auth/apple/nonce': 10}
_BANNED = {}
_RISK = {}
_STATE_WRITE = {}
_SCANNER_UA = re.compile(r'(sqlmap|nikto|nmap|masscan|zgrab|gobuster|dirbuster|feroxbuster|ffuf|nuclei|wpscan|acunetix|nessus|openvas|burp)', re.I)
_HONEYPOTS = {'/.env','/.git/config','/wp-login.php','/phpmyadmin','/server-status','/actuator/health',
    '/backup.zip','/admin-backup.zip','/config.json','/swagger.json','/openapi.json','/graphql','/graphiql',
    '/api/internal','/api/debug','/.well-known/cybercheck-backup'}
_SENSITIVE_PATHS = (
    '/.git', '/.env', '/.svn', '/.hg', '/wp-admin', '/wp-login',
    '/phpmyadmin', '/server-status', '/actuator', '/vendor/phpunit',
    '/cgi-bin', '/config.', '/backup', '/database', '/dump', '/.aws',
)
_SENSITIVE_SUFFIXES = (
    '.bak', '.old', '.orig', '.save', '.swp', '.sql', '.sqlite', '.sqlite3',
    '.pem', '.key', '.p8', '.crt', '.p12', '.log', '.pyc', '.map', '~',
)
_QUERY_SIG = re.compile(
    r'(\.\./|%2e%2e|<script|%3cscript|union\s+select|sleep\s*\(|benchmark\s*\('
    r'|\$\{jndi:|/etc/passwd|cmd=|powershell|;\s*(?:cat|curl|wget|bash|sh)\b)',
    re.I,
)
_ALLOWED_METHODS = {'GET', 'HEAD', 'POST', 'DELETE', 'OPTIONS'}
_PUBLIC_STATIC = {'/style.css', '/app.js', '/consent.js', '/favicon.ico', '/favicon.png', '/assets/cybercheck-hero-3d.js', '/assets/cybercheck-glb-hero.js'}
_ASSET_SUFFIXES = {'.png','.jpg','.jpeg','.webp','.gif','.svg','.ico','.mp4','.webm','.glb','.gltf','.bin','.ktx2','.wasm'}
_ADMIN_SUFFIXES = {'.html','.css','.js'}
_ADMIN_PREFIX = '/admin/'


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _ensure_secret():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_urlsafe(48) + '\n')
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text().strip()
@contextmanager
def _db():
    """One transaction on a connection that is always closed (audit Q-03).

    ``with sqlite3.connect(...)`` only commits; the handle stayed open until
    garbage collection, leaking descriptors in the long-running server.
    """
    connection = sqlite3.connect(DB)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with _db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS security_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_at TEXT NOT NULL,
          client_hash TEXT NOT NULL,
          method TEXT NOT NULL,
          path TEXT NOT NULL,
          status INTEGER NOT NULL DEFAULT 0,
          risk INTEGER NOT NULL DEFAULT 0,
          action TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT ''
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_security_time ON security_events(occurred_at)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_security_client ON security_events(client_hash)')
        db.execute('''CREATE TABLE IF NOT EXISTS security_client_state(
          day TEXT NOT NULL,
          client_hash TEXT NOT NULL,
          risk REAL NOT NULL DEFAULT 0,
          last_seen TEXT NOT NULL,
          quarantine_until TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(day,client_hash)
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_security_state_day ON security_client_state(day)')
        cutoff=(datetime.date.today()-datetime.timedelta(days=7)).isoformat()
        db.execute('DELETE FROM security_client_state WHERE day<?',(cutoff,))
    DB.chmod(0o600)
    _ensure_secret()
    _restore_persistent_state()


def client_hash(ip: str) -> str:
    day = datetime.date.today().isoformat()
    raw = f'{day}|{ip or "unknown"}'.encode()
    return hmac.new(_ensure_secret().encode(), raw, hashlib.sha256).hexdigest()[:20]


TRUSTED_PROXIES_ENV = 'CYBERCHECK_TRUSTED_PROXIES'
CLIENT_IP_HEADER_ENV = 'CYBERCHECK_CLIENT_IP_HEADER'
# Production runs behind a local Cloudflare Tunnel connector (loopback peer).
DEFAULT_TRUSTED_PROXIES = '127.0.0.0/8,::1/128'
DEFAULT_CLIENT_IP_HEADER = 'cf-connecting-ip'
_CLIENT_IP_HEADERS = {'cf-connecting-ip', 'x-forwarded-for', 'none'}


def _valid_ip(value) -> str:
    try:
        return str(ipaddress.ip_address(str(value or '').strip()))
    except ValueError:
        return ''


def trusted_proxy_networks() -> tuple:
    raw = os.environ.get(TRUSTED_PROXIES_ENV)
    raw = DEFAULT_TRUSTED_PROXIES if raw is None else raw
    networks = []
    for item in str(raw).split(','):
        item = item.strip()
        if not item or item.lower() == 'none':
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def client_ip_header() -> str:
    value = str(os.environ.get(CLIENT_IP_HEADER_ENV) or DEFAULT_CLIENT_IP_HEADER).strip().lower()
    return value if value in _CLIENT_IP_HEADERS else 'none'


def _peer_is_trusted_proxy(peer: str) -> bool:
    if not peer:
        return False
    address = ipaddress.ip_address(peer)
    return any(address.version == net.version and address in net for net in trusted_proxy_networks())


def client_ip(headers, peer_ip=''):
    """Return the client address used for rate limits and bans.

    Forwarding headers are client-controlled unless the direct peer is a
    configured trusted proxy (``CYBERCHECK_TRUSTED_PROXIES``). Only the single
    header named by ``CYBERCHECK_CLIENT_IP_HEADER`` is then honoured; for
    ``X-Forwarded-For`` the right-most entry (added by the trusted proxy) is used.
    """
    peer = _valid_ip(peer_ip)
    if peer and _peer_is_trusted_proxy(peer):
        header = client_ip_header()
        forwarded = ''
        if header == 'cf-connecting-ip':
            forwarded = _valid_ip(headers.get('CF-Connecting-IP'))
        elif header == 'x-forwarded-for':
            entries = [part.strip() for part in str(headers.get('X-Forwarded-For') or '').split(',')]
            forwarded = _valid_ip(entries[-1]) if entries else ''
        if forwarded:
            return forwarded
    return (peer or str(peer_ip or '').strip() or 'unknown')[:80]


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_utc(value: str):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(datetime.timezone.utc)
    except Exception:
        return None


def _persist_state(client: str, force=False):
    if not client or client == 'system':
        return
    now_m=time.monotonic(); last=_STATE_WRITE.get(client,0.0)
    score,last_score=_RISK.get(client,(0.0,now_m))
    score=max(0.0,float(score)-max(0.0,now_m-last_score)/30.0)
    _RISK[client]=(score,now_m)
    banned=_BANNED.get(client,0.0); remaining=max(0.0,banned-now_m)
    if not force and now_m-last<5.0 and score<65 and remaining<=0:
        return
    _STATE_WRITE[client]=now_m
    now=_utcnow(); until=(now+datetime.timedelta(seconds=remaining)).isoformat(timespec='seconds') if remaining>0 else ''
    try:
        with _db() as db:
            db.execute('''INSERT INTO security_client_state(day,client_hash,risk,last_seen,quarantine_until)
              VALUES(?,?,?,?,?) ON CONFLICT(day,client_hash) DO UPDATE SET
              risk=excluded.risk,last_seen=excluded.last_seen,quarantine_until=excluded.quarantine_until''',
              (datetime.date.today().isoformat(),client,round(score,2),now.isoformat(timespec='seconds'),until))
    except Exception:
        pass


def _restore_persistent_state():
    today=datetime.date.today().isoformat(); now=_utcnow(); mono=time.monotonic()
    try:
        with _db() as db:
            db.row_factory=sqlite3.Row
            rows=list(db.execute('SELECT client_hash,risk,last_seen,quarantine_until FROM security_client_state WHERE day=?',(today,)))
        for row in rows:
            seen=_parse_utc(row['last_seen']) or now
            elapsed=max(0.0,(now-seen).total_seconds())
            score=max(0.0,float(row['risk'] or 0)-elapsed/30.0)
            if score>0:
                _RISK[row['client_hash']] = (score,mono)
            until=_parse_utc(row['quarantine_until'])
            if until and until>now:
                _BANNED[row['client_hash']] = mono+(until-now).total_seconds()
    except Exception:
        pass
def _prune(q: deque, now: float, window: float):
    while q and now - q[0] > window:
        q.popleft()


def _prune_paths(q: deque, now: float, window: float):
    while q and now - q[0][0] > window:
        q.popleft()


def _record(client: str, method: str, path: str, action: str, reason: str, risk=0, status=0):
    try:
        with _db() as db:
            db.execute(
                'INSERT INTO security_events(occurred_at,client_hash,method,path,status,risk,action,reason) VALUES(?,?,?,?,?,?,?,?)',
                (_now_iso(), client, method[:12], path[:180], int(status), int(risk), action[:24], reason[:180]),
            )
    except Exception:
        pass


def _ban(client: str, seconds: int, reason: str):
    _BANNED[client] = max(_BANNED.get(client, 0), time.monotonic() + seconds)
    _RISK[client] = (100.0,time.monotonic())
    _persist_state(client,True)
    _record(client, '-', '-', 'quarantine', reason, 100, 429)
    try:
        alerts.emit('high','automatic_quarantine','Quarantaine automatique Sentinel',reason,fingerprint=client,
                    metadata={'durationSeconds':int(seconds)},dedup_key=f'quarantine:{client}:{reason}',cooldown=900)
    except Exception:
        pass


def _risk_value(client: str, now=None) -> float:
    now = time.monotonic() if now is None else now
    score, last = _RISK.get(client, (0.0, now))
    score = max(0.0, score - max(0.0, now - last) / 30.0)
    _RISK[client] = (score, now)
    return score


def _add_risk(client: str, points: float, reason: str, path='-') -> float:
    now = time.monotonic()
    score = min(100.0, _risk_value(client, now) + max(0.0, float(points)))
    _RISK[client] = (score, now)
    _persist_state(client,force=score>=65)
    if points >= 20:
        _record(client, 'RISK', path, 'score', reason, int(score), 0)
    if score >= 85 and _BANNED.get(client, 0) <= now:
        _ban(client, 1800, 'adaptive_risk_quarantine')
    return score


def _risk_floor(client: str, floor: float, reason: str, path='-') -> float:
    now = time.monotonic(); current = _risk_value(client, now)
    score = min(100.0, max(current, float(floor or 0)))
    _RISK[client] = (score, now)
    _persist_state(client,force=score>=65)
    if score > current and score >= 25:
        _record(client, 'BEHAVIOR', path, 'score', reason, int(score), 0)
    if score >= 85 and _BANNED.get(client, 0) <= now:
        _ban(client, 1800, 'adaptive_behavior_quarantine')
    return score


def _sensitive_path(path: str) -> bool:
    p = unquote(path).lower()
    if any(x in p for x in _SENSITIVE_PATHS):
        return True
    name = p.rsplit('/', 1)[-1]
    return any(name.endswith(s) or s in name for s in _SENSITIVE_SUFFIXES)
def static_allowed(path: str, admin_authorized=False) -> bool:
    decoded = unquote(unquote(path or ''))
    parts = decoded.replace('\\', '/').split('/')
    if '\x00' in decoded or '..' in parts:
        return False
    if decoded in _PUBLIC_STATIC:
        return True
    if decoded.startswith('/assets/'):
        return Path(decoded).suffix.lower() in _ASSET_SUFFIXES
    if admin_authorized and decoded.startswith(_ADMIN_PREFIX):
        return Path(decoded).suffix.lower() in _ADMIN_SUFFIXES
    return False


def evaluate(method: str, raw_target: str, headers, peer_ip='') -> dict:
    now = time.monotonic()
    parts = urlsplit(raw_target); path = parts.path or '/'; query = parts.query or ''
    decoded_path = unquote(unquote(path))
    ip = client_ip(headers, peer_ip); client = client_hash(ip)
    ua = (headers.get('User-Agent') or '')[:300]
    behavioral = behavior.observe_request(client, headers, method, path)
    fp = behavioral.get('fingerprint','')
    with _LOCK:
        if behavioral.get('risk',0):
            _risk_floor(client, behavioral['risk'], 'behavior:' + ','.join(behavioral.get('reasons',[])[:3]), path)
        def deny(status, risk, reason):
            return {'allow':False,'status':status,'client':client,'fingerprint':fp,'path':path,
                    'risk':risk,'reason':reason,'behavior':behavioral.get('classification','normal')}
        ban_until = _BANNED.get(client, 0)
        if ban_until > now:
            return deny(429,100,'quarantine_active')
        cumulative = _risk_value(client, now)
        if cumulative >= 85:
            _ban(client, 1800, 'adaptive_risk_quarantine')
            return deny(429,100,'adaptive_risk_quarantine')
        if _SCANNER_UA.search(ua):
            cumulative = _add_risk(client, 35, 'scanner_user_agent', path)
            try: alerts.emit('high','scanner_signature','Signature de scanner détectée',ua[:120],fp,
                             {'path':path},dedup_key=f'scanner:{fp}',cooldown=1800)
            except Exception: pass
            if cumulative >= 85: return deny(429,100,'scanner_user_agent')
        elif not ua:
            cumulative = _add_risk(client, 6, 'missing_user_agent', path)
        if method.upper() not in _ALLOWED_METHODS:
            _record(client, method, path, 'block', 'method_not_allowed', 90, 405)
            return deny(405,90,'method_not_allowed')
        if len(raw_target)>4096 or len(path)>1024 or len(query)>2048:
            _record(client,method,path,'block','request_target_too_large',80,414)
            return deny(414,80,'request_target_too_large')
        normalized_parts = decoded_path.replace('\\','/').split('/')
        if '\x00' in decoded_path or '..' in normalized_parts or '\\' in decoded_path:
            cumulative=_add_risk(client,70,'path_traversal_signature',path)
            _record(client,method,path,'block','path_traversal_signature',max(95,int(cumulative)),403)
            try: alerts.emit('critical','path_traversal','Tentative de traversée de chemin',path,fp,
                             dedup_key=f'traversal:{fp}',cooldown=1800)
            except Exception: pass
            return deny(403,max(95,int(cumulative)),'path_traversal_signature')
        if decoded_path.lower() in _HONEYPOTS or _sensitive_path(path):
            q=_PROBES[client]; q.append(now); _prune(q,now,600)
            honeypot=decoded_path.lower() in _HONEYPOTS
            reason='honeypot_probe' if honeypot else 'sensitive_probe'
            cumulative=_add_risk(client,65 if honeypot else 45,reason,path)
            if honeypot:
                try: alerts.emit('high','honeypot','Leurre Sentinel déclenché',path,fp,
                                 {'clientHash':client},dedup_key=f'honeypot:{fp}:{path}',cooldown=1800)
                except Exception: pass
            if len(q)>=3: _ban(client,1800,'repeated_sensitive_probes')
            _record(client,method,path,'block',reason,max(95,int(cumulative)),404)
            return deny(404,max(95,int(cumulative)),reason)
        if _QUERY_SIG.search(unquote(query)):
            q=_PROBES[client]; q.append(now); _prune(q,now,600)
            cumulative=_add_risk(client,70,'malicious_query_signature',path)
            if len(q)>=2: _ban(client,1800,'repeated_payload_signatures')
            _record(client,method,path,'block','malicious_query_signature',max(95,int(cumulative)),403)
            try: alerts.emit('critical','payload_signature','Charge malveillante détectée',path,fp,
                             dedup_key=f'payload:{fp}',cooldown=1800)
            except Exception: pass
            return deny(403,max(95,int(cumulative)),'malicious_query_signature')
        req=_REQ[client]; req.append(now); _prune(req,now,60)
        for route, route_limit in _ENDPOINT_LIMITS.items():
            if path==route:
                eq=_ENDPOINT_REQ[(client,route)]; eq.append(now); _prune(eq,now,60)
                if len(eq)>route_limit:
                    score=_add_risk(client,20,'endpoint_rate_limit',path)
                    _record(client,method,path,'block','endpoint_rate_limit',max(70,int(score)),429)
                    return deny(429,max(70,int(score)),'endpoint_rate_limit')
                break
        paths=_PATHS[client]; paths.append((now,path)); _prune_paths(paths,now,60)
        distinct=len({p for _,p in paths}); limit=45 if path.startswith('/admin') else (90 if path.startswith('/api/') else 180)
        if len(req)>limit or distinct>70:
            _ban(client,900,'rate_or_path_sweep'); return deny(429,100,'rate_or_path_sweep')
        nf=_NOT_FOUND[client]; _prune(nf,now,60); probe=_PROBES[client]; _prune(probe,now,600)
        transient=min(100,int((len(req)/max(limit,1))*45+(distinct/70)*30+min(len(nf),25)/25*20+min(len(probe),3)/3*30))
        cumulative=_risk_value(client,now); risk=min(100,max(transient,int(cumulative),int(behavioral.get('risk',0))))
        return {'allow':True,'status':0,'client':client,'fingerprint':fp,'path':path,'risk':risk,'reason':'allow',
                'behavior':behavioral.get('classification','normal'),'behaviorReasons':behavioral.get('reasons',[])[:6]}

def observe_response(client: str, method: str, path: str, status: int, risk=0, fingerprint=''):
    now = time.monotonic()
    with _LOCK:
        b = behavior.observe_response(fingerprint, client, int(status)) if fingerprint else {'risk':0,'reasons':[]}
        if b.get('risk',0):
            _risk_floor(client,b['risk'],'behavior_response:' + ','.join(b.get('reasons',[])[:3]),path)
        if int(status)==404:
            q=_NOT_FOUND[client]; q.append(now); _prune(q,now,60)
            _add_risk(client,3,'http_404',path)
            if len(q)>=25: _ban(client,900,'excessive_404_scan')
        elif int(status)==401:
            _add_risk(client,8,'http_401',path)
        elif int(status)==403:
            _add_risk(client,15,'http_403',path)
        if int(status)>=400:
            _record(client,method,path,'response',f'http_{status}',max(int(risk),int(_risk_value(client,now))),status)


def system_event(reason: str, risk=80, action='alert', path='-'):
    _record('system','SYSTEM',str(path),str(action),str(reason),int(risk),0)
    if int(risk)>=70:
        level='critical' if int(risk)>=95 else 'high'
        try: alerts.emit(level,'system_event','Alerte système Sentinel',str(reason),metadata={'path':str(path),'risk':int(risk)},
                         dedup_key=f'system:{reason}:{path}',cooldown=900)
        except Exception: pass


def auth_failure(client: str, path='/admin/'):
    now = time.monotonic()
    with _LOCK:
        last = float(_AUTH_FAIL_BURST.get(client, 0.0) or 0.0)
        if last and now - last < _AUTH_FAIL_BURST_SECONDS:
            return
        _AUTH_FAIL_BURST[client] = now
        q = _AUTH_FAIL[client]; q.append(now); _prune(q, now, 600)
        score = _add_risk(client, 20, 'basic_auth_failed', path)
        _record(client, 'AUTH', path, 'auth_failure', 'basic_auth_failed', max(70, int(score)), 401)
        if len(q) >= 3:
            try: alerts.emit('high','admin_auth_failures','Échecs répétés d’authentification admin',
                             f'{len(q)} échecs sur 10 minutes',client,{'path':path},
                             dedup_key=f'authfail:{client}',cooldown=1200)
            except Exception: pass
        if len(q) >= 6:
            _ban(client, 1800, 'admin_bruteforce')


STATUS_MAX_DAYS = 30


def status(days=1):
    days = max(1, min(int(days), STATUS_MAX_DAYS))
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat(timespec='seconds')
    with _db() as db:
        db.row_factory = sqlite3.Row
        total = db.execute('SELECT COUNT(*) n FROM security_events WHERE occurred_at>=?', (since,)).fetchone()['n']
        blocked = db.execute("SELECT COUNT(*) n FROM security_events WHERE occurred_at>=? AND action IN ('block','quarantine')", (since,)).fetchone()['n']
        reasons = [dict(r) for r in db.execute('SELECT reason,COUNT(*) count FROM security_events WHERE occurred_at>=? GROUP BY reason ORDER BY count DESC LIMIT 12', (since,))]
        recent = [dict(r) for r in db.execute('SELECT occurred_at,client_hash,method,path,status,risk,action,reason FROM security_events WHERE occurred_at>=? ORDER BY id DESC LIMIT 40', (since,))]
    now = time.monotonic()
    active = sum(1 for t in _BANNED.values() if t > now)
    live_scores = sorted(({'clientHash': c, 'risk': round(_risk_value(c, now), 1)} for c in list(_RISK)), key=lambda x: x['risk'], reverse=True)
    live_scores = [x for x in live_scores if x['risk'] > 0][:12]
    return {'days':days,'events':total,'blocked':blocked,'activeQuarantines':active,
            'topReasons':reasons,'recent':recent,'riskClients':live_scores,
            'behaviorProfiles':behavior.profiles(20,days),'alerts':alerts.summary(),
            'statePersistence':'sqlite','privacy':'daily HMAC client hash + daily behavioral fingerprint; no raw IP storage'}

init_db()
