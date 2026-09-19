from __future__ import annotations

from pathlib import Path
import datetime
import hashlib
import hmac
import json
import os
import sqlite3
import threading

import requests

STATE_DIR = Path('/root/CyberCheckSecurity')
DB = STATE_DIR / 'security.sqlite3'
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD = None
LEVELS = ('info','low','medium','high','critical')


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


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
        db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_created ON security_alerts(created_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_alerts_ack ON security_alerts(acknowledged,created_at DESC)')
    DB.chmod(0o600)


def _deliver(alert: dict):
    url = os.environ.get('CYBERCHECK_SECURITY_ALERT_WEBHOOK','').strip()
    if not url:
        return False
    raw = json.dumps(alert,ensure_ascii=False,separators=(',',':')).encode()
    headers = {'Content-Type':'application/json','User-Agent':'CyberCheck-Sentinel/1.0'}
    secret = os.environ.get('CYBERCHECK_SECURITY_ALERT_SECRET','').strip()
    if secret:
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        headers['X-CyberCheck-Signature'] = 'sha256=' + sig
    r = requests.post(url,data=raw,headers=headers,timeout=8)
    r.raise_for_status()
    return True

def emit(level: str, kind: str, title: str, detail='', fingerprint='', metadata=None, dedup_key='', cooldown=900):
    init_db()
    level = level if level in LEVELS else 'medium'
    kind = str(kind)[:80]; title = str(title)[:180]; detail = str(detail)[:1000]
    fingerprint = str(fingerprint or '')[:64]
    metadata = metadata if isinstance(metadata,dict) else {}
    dedup_key = dedup_key or hashlib.sha256(f'{level}|{kind}|{title}|{fingerprint}'.encode()).hexdigest()[:24]
    now = datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(seconds=max(0,int(cooldown)))).isoformat(timespec='seconds')
    with _LOCK, sqlite3.connect(DB) as db:
        row = db.execute('SELECT id FROM security_alerts WHERE dedup_key=? AND created_at>=? ORDER BY id DESC LIMIT 1',(dedup_key,since)).fetchone()
        if row:
            return {'created':False,'id':row[0]}
        cur = db.execute('''INSERT INTO security_alerts(created_at,level,kind,title,detail,fingerprint,dedup_key,metadata_json)
          VALUES(?,?,?,?,?,?,?,?)''',(_now(),level,kind,title,detail,fingerprint,dedup_key,json.dumps(metadata,ensure_ascii=False,separators=(',',':'))))
        alert_id = cur.lastrowid
    payload = {'id':alert_id,'createdAt':_now(),'level':level,'kind':kind,'title':title,'detail':detail,
               'fingerprint':fingerprint,'metadata':metadata}
    delivered = False
    try: delivered = _deliver(payload)
    except Exception: delivered = False
    if delivered:
        with sqlite3.connect(DB) as db: db.execute('UPDATE security_alerts SET delivered=1 WHERE id=?',(alert_id,))
    return {'created':True,'id':alert_id,'delivered':delivered}

def retry_pending(limit=20):
    init_db()
    url=os.environ.get('CYBERCHECK_SECURITY_ALERT_WEBHOOK','').strip()
    if not url:
        return {'configured':False,'attempted':0,'delivered':0}
    limit=max(1,min(int(limit),100)); attempted=0; delivered=0
    with sqlite3.connect(DB) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('''SELECT id,created_at,level,kind,title,detail,fingerprint,metadata_json
          FROM security_alerts WHERE delivered=0 AND acknowledged=0 AND level IN ('high','critical') ORDER BY id ASC LIMIT ?''',(limit,))]
    for row in rows:
        attempted+=1
        try: metadata=json.loads(row.pop('metadata_json') or '{}')
        except Exception: metadata={}
        payload={'id':row['id'],'createdAt':row['created_at'],'level':row['level'],'kind':row['kind'],
                 'title':row['title'],'detail':row['detail'],'fingerprint':row['fingerprint'],'metadata':metadata}
        try:
            if _deliver(payload):
                with sqlite3.connect(DB) as db: db.execute('UPDATE security_alerts SET delivered=1 WHERE id=?',(row['id'],))
                delivered+=1
        except Exception:
            pass
    return {'configured':True,'attempted':attempted,'delivered':delivered}


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
        rows = [dict(r) for r in db.execute(f'''SELECT id,created_at,level,kind,title,detail,fingerprint,acknowledged,delivered
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


def summary():
    init_db()
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        open_count = db.execute('SELECT COUNT(*) n FROM security_alerts WHERE acknowledged=0').fetchone()['n']
        high = db.execute("SELECT COUNT(*) n FROM security_alerts WHERE acknowledged=0 AND level IN ('high','critical')").fetchone()['n']
        undelivered = db.execute("SELECT COUNT(*) n FROM security_alerts WHERE acknowledged=0 AND delivered=0 AND level IN ('high','critical')").fetchone()['n']
        latest = [dict(r) for r in db.execute('''SELECT id,created_at,level,kind,title,detail,fingerprint,acknowledged,delivered
          FROM security_alerts ORDER BY id DESC LIMIT 25''')]
    return {'open':open_count,'highOrCritical':high,'undeliveredHighOrCritical':undelivered,'latest':latest,
            'webhookConfigured':bool(os.environ.get('CYBERCHECK_SECURITY_ALERT_WEBHOOK','').strip())}
