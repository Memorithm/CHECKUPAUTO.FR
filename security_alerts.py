from __future__ import annotations

from pathlib import Path
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import sqlite3
import threading
from urllib.parse import urlparse

import requests

STATE_DIR = Path(os.environ.get('CYBERCHECK_SECURITY_DIR', '/root/CyberCheckSecurity'))
DB = STATE_DIR / 'security.sqlite3'
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD = None
LEVELS = ('info','low','medium','high','critical')
DELIVERY_BACKOFF_BASE_SECONDS = 60
DELIVERY_BACKOFF_MAX_SECONDS = 3600
_DELIVERY_COLUMNS = {
    'delivery_attempts': "INTEGER NOT NULL DEFAULT 0",
    'last_delivery_attempt_at': "TEXT NOT NULL DEFAULT ''",
    'next_delivery_attempt_at': "TEXT NOT NULL DEFAULT ''",
    'last_delivery_error': "TEXT NOT NULL DEFAULT ''",
}


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _now():
    return _utcnow().isoformat(timespec='seconds')


def init_db():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS security_alerts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          level TEXT NOT NULL,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT '',
          fingerprint TEXT NOT NULL DEFAULT '',
          dedup_key TEXT NOT NULL DEFAULT '',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          acknowledged INTEGER NOT NULL DEFAULT 0,
          delivered INTEGER NOT NULL DEFAULT 0
        )''')
        existing = {row[1] for row in db.execute('PRAGMA table_info(security_alerts)')}
        for column, definition in _DELIVERY_COLUMNS.items():
            if column not in existing:
                db.execute(f'ALTER TABLE security_alerts ADD COLUMN {column} {definition}')
        db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_created ON security_alerts(created_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_ack ON security_alerts(acknowledged,created_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_delivery_due ON security_alerts(delivered,acknowledged,next_delivery_attempt_at)')
    DB.chmod(0o600)


def _resolve_endpoint_ips(host: str, port: int) -> list[str]:
    addresses = []
    for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        address = item[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


def delivery_status() -> dict:
    url = os.environ.get('CYBERCHECK_SECURITY_ALERT_WEBHOOK','').strip()
    secret = os.environ.get('CYBERCHECK_SECURITY_ALERT_SECRET','').strip()
    if not url:
        return {'configured': False, 'ready': False, 'state': 'awaiting_webhook', 'signed': False}
    parsed = urlparse(url)
    if parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        return {'configured': True, 'ready': False, 'state': 'invalid_endpoint', 'signed': bool(secret)}
    try:
        port = parsed.port or 443
        addresses = _resolve_endpoint_ips(parsed.hostname, port)
    except (OSError, ValueError):
        return {'configured': True, 'ready': False, 'state': 'endpoint_unresolved', 'signed': bool(secret), 'endpointHost': parsed.hostname}
    if not addresses:
        return {'configured': True, 'ready': False, 'state': 'endpoint_unresolved', 'signed': bool(secret), 'endpointHost': parsed.hostname}
    try:
        public_only = all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError:
        public_only = False
    if not public_only:
        return {'configured': True, 'ready': False, 'state': 'private_endpoint_rejected', 'signed': bool(secret), 'endpointHost': parsed.hostname}
    if not secret:
        return {'configured': True, 'ready': False, 'state': 'awaiting_signing_secret', 'signed': False, 'endpointHost': parsed.hostname}
    return {'configured': True, 'ready': True, 'state': 'ready', 'signed': True, 'endpointHost': parsed.hostname}


def _deliver(alert: dict):
    status = delivery_status()
    if not status['ready']:
        return False
    url = os.environ.get('CYBERCHECK_SECURITY_ALERT_WEBHOOK','').strip()
    raw = json.dumps(alert,ensure_ascii=False,separators=(',',':')).encode()
    secret = os.environ.get('CYBERCHECK_SECURITY_ALERT_SECRET','').strip()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    headers = {
        'Content-Type':'application/json',
        'User-Agent':'CyberCheck-Sentinel/1.0',
        'X-CyberCheck-Signature':'sha256=' + sig,
    }
    r = requests.post(url,data=raw,headers=headers,timeout=8,allow_redirects=False)
    r.raise_for_status()
    if not 200 <= int(r.status_code) < 300:
        return False
    return True


def _delivery_backoff_seconds(attempts: int) -> int:
    exponent = max(0, min(int(attempts) - 1, 16))
    return min(DELIVERY_BACKOFF_MAX_SECONDS, DELIVERY_BACKOFF_BASE_SECONDS * (2 ** exponent))


def _delivery_error(exc: Exception) -> str:
    if isinstance(exc, requests.Timeout):
        return 'timeout'
    if isinstance(exc, requests.ConnectionError):
        return 'connection_error'
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        return f'http_{int(status)}' if status is not None else 'http_error'
    if isinstance(exc, requests.RequestException):
        return 'request_error'
    return type(exc).__name__[:80] or 'delivery_error'


def _record_delivery_result(alert_id: int, *, delivered: bool, error: str = '', now=None) -> dict:
    now = now or _utcnow()
    attempted_at = now.isoformat(timespec='seconds')
    with _LOCK, sqlite3.connect(DB) as db:
        row = db.execute('SELECT delivery_attempts FROM security_alerts WHERE id=?', (int(alert_id),)).fetchone()
        if not row:
            return {'attempts': 0, 'nextAttemptAt': ''}
        attempts = int(row[0] or 0) + 1
        if delivered:
            db.execute(
                "UPDATE security_alerts SET delivered=1,delivery_attempts=?,last_delivery_attempt_at=?,"
                "next_delivery_attempt_at='',last_delivery_error='' WHERE id=?",
                (attempts, attempted_at, int(alert_id)),
            )
            return {'attempts': attempts, 'nextAttemptAt': ''}
        next_attempt = (now + datetime.timedelta(seconds=_delivery_backoff_seconds(attempts))).isoformat(timespec='seconds')
        db.execute(
            "UPDATE security_alerts SET delivery_attempts=?,last_delivery_attempt_at=?,"
            "next_delivery_attempt_at=?,last_delivery_error=? WHERE id=?",
            (attempts, attempted_at, next_attempt, str(error)[:80], int(alert_id)),
        )
        return {'attempts': attempts, 'nextAttemptAt': next_attempt}


def _attempt_delivery(alert_id: int, payload: dict, *, now=None) -> dict:
    delivery = delivery_status()
    if not delivery['ready']:
        return {'attempted': False, 'delivered': False, 'state': delivery['state']}
    try:
        delivered = bool(_deliver(payload))
        error = '' if delivered else 'delivery_rejected'
    except Exception as exc:
        delivered = False
        error = _delivery_error(exc)
    recorded = _record_delivery_result(alert_id, delivered=delivered, error=error, now=now)
    return {'attempted': True, 'delivered': delivered, 'error': error, **recorded}

def emit(level: str, kind: str, title: str, detail='', fingerprint='', metadata=None, dedup_key='', cooldown=900):
    init_db()
    level = level if level in LEVELS else 'medium'
    kind = str(kind)[:80]; title = str(title)[:180]; detail = str(detail)[:1000]
    fingerprint = str(fingerprint or '')[:64]
    metadata = metadata if isinstance(metadata,dict) else {}
    dedup_key = dedup_key or hashlib.sha256(f'{level}|{kind}|{title}|{fingerprint}'.encode()).hexdigest()[:24]
    now = _utcnow()
    created_at = now.isoformat(timespec='seconds')
    since = (now - datetime.timedelta(seconds=max(0,int(cooldown)))).isoformat(timespec='seconds')
    with _LOCK, sqlite3.connect(DB) as db:
        row = db.execute('SELECT id FROM security_alerts WHERE dedup_key=? AND created_at>=? ORDER BY id DESC LIMIT 1',(dedup_key,since)).fetchone()
        if row:
            return {'created':False,'id':row[0]}
        cur = db.execute('''INSERT INTO security_alerts(created_at,level,kind,title,detail,fingerprint,dedup_key,metadata_json)
          VALUES(?,?,?,?,?,?,?,?)''',(created_at,level,kind,title,detail,fingerprint,dedup_key,json.dumps(metadata,ensure_ascii=False,separators=(',',':'))))
        alert_id = cur.lastrowid
    payload = {'id':alert_id,'createdAt':created_at,'level':level,'kind':kind,'title':title,'detail':detail,
               'fingerprint':fingerprint,'metadata':metadata}
    attempt = _attempt_delivery(alert_id, payload, now=now)
    return {'created':True,'id':alert_id,'delivered':bool(attempt.get('delivered')),'deliveryAttempted':bool(attempt.get('attempted'))}

def retry_pending(limit=20):
    init_db()
    delivery = delivery_status()
    if not delivery['ready']:
        return {'configured':delivery['configured'],'ready':False,'state':delivery['state'],'attempted':0,'delivered':0,'deferred':0}
    limit=max(1,min(int(limit),100)); attempted=0; delivered=0
    now = _utcnow()
    now_text = now.isoformat(timespec='seconds')
    with sqlite3.connect(DB) as db:
        db.row_factory=sqlite3.Row
        deferred = db.execute('''SELECT COUNT(*) n FROM security_alerts
          WHERE delivered=0 AND acknowledged=0 AND level IN ('high','critical')
          AND next_delivery_attempt_at<>'' AND next_delivery_attempt_at>?''', (now_text,)).fetchone()['n']
        rows=[dict(r) for r in db.execute('''SELECT id,created_at,level,kind,title,detail,fingerprint,metadata_json
          FROM security_alerts WHERE delivered=0 AND acknowledged=0 AND level IN ('high','critical')
          AND (next_delivery_attempt_at='' OR next_delivery_attempt_at<=?)
          ORDER BY id ASC LIMIT ?''',(now_text,limit))]
    for row in rows:
        try: metadata=json.loads(row.pop('metadata_json') or '{}')
        except Exception: metadata={}
        payload={'id':row['id'],'createdAt':row['created_at'],'level':row['level'],'kind':row['kind'],
                 'title':row['title'],'detail':row['detail'],'fingerprint':row['fingerprint'],'metadata':metadata}
        result = _attempt_delivery(row['id'], payload, now=now)
        if result.get('attempted'):
            attempted += 1
        if result.get('delivered'):
            delivered += 1
    return {'configured':True,'ready':True,'state':'ready','attempted':attempted,'delivered':delivered,'deferred':int(deferred)}


def _loop(interval):
    while not _STOP.wait(max(60,int(interval))):
        try: retry_pending(20)
        except Exception: pass


def start(interval=120):
    init_db()
    global _THREAD
    if _THREAD and _THREAD.is_alive(): return
    _THREAD=threading.Thread(target=_loop,args=(interval,),daemon=True,name='CyberCheckSecurityAlerts')
    _THREAD.start()


def stop():
    _STOP.set()


def list_alerts(limit=50, unacknowledged=False):
    init_db()
    limit = max(1,min(int(limit),200))
    where = 'WHERE acknowledged=0' if unacknowledged else ''
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute(f'''SELECT id,created_at,level,kind,title,detail,fingerprint,acknowledged,delivered,
          delivery_attempts,last_delivery_attempt_at,next_delivery_attempt_at,last_delivery_error
          FROM security_alerts {where} ORDER BY id DESC LIMIT ?''',(limit,))]
    return rows


def acknowledge(alert_id: int):
    init_db()
    with sqlite3.connect(DB) as db:
        cur = db.execute('UPDATE security_alerts SET acknowledged=1 WHERE id=?',(int(alert_id),))
    return {'ok':True,'updated':cur.rowcount}


def resolve_after_rebaseline():
    init_db()
    with sqlite3.connect(DB) as db:
        cur=db.execute('''UPDATE security_alerts SET acknowledged=1 WHERE acknowledged=0 AND (
          kind='integrity' OR
          (kind='system_event' AND detail='integrity_mismatch') OR
          (kind='ai_supervisor' AND detail LIKE '%intégrité ALERTE%')
        )''')
    return {'ok':True,'updated':cur.rowcount}


def resolve_recovered_dependencies(*, dependencies_ok: bool, vulnerability_count) -> dict:
    # Only conditions that can be proven healthy by the current dependency
    # posture are auto-resolved. Attack/quarantine alerts remain operator-owned.
    init_db()
    kinds = []
    if dependencies_ok is True:
        kinds.append('dependency_drift')
    if vulnerability_count == 0:
        kinds.append('dependency_vulnerability')
    if not kinds:
        return {'ok':True,'updated':0,'kinds':[]}
    placeholders = ','.join('?' for _ in kinds)
    with sqlite3.connect(DB) as db:
        cur = db.execute(
            f'''UPDATE security_alerts SET acknowledged=1
                WHERE acknowledged=0 AND kind IN ({placeholders})''',
            kinds,
        )
    return {'ok':True,'updated':cur.rowcount,'kinds':kinds}


def summary():
    init_db()
    now_text = _now()
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        open_count = db.execute('SELECT COUNT(*) n FROM security_alerts WHERE acknowledged=0').fetchone()['n']
        high = db.execute("SELECT COUNT(*) n FROM security_alerts WHERE acknowledged=0 AND level IN ('high','critical')").fetchone()['n']
        undelivered = db.execute("SELECT COUNT(*) n FROM security_alerts WHERE acknowledged=0 AND delivered=0 AND level IN ('high','critical')").fetchone()['n']
        deferred = db.execute('''SELECT COUNT(*) n FROM security_alerts
          WHERE acknowledged=0 AND delivered=0 AND level IN ('high','critical')
          AND next_delivery_attempt_at<>'' AND next_delivery_attempt_at>?''', (now_text,)).fetchone()['n']
        eligible = db.execute('''SELECT COUNT(*) n FROM security_alerts
          WHERE acknowledged=0 AND delivered=0 AND level IN ('high','critical')
          AND (next_delivery_attempt_at='' OR next_delivery_attempt_at<=?)''', (now_text,)).fetchone()['n']
        fields = '''id,created_at,level,kind,title,detail,fingerprint,acknowledged,delivered,
                    delivery_attempts,last_delivery_attempt_at,next_delivery_attempt_at,last_delivery_error'''
        actionable = [dict(r) for r in db.execute(f'''SELECT {fields}
          FROM security_alerts
          WHERE acknowledged=0 AND level IN ('high','critical')
          ORDER BY id DESC LIMIT 50''')]
        latest = [dict(r) for r in db.execute(f'''SELECT {fields}
          FROM security_alerts ORDER BY id DESC LIMIT 25''')]
        failure = db.execute('''SELECT last_delivery_attempt_at,last_delivery_error,delivery_attempts,next_delivery_attempt_at
          FROM security_alerts WHERE acknowledged=0 AND delivered=0 AND last_delivery_error<>''
          ORDER BY last_delivery_attempt_at DESC,id DESC LIMIT 1''').fetchone()
    delivery = delivery_status()
    delivery['retry'] = {
        'baseSeconds': DELIVERY_BACKOFF_BASE_SECONDS,
        'maxSeconds': DELIVERY_BACKOFF_MAX_SECONDS,
        'eligible': int(eligible),
        'deferred': int(deferred),
        'lastFailure': ({
            'at': failure['last_delivery_attempt_at'],
            'reason': failure['last_delivery_error'],
            'attempts': int(failure['delivery_attempts'] or 0),
            'nextAttemptAt': failure['next_delivery_attempt_at'],
        } if failure else None),
    }
    return {'open':open_count,'highOrCritical':high,'undeliveredHighOrCritical':undelivered,
            'actionable':actionable,'latest':latest,
            'webhookConfigured':delivery['configured'],'delivery':delivery}
