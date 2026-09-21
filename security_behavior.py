from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import datetime
import hashlib
import math
import os
import sqlite3
import statistics
import threading
import time

STATE_DIR = Path(os.environ.get('CYBERCHECK_SECURITY_DIR', '/root/CyberCheckSecurity'))
DB = STATE_DIR / 'security.sqlite3'
_LOCK = threading.RLock()
_SESSIONS = defaultdict(lambda: {
    'requests': deque(), 'responses': deque(), 'paths': deque(),
    'methods': deque(), 'categories': deque(), 'last_persist': 0.0,
})


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _day():
    return datetime.date.today().isoformat()

def init_db():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS behavior_profiles(
          day TEXT NOT NULL,
          fingerprint TEXT NOT NULL,
          client_hash TEXT NOT NULL,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          requests INTEGER NOT NULL DEFAULT 0,
          errors INTEGER NOT NULL DEFAULT 0,
          unique_paths INTEGER NOT NULL DEFAULT 0,
          max_risk REAL NOT NULL DEFAULT 0,
          classification TEXT NOT NULL DEFAULT 'normal',
          PRIMARY KEY(day,fingerprint)
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_behavior_risk ON behavior_profiles(day,max_risk DESC)')
    DB.chmod(0o600)


def fingerprint(client_hash: str, headers) -> str:
    ua = (headers.get('User-Agent') or '').strip().lower()[:300]
    lang = (headers.get('Accept-Language') or '').strip().lower()[:120]
    accept = (headers.get('Accept') or '').strip().lower()[:180]
    chua = (headers.get('Sec-CH-UA') or '').strip().lower()[:180]
    platform = (headers.get('Sec-CH-UA-Platform') or '').strip().lower()[:80]
    material = '|'.join((client_hash, ua, lang, accept, chua, platform))
    return hashlib.sha256(material.encode()).hexdigest()[:24]

def _category(path: str) -> str:
    p = (path or '/').lower()
    if p.startswith('/admin') or p.startswith('/api/admin'):
        return 'admin'
    if p.startswith('/api/'):
        return 'api'
    if p.startswith('/assets/') or p.endswith(('.css','.js','.png','.jpg','.jpeg','.webp','.svg','.ico','.mp4','.webm','.woff','.woff2')):
        return 'asset'
    if p.startswith('/.') or any(x in p for x in ('backup','config','swagger','openapi','graphql','phpmyadmin','wp-admin')):
        return 'probe'
    return 'public'


def _prune_times(q: deque, now: float, window: float):
    while q and now - q[0] > window:
        q.popleft()


def _prune_pairs(q: deque, now: float, window: float):
    while q and now - q[0][0] > window:
        q.popleft()


def _classification(risk: float) -> str:
    if risk >= 85: return 'scanner'
    if risk >= 65: return 'high-risk'
    if risk >= 35: return 'suspicious'
    if risk >= 18: return 'automation'
    return 'normal'

def _metrics(state: dict, headers, now: float) -> tuple[float, list[str], dict]:
    req60 = [t for t in state['requests'] if now - t <= 60]
    req300 = list(state['requests'])
    unique = len({p for _, p in state['paths']})
    methods = len({m for _, m in state['methods']})
    categories = [c for _, c in state['categories']]
    risk = 0.0
    reasons = []
    if len(req60) >= 90:
        risk, reasons = max(risk, 55), reasons + ['very_high_request_rate']
    elif len(req60) >= 45:
        risk, reasons = max(risk, 28), reasons + ['high_request_rate']
    if unique >= 55:
        risk, reasons = max(risk, 62), reasons + ['wide_path_sweep']
    elif unique >= 25:
        risk, reasons = max(risk, 34), reasons + ['path_sweep']
    if methods >= 4:
        risk, reasons = max(risk, 25), reasons + ['method_diversity']
    if categories.count('admin') >= 12 and len(req300) >= 15:
        risk, reasons = max(risk, 42), reasons + ['admin_surface_focus']
    times = sorted(req300)
    if len(times) >= 12:
        intervals = [b-a for a,b in zip(times, times[1:]) if b > a]
        if len(intervals) >= 8:
            mean = statistics.fmean(intervals)
            if mean > 0:
                cv = statistics.pstdev(intervals) / mean if len(intervals) > 1 else 1.0
                if mean < 3.0 and cv < 0.12:
                    risk, reasons = max(risk, 31), reasons + ['machine_cadence']
    ua = (headers.get('User-Agent') or '').lower()
    if 'mozilla/' in ua:
        if not headers.get('Accept-Language'):
            risk, reasons = max(risk, 12), reasons + ['browser_missing_language']
        if not headers.get('Sec-Fetch-Site'):
            risk, reasons = max(risk, 9), reasons + ['browser_missing_fetch_metadata']
    probe_share = (categories.count('probe') / len(categories)) if categories else 0.0
    if probe_share >= 0.2 and len(categories) >= 5:
        risk, reasons = max(risk, 74), reasons + ['probe_heavy_session']
    metrics = {'req60': len(req60), 'req300': len(req300), 'uniquePaths': unique,
               'methodCount': methods, 'probeShare': round(probe_share, 3)}
    return risk, sorted(set(reasons)), metrics


def _persist(fp: str, client: str, state: dict, risk: float, force=False):
    init_db()
    now = time.monotonic()
    if not force and now - state.get('last_persist', 0.0) < 10 and risk < 35:
        return
    state['last_persist'] = now
    responses = list(state['responses'])
    errors = sum(1 for _, status in responses if status >= 400)
    unique = len({p for _, p in state['paths']})
    stamp = _now_iso(); day = _day(); cls = _classification(risk)
    with sqlite3.connect(DB) as db:
        db.execute('''INSERT INTO behavior_profiles(day,fingerprint,client_hash,first_seen,last_seen,requests,errors,unique_paths,max_risk,classification)
          VALUES(?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(day,fingerprint) DO UPDATE SET
          last_seen=excluded.last_seen,
          requests=MAX(behavior_profiles.requests,excluded.requests),
          errors=MAX(behavior_profiles.errors,excluded.errors),
          unique_paths=MAX(behavior_profiles.unique_paths,excluded.unique_paths),
          max_risk=MAX(behavior_profiles.max_risk,excluded.max_risk),
          classification=CASE WHEN excluded.max_risk>=behavior_profiles.max_risk THEN excluded.classification ELSE behavior_profiles.classification END''',
          (day,fp,client,stamp,stamp,len(state['requests']),errors,unique,round(float(risk),2),cls))


def observe_request(client: str, headers, method: str, path: str) -> dict:
    now = time.monotonic(); fp = fingerprint(client, headers)
    with _LOCK:
        state = _SESSIONS[fp]
        state['requests'].append(now); state['paths'].append((now, path))
        state['methods'].append((now, method.upper())); state['categories'].append((now, _category(path)))
        _prune_times(state['requests'], now, 300)
        for key in ('paths','methods','categories','responses'):
            _prune_pairs(state[key], now, 300)
        risk, reasons, metrics = _metrics(state, headers, now)
        _persist(fp, client, state, risk)
    return {'fingerprint': fp, 'risk': round(risk,1), 'reasons': reasons, 'metrics': metrics,
            'classification': _classification(risk)}

def observe_response(fp: str, client: str, status: int) -> dict:
    if not fp:
        return {'risk': 0.0, 'reasons': []}
    now = time.monotonic()
    with _LOCK:
        state = _SESSIONS[fp]
        state['responses'].append((now, int(status)))
        _prune_pairs(state['responses'], now, 300)
        responses = list(state['responses'])
        total = len(responses); errors = sum(1 for _,s in responses if s >= 400)
        not_found = sum(1 for _,s in responses if s == 404)
        risk = 0.0; reasons = []
        if total >= 10 and errors / total >= 0.60:
            risk, reasons = max(risk, 55), reasons + ['high_error_ratio']
        elif total >= 10 and errors / total >= 0.35:
            risk, reasons = max(risk, 31), reasons + ['elevated_error_ratio']
        if total >= 10 and not_found / total >= 0.50:
            risk, reasons = max(risk, 58), reasons + ['enumeration_404_ratio']
        _persist(fp, client, state, risk, force=risk >= 35)
    return {'risk': round(risk,1), 'reasons': sorted(set(reasons)), 'classification': _classification(risk)}


def profiles(limit=25, days=1):
    init_db()
    limit = max(1, min(int(limit), 100)); days = max(1, min(int(days), 30))
    since = (datetime.date.today() - datetime.timedelta(days=days-1)).isoformat()
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('''SELECT day,fingerprint,client_hash,last_seen,requests,errors,unique_paths,max_risk,classification
          FROM behavior_profiles WHERE day>=? ORDER BY max_risk DESC,last_seen DESC LIMIT ?''',(since,limit))]
    return rows
