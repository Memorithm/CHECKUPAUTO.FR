from __future__ import annotations

from pathlib import Path
import datetime, os, sqlite3, threading

import mercure_admin_client as mercure

DATA_DIR=Path(os.environ.get('CYBERCHECK_DATA_DIR','/root/CyberCheckData'))
DB=DATA_DIR/'review-followup.sqlite3'
_STOP=threading.Event()
_THREAD=None
INTERVAL_SECONDS=900
DELAY_MINUTES=45
LOOKBACK_HOURS=36
MAX_ATTEMPTS=3

def _now():
    return datetime.datetime.now(datetime.timezone.utc)

def _now_iso():
    return _now().isoformat(timespec='seconds')

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    try: DATA_DIR.chmod(0o700)
    except PermissionError: pass
    db=sqlite3.connect(DB,timeout=10)
    db.row_factory=sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS review_followup(
          appointment_id TEXT PRIMARY KEY,
          first_seen_at TEXT NOT NULL,
          last_attempt_at TEXT NOT NULL DEFAULT '',
          sent_at TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT ''
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_review_followup_status ON review_followup(status,sent_at)')
    DB.chmod(0o600)

def _parse_dt(value):
    raw=str(value or '').strip()
    if not raw: return None
    for fmt in (
        '%Y-%m-%dT%H:%M:%S','%Y-%m-%dT%H:%M','%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M',
        '%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M',
    ):
        try:
            dt=datetime.datetime.strptime(raw[:19],fmt)
            return dt.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo).astimezone(datetime.timezone.utc)
        except Exception:
            pass
    try:
        dt=datetime.datetime.fromisoformat(raw.replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None

def _state(rid):
    with connect() as db:
        row=db.execute('SELECT * FROM review_followup WHERE appointment_id=?',(rid,)).fetchone()
    return dict(row) if row else None

def _mark(rid,status,error=''):
    now=_now_iso()
    with connect() as db:
        db.execute('''INSERT INTO review_followup(appointment_id,first_seen_at,last_attempt_at,status,attempts,last_error)
          VALUES(?,?,?,?,1,?)
          ON CONFLICT(appointment_id) DO UPDATE SET
          last_attempt_at=excluded.last_attempt_at,status=excluded.status,
          attempts=review_followup.attempts+1,last_error=excluded.last_error''',
          (rid,now,now,status,str(error or '')[:300]))
        if status=='sent':
            db.execute('UPDATE review_followup SET sent_at=?,last_error="" WHERE appointment_id=?',(now,rid))

def process_once():
    session=mercure.session_status()
    if not session.get('connected'):
        return {'ok':False,'state':'waiting_mercure','error':session.get('error','Session Mercure indisponible')}
    native=mercure.native_review_email_status()
    if native.get('nativeFavorableOnlyEmailEnabled'):
        try:
            mercure.disable_native_review_email_automation()
        except Exception as exc:
            return {'ok':False,'state':'native_positive_only_enabled','error':str(exc)}
    now=_now(); sent=failed=eligible=0
    for row in mercure.review_followup_rows(2):
        rid=str(row.get('id') or '').strip()
        if not rid or not row.get('honored') or not row.get('finished'): continue
        if 'CYBERCHECK TEST' in str(row.get('name') or '').upper(): continue
        at=_parse_dt(row.get('dateRdv'))
        if not at: continue
        age=(now-at).total_seconds()/3600
        if age < DELAY_MINUTES/60 or age > LOOKBACK_HOURS: continue
        eligible+=1
        state=_state(rid)
        if state and state.get('status')=='sent': continue
        if state and int(state.get('attempts') or 0)>=MAX_ATTEMPTS: continue
        try:
            mercure.send_google_review_email(rid)
            _mark(rid,'sent'); sent+=1
        except Exception as exc:
            _mark(rid,'failed',type(exc).__name__+': '+str(exc)); failed+=1
    return {'ok':True,'state':'active','eligible':eligible,'sent':sent,'failed':failed}

def status():
    session=mercure.session_status()
    native={'nativeFavorableOnlyEmailEnabled':None}
    if session.get('connected'):
        try: native=mercure.native_review_email_status()
        except Exception: pass
    cutoff=(_now()-datetime.timedelta(hours=24)).isoformat(timespec='seconds')
    with connect() as db:
        sent24=db.execute("SELECT COUNT(*) n FROM review_followup WHERE sent_at>=?",(cutoff,)).fetchone()['n']
        sent_total=db.execute("SELECT COUNT(*) n FROM review_followup WHERE status='sent'").fetchone()['n']
        failed=db.execute("SELECT COUNT(*) n FROM review_followup WHERE status='failed' AND attempts>=?",(MAX_ATTEMPTS,)).fetchone()['n']
        latest=[dict(r) for r in db.execute('''SELECT appointment_id,status,attempts,last_attempt_at,sent_at,last_error
          FROM review_followup ORDER BY COALESCE(sent_at,last_attempt_at,first_seen_at) DESC LIMIT 20''')]
    return {
      'enabled':True,
      'mode':'all_honored_controls',
      'delayMinutes':DELAY_MINUTES,
      'lookbackHours':LOOKBACK_HOURS,
      'sessionConnected':bool(session.get('connected')),
      'sessionError':session.get('error',''),
      'nativeFavorableOnlyEmailEnabled':native.get('nativeFavorableOnlyEmailEnabled'),
      'sent24h':sent24,'sentTotal':sent_total,'permanentFailures':failed,'latest':latest,
      'privacy':'CyberCheck stores appointment id + delivery state only; customer email remains in Mercure'
    }

def _loop():
    while not _STOP.is_set():
        try: process_once()
        except Exception: pass
        if _STOP.wait(INTERVAL_SECONDS): break

def start():
    global _THREAD
    init_db()
    if _THREAD and _THREAD.is_alive(): return
    _THREAD=threading.Thread(target=_loop,daemon=True,name='CyberCheckReviewFollowup')
    _THREAD.start()

def stop():
    _STOP.set()

init_db()
