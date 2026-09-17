from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import datetime, hashlib, hmac, json, os, secrets, unicodedata, html
import analytics_store as analytics

ROOT = Path(__file__).resolve().parent
PRIVATE_DIR = Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
SECRET_FILE = PRIVATE_DIR / 'mercure-webhook-secret'
PROVIDER = 'mercure-rdv'
CONFIRMED = ('confirmed','completed')
ALLOWED_STATUS = ('confirmed','completed','cancelled','no_show')


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def init_db():
    with analytics.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS booking_intents(
          token TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          source TEXT NOT NULL,
          campaign TEXT NOT NULL DEFAULT '',
          device TEXT NOT NULL,
          path TEXT NOT NULL,
          service TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_booking_intents_time ON booking_intents(created_at);
        CREATE TABLE IF NOT EXISTS booking_conversions(
          provider TEXT NOT NULL,
          external_id TEXT NOT NULL,
          status TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          confirmed_at TEXT,
          appointment_at TEXT NOT NULL DEFAULT '',
          amount_cents INTEGER NOT NULL DEFAULT 0,
          service TEXT NOT NULL DEFAULT '',
          attribution_token TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'Non attribué',
          campaign TEXT NOT NULL DEFAULT '',
          device TEXT NOT NULL DEFAULT 'unknown',
          PRIMARY KEY(provider,external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_booking_conversion_confirmed ON booking_conversions(confirmed_at);
        CREATE INDEX IF NOT EXISTS idx_booking_conversion_source ON booking_conversions(source);
        ''')
    analytics.DB.chmod(0o600)
    ensure_secret()
def ensure_secret():
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_FILE.exists():
        tmp=SECRET_FILE.with_suffix('.tmp')
        tmp.write_text(secrets.token_urlsafe(48)+'\n')
        tmp.chmod(0o600); os.replace(tmp,SECRET_FILE)
    SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text().strip()


def secret_info(reveal=False):
    secret=ensure_secret(); digest=hashlib.sha256(secret.encode()).hexdigest()
    out={'configured':True,'fingerprint':digest[:12]}
    if reveal: out['secret']=secret
    return out


def rotate_secret():
    tmp=SECRET_FILE.with_suffix('.tmp')
    tmp.write_text(secrets.token_urlsafe(48)+'\n'); tmp.chmod(0o600); os.replace(tmp,SECRET_FILE)
    return secret_info(True)


def verify_signature(raw, header):
    header=(header or '').strip()
    if header.startswith('sha256='): header=header[7:]
    expected=hmac.new(ensure_secret().encode(),raw,hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(header.lower(),expected.lower())


def browser_token(ccid):
    ccid=analytics.clean(ccid,120)
    if not ccid: raise ValueError('ccid required')
    return hmac.new(ensure_secret().encode(),('browser:'+ccid).encode(),hashlib.sha256).hexdigest()


def verify_browser_token(ccid, token):
    try: expected=browser_token(ccid)
    except Exception: return False
    return bool(token) and hmac.compare_digest(str(token),expected)


def _device(v):
    v=analytics.clean(v or 'unknown',20).lower()
    return v if v in ('mobile','tablet','desktop','unknown') else 'unknown'



MERCURE_PRESTATIONS = {
    'controle technique': 'TOUT VEHICULE HORS CAMPING CAR|1763|80|40|1',
    'vehicule amenage': 'VISITE TECHNIQUE VASP (CAMPING CAR,SANITAIRE,FOOD TRUCK,...)|1771|90|40|1',
}

def _fold(v):
    v=unicodedata.normalize('NFKD',str(v or '')).encode('ascii','ignore').decode().lower().strip()
    return ' '.join(v.split())

def mercure_prestation(service):
    return MERCURE_PRESTATIONS.get(_fold(service))

def auto_submit_html(token, service, nonce=""):
    prestation=mercure_prestation(service)
    if not prestation: return None
    action='https://rdv.checkupauto.fr/prendre_rdv?ccid='+token+'&cct='+browser_token(token)
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Ouverture de la réservation…</title></head><body><form id="mercure" method="post" action="{html.escape(action,quote=True)}"><input type="hidden" name="id" value="240"><input type="hidden" name="prestation" value="{html.escape(prestation,quote=True)}"></form><script nonce="{html.escape(str(nonce),quote=True)}">document.getElementById('mercure').submit()</script><noscript><button form="mercure" type="submit">Continuer vers la réservation</button></noscript></body></html>'''.encode()

def create_intent(params, booking_url):
    token=secrets.token_urlsafe(20)
    created=now_iso()
    source=analytics.classify_source(params.get('referrer',''),params.get('utmSource',''))
    campaign=analytics.clean(params.get('utmCampaign'),100)
    device=_device(params.get('device'))
    path=analytics.clean(params.get('path') or '/',300)
    if not path.startswith('/'): path='/'
    service=analytics.clean(params.get('service'),100)
    with analytics.connect() as db:
        db.execute('INSERT INTO booking_intents(token,created_at,source,campaign,device,path,service) VALUES(?,?,?,?,?,?,?)',
                   (token,created,source,campaign,device,path,service))
        db.execute("INSERT INTO events(occurred_at,event,path,source,campaign,device,referrer_host,service) VALUES(?,?,?,?,?,?,?,?)",
                   (created,'booking_click',path,source,campaign,device,'',service))
    parts=urlsplit(booking_url)
    query=dict(parse_qsl(parts.query,keep_blank_values=True)); query['ccid']=token; query['cct']=browser_token(token)
    target=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))
    return {'token':token,'target':target,'source':source,'campaign':campaign}
def _money_cents(value):
    if value in (None,''): return 0
    if isinstance(value,bool): raise ValueError('amount invalid')
    try: amount=float(value)
    except Exception: raise ValueError('amount invalid')
    if amount<0 or amount>100000: raise ValueError('amount invalid')
    return int(round(amount*100))


def apply_conversion(payload):
    if not isinstance(payload,dict): raise ValueError('invalid payload')
    external_id=analytics.clean(payload.get('externalId') or payload.get('id'),120)
    if not external_id: raise ValueError('externalId required')
    status=analytics.clean(payload.get('status') or 'confirmed',30).lower()
    if status not in ALLOWED_STATUS: raise ValueError('unsupported status')
    token=analytics.clean(payload.get('attributionToken') or payload.get('ccid'),120)
    appointment=analytics.clean(payload.get('appointmentDate'),80)
    service=analytics.clean(payload.get('service'),120)
    amount_cents=_money_cents(payload.get('amount'))
    source='Non attribué'; campaign=''; device='unknown'
    with analytics.connect() as db:
        if token:
            intent=db.execute('SELECT * FROM booking_intents WHERE token=?',(token,)).fetchone()
            if intent:
                source=intent['source']; campaign=intent['campaign']; device=intent['device']
                if not service: service=intent['service']
        if source=='Non attribué' and payload.get('source'):
            source=analytics.clean(payload.get('source'),100)
        now=now_iso(); confirmed=now if status in CONFIRMED else None
        db.execute('''INSERT INTO booking_conversions(
          provider,external_id,status,first_seen_at,updated_at,confirmed_at,appointment_at,
          amount_cents,service,attribution_token,source,campaign,device)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(provider,external_id) DO UPDATE SET
          status=excluded.status,updated_at=excluded.updated_at,
          confirmed_at=CASE WHEN excluded.status IN ('confirmed','completed') THEN COALESCE(booking_conversions.confirmed_at,excluded.confirmed_at) ELSE booking_conversions.confirmed_at END,
          appointment_at=excluded.appointment_at,amount_cents=excluded.amount_cents,
          service=excluded.service,attribution_token=CASE WHEN excluded.attribution_token<>'' THEN excluded.attribution_token ELSE booking_conversions.attribution_token END,
          source=CASE WHEN excluded.source<>'Non attribué' THEN excluded.source ELSE booking_conversions.source END,
          campaign=CASE WHEN excluded.campaign<>'' THEN excluded.campaign ELSE booking_conversions.campaign END,
          device=CASE WHEN excluded.device<>'unknown' THEN excluded.device ELSE booking_conversions.device END''',
          (PROVIDER,external_id,status,now,now,confirmed,appointment,amount_cents,service,token,source,campaign,device))
    return {'ok':True,'externalId':external_id,'status':status,'attributed':source!='Non attribué','source':source}
def browser_confirmation(payload):
    if not isinstance(payload,dict): raise ValueError('invalid payload')
    ccid=analytics.clean(payload.get('ccid'),120)
    cct=analytics.clean(payload.get('cct'),128)
    route=analytics.clean(payload.get('route'),500)
    if not verify_browser_token(ccid,cct): raise PermissionError('invalid browser token')
    with analytics.connect() as db:
        intent=db.execute('SELECT * FROM booking_intents WHERE token=?',(ccid,)).fetchone()
    if not intent: raise ValueError('unknown attribution token')
    created=datetime.datetime.fromisoformat(intent['created_at'].replace('Z','+00:00'))
    if datetime.datetime.now(datetime.timezone.utc)-created>datetime.timedelta(hours=48):
        raise ValueError('attribution token expired')
    # The provider callback only fires after a successful appointment creation.
    # Use a deterministic id so retries/beacons remain idempotent.
    external='browser-'+hashlib.sha256((ccid+'|'+route).encode()).hexdigest()[:24]
    service=intent['service']
    amount=0.0
    presta=mercure_prestation(service)
    if presta:
        try: amount=float(presta.split('|')[2])
        except Exception: amount=0.0
    result=apply_conversion({'externalId':external,'status':'confirmed','ccid':ccid,'service':service,'amount':amount})
    result['transport']='browser-success-callback'; result['routeObserved']=bool(route)
    return result


def stats(days=30):
    days=max(1,min(int(days),365))
    now=datetime.datetime.now(datetime.timezone.utc)
    start=(now-datetime.timedelta(days=days)).isoformat(timespec='seconds')
    prev_start=(now-datetime.timedelta(days=days*2)).isoformat(timespec='seconds')
    with analytics.connect() as db:
        clicks=db.execute('SELECT COUNT(*) n FROM booking_intents WHERE created_at>=?',(start,)).fetchone()['n']
        confirmed=db.execute("SELECT COUNT(*) n FROM booking_conversions WHERE confirmed_at>=? AND status IN ('confirmed','completed')",(start,)).fetchone()['n']
        revenue=db.execute("SELECT COALESCE(SUM(amount_cents),0) s FROM booking_conversions WHERE confirmed_at>=? AND status IN ('confirmed','completed')",(start,)).fetchone()['s']
        attributed=db.execute("SELECT COUNT(*) n FROM booking_conversions WHERE confirmed_at>=? AND status IN ('confirmed','completed') AND source<>'Non attribué'",(start,)).fetchone()['n']
        previous_clicks=db.execute('SELECT COUNT(*) n FROM booking_intents WHERE created_at>=? AND created_at<?',(prev_start,start)).fetchone()['n']
        previous_confirmed=db.execute("SELECT COUNT(*) n FROM booking_conversions WHERE confirmed_at>=? AND confirmed_at<? AND status IN ('confirmed','completed')",(prev_start,start)).fetchone()['n']
        previous_revenue=db.execute("SELECT COALESCE(SUM(amount_cents),0) s FROM booking_conversions WHERE confirmed_at>=? AND confirmed_at<? AND status IN ('confirmed','completed')",(prev_start,start)).fetchone()['s']
        by_source=[dict(r) for r in db.execute('''SELECT source,COUNT(*) confirmed,COALESCE(SUM(amount_cents),0) revenueCents
          FROM booking_conversions WHERE confirmed_at>=? AND status IN ('confirmed','completed')
          GROUP BY source ORDER BY confirmed DESC,revenueCents DESC''',(start,))]
        pending=db.execute("SELECT COUNT(*) n FROM booking_intents i WHERE i.created_at>=? AND NOT EXISTS(SELECT 1 FROM booking_conversions c WHERE c.attribution_token=i.token AND c.status IN ('confirmed','completed'))",(start,)).fetchone()['n']
        recent=[dict(r) for r in db.execute('''SELECT external_id externalId,status,updated_at updatedAt,appointment_at appointmentAt,
          amount_cents amountCents,service,source,campaign
          FROM booking_conversions ORDER BY updated_at DESC LIMIT 30''')]
        daily=[dict(r) for r in db.execute("SELECT substr(confirmed_at,1,10) day,COUNT(*) confirmed,COALESCE(SUM(amount_cents),0) revenueCents FROM booking_conversions WHERE confirmed_at>=? AND status IN ('confirmed','completed') GROUP BY day ORDER BY day",(start,))]
    return {
      'days':days,'bookingIntents':clicks,'confirmedBookings':confirmed,
      'confirmationRate':round((confirmed/clicks*100) if clicks else 0,2),
      'revenueCents':revenue,'attributedBookings':attributed,
      'attributionRate':round((attributed/confirmed*100) if confirmed else 0,2),
      'pendingIntents':pending,'bySource':by_source,'recent':recent,'daily':daily,
      'previous':{'bookingIntents':previous_clicks,'confirmedBookings':previous_confirmed,'confirmationRate':round((previous_confirmed/previous_clicks*100) if previous_clicks else 0,2),'revenueCents':previous_revenue}
    }


def merge_into_analytics(summary):
    days=summary.get('days',30); s=stats(days)
    conv={r['source']:r for r in s['bySource']}
    existing={r['source']:r for r in summary.get('sourceFunnels',[])}
    for source,row in conv.items():
        target=existing.setdefault(source,{'source':source,'views':0,'bookings':0,'phoneClicks':0,'directionsClicks':0,'bookingRate':0})
        target['confirmedBookings']=row['confirmed']; target['revenueCents']=row['revenueCents']
    for row in existing.values():
        row.setdefault('confirmedBookings',0); row.setdefault('revenueCents',0)
        row['confirmationRate']=round((row['confirmedBookings']/row['bookings']*100) if row['bookings'] else 0,2)
    summary['sourceFunnels']=sorted(existing.values(),key=lambda r:(r['views'],r['bookings'],r['confirmedBookings']),reverse=True)
    daily_conv={r['day']:r for r in s.get('daily',[])}
    for row in summary.get('daily',[]):
        c=daily_conv.get(row['day'],{}); row['confirmedBookings']=c.get('confirmed',0); row['revenueCents']=c.get('revenueCents',0)
    summary.update({k:s[k] for k in ('confirmedBookings','confirmationRate','revenueCents','attributedBookings','attributionRate','pendingIntents')})
    prev=s.get('previous',{}); delta=summary.setdefault('delta',{})
    delta['confirmedBookingsPct']=analytics._pct_delta(s['confirmedBookings'],prev.get('confirmedBookings',0))
    delta['confirmationRatePoints']=round(s['confirmationRate']-prev.get('confirmationRate',0),2)
    delta['revenuePct']=analytics._pct_delta(s['revenueCents'],prev.get('revenueCents',0))
    summary['bookingIntegration']=s
    return summary
