from pathlib import Path
import datetime, hashlib, os, secrets

import analytics_store as analytics
import mercure_admin_client as mercure_admin
import mercure_public_client as mercure_public

TTL_MINUTES=60


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def init_db():
    with analytics.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS booking_test_sessions(
          token_hash TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          appointment_id TEXT NOT NULL DEFAULT '',
          service_key TEXT NOT NULL DEFAULT '',
          appointment_at TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'ready'
        )''')


def _hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def create_session():
    init_db(); token=secrets.token_urlsafe(32); now=_now(); exp=now+datetime.timedelta(minutes=TTL_MINUTES)
    with analytics.connect() as db:
        db.execute('INSERT INTO booking_test_sessions(token_hash,created_at,expires_at) VALUES(?,?,?)',
                   (_hash(token),now.isoformat(timespec='seconds'),exp.isoformat(timespec='seconds')))
    return {'token':token,'expiresAt':exp.isoformat(timespec='seconds')}
def _session(token, require_ready=False):
    init_db(); h=_hash(token)
    with analytics.connect() as db:
        row=db.execute('SELECT * FROM booking_test_sessions WHERE token_hash=?',(h,)).fetchone()
    if not row: raise PermissionError('Session de test inconnue')
    exp=datetime.datetime.fromisoformat(row['expires_at'].replace('Z','+00:00'))
    if _now()>exp: raise PermissionError('Session de test expirée')
    if require_ready and row['status']!='ready': raise ValueError('Un rendez-vous test existe déjà dans cette session')
    return dict(row)


def status(token):
    row=_session(token)
    return {
      'ok':True,'mode':'booking-test','expiresAt':row['expires_at'],'status':row['status'],
      'appointmentId':row['appointment_id'],'service':row['service_key'],'appointmentAt':row['appointment_at'],
      'safety':'Synthetic appointment; no email or SMS notifications.'
    }


def create_appointment(token, service_key, date_value, time_value):
    row=_session(token,True)
    meta=mercure_public.service(service_key)
    availability=mercure_public.availability(service_key,date_value)
    valid=False; price=float(meta['basePrice'])
    for day in availability.get('days',[]):
        if day.get('date')!=date_value: continue
        for slot in day.get('slots',[]):
            if str(slot.get('time'))==str(time_value):
                valid=True; price=float(slot.get('price') or price); break
    if not valid: raise ValueError('Ce créneau n’est plus disponible dans Mercure')
    created=mercure_admin.create_synthetic_test_appointment(service_key,date_value,time_value)
    appointment_id=str(created['appointmentId'])
    appointment_at=f'{date_value}T{time_value}'
    with analytics.connect() as db:
        db.execute('''UPDATE booking_test_sessions SET appointment_id=?,service_key=?,appointment_at=?,status='created'
                      WHERE token_hash=?''',(appointment_id,service_key,appointment_at,_hash(token)))
    return {'ok':True,'appointmentId':appointment_id,'service':service_key,'appointmentAt':appointment_at,
            'price':price,'providerVerified':bool(created.get('verified')),'notifications':{'email':False,'sms':False}}
def remove_appointment(token):
    row=_session(token)
    if row['status']!='created' or not row['appointment_id']:
        raise ValueError('Aucun rendez-vous test actif')
    result=mercure_admin.remove_synthetic_test_appointment(row['appointment_id'],row['appointment_at'])
    with analytics.connect() as db:
        db.execute("UPDATE booking_test_sessions SET status='removed' WHERE token_hash=?",(_hash(token),))
    return {'ok':True,'appointmentId':row['appointment_id'],'removed':True,'providerVerified':bool(result.get('verified'))}


def purge_expired():
    init_db(); now=_now().isoformat(timespec='seconds')
    with analytics.connect() as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM booking_test_sessions WHERE expires_at<? AND status='created'",(now,))]
    cleaned=0
    for row in rows:
        try:
            mercure_admin.remove_synthetic_test_appointment(row['appointment_id'],row['appointment_at'])
            with analytics.connect() as db:
                db.execute("UPDATE booking_test_sessions SET status='expired-removed' WHERE token_hash=?",(row['token_hash'],))
            cleaned+=1
        except Exception:
            pass
    return {'expiredAppointmentsRemoved':cleaned}


import threading
_STOP=threading.Event()
_THREAD=None

def _cleanup_loop(interval):
    while not _STOP.wait(max(60,int(interval))):
        try: purge_expired()
        except Exception: pass

def start(interval=300):
    global _THREAD
    if _THREAD and _THREAD.is_alive(): return
    _THREAD=threading.Thread(target=_cleanup_loop,args=(interval,),daemon=True,name='CyberCheckBookingTestCleanup')
    _THREAD.start()

def stop():
    _STOP.set()
