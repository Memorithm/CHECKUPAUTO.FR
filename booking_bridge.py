from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import datetime, hashlib, hmac, json, os, re, secrets, unicodedata, html
from zoneinfo import ZoneInfo
import analytics_store as analytics
import referral_engine as referrals
import compliance_store as compliance

ROOT = Path(__file__).resolve().parent
PRIVATE_DIR = Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
SECRET_FILE = PRIVATE_DIR / 'mercure-webhook-secret'
PROVIDER = 'mercure-rdv'
CONFIRMED = ('confirmed','completed')
ALLOWED_STATUS = ('confirmed','completed','cancelled','no_show')
BOOKING_BROWSER_TOKEN_TTL_HOURS = 48
_BOOKING_ATTRIBUTION_STORAGE_KEY = 'booking_conversion_attribution_storage'
_BOOKING_ATTRIBUTION_STORAGE_VERSION = 'sha256-v1'
_BOOKING_ATTRIBUTION_KEY_RE = re.compile(r'^sha256-v1:[0-9a-f]{64}$')
_BROWSER_SYNTHETIC_PREFIX = 'browser-'


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _attribution_key(value):
    raw=analytics.clean(value,120)
    if not raw: return ''
    material=b'checkupauto:booking-conversion-attribution:v1\x00'+raw.encode('utf-8')
    return _BOOKING_ATTRIBUTION_STORAGE_VERSION+':'+hashlib.sha256(material).hexdigest()


def _migrate_attribution_keys_locked(db):
    db.execute('''CREATE TABLE IF NOT EXISTS booking_schema_meta(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )''')
    marker=db.execute(
        'SELECT value FROM booking_schema_meta WHERE key=?',
        (_BOOKING_ATTRIBUTION_STORAGE_KEY,),
    ).fetchone()
    if marker and str(marker['value']) != _BOOKING_ATTRIBUTION_STORAGE_VERSION:
        raise RuntimeError('Version de stockage attribution réservation inconnue')

    # Raw browser tokens are kept only during the short checkout lifetime. Once
    # retired, token itself is replaced by the already-derived attribution key.
    # Never hash that derived key a second time during subsequent migrations.
    for row in db.execute('SELECT token,attribution_key FROM booking_intents').fetchall():
        stored_token=str(row['token'] or '')
        stored_key=str(row['attribution_key'] or '')
        if _BOOKING_ATTRIBUTION_KEY_RE.fullmatch(stored_token):
            if stored_key != stored_token:
                db.execute(
                    'UPDATE booking_intents SET attribution_key=? WHERE token=?',
                    (stored_token,stored_token),
                )
            continue
        expected=_attribution_key(stored_token)
        if stored_key != expected:
            db.execute(
                'UPDATE booking_intents SET attribution_key=? WHERE token=?',
                (expected,stored_token),
            )

    # Repair historical raw conversion tokens, and raw rows produced by an older
    # process during a rolling deployment. Versioned keys are left untouched.
    rows=db.execute('''SELECT provider,external_id,attribution_token
      FROM booking_conversions WHERE attribution_token<>'' ''').fetchall()
    for row in rows:
        stored=str(row['attribution_token'])
        if _BOOKING_ATTRIBUTION_KEY_RE.fullmatch(stored):
            continue
        db.execute(
            '''UPDATE booking_conversions SET attribution_token=?
               WHERE provider=? AND external_id=?''',
            (_attribution_key(stored),row['provider'],row['external_id']),
        )

    if marker is None:
        db.execute(
            'INSERT INTO booking_schema_meta(key,value) VALUES(?,?)',
            (_BOOKING_ATTRIBUTION_STORAGE_KEY,_BOOKING_ATTRIBUTION_STORAGE_VERSION),
        )

    invalid=db.execute('''SELECT attribution_token FROM booking_conversions
      WHERE attribution_token<>'' ''').fetchall()
    if any(not _BOOKING_ATTRIBUTION_KEY_RE.fullmatch(str(row['attribution_token'])) for row in invalid):
        raise RuntimeError('Migration attribution réservation incomplète')


def init_db():
    with analytics.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS booking_intents(
          token TEXT PRIMARY KEY,
          attribution_key TEXT NOT NULL DEFAULT '',
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
        db.execute('BEGIN IMMEDIATE')
        intent_cols={row['name'] for row in db.execute('PRAGMA table_info(booking_intents)')}
        if 'attribution_key' not in intent_cols:
            db.execute("ALTER TABLE booking_intents ADD COLUMN attribution_key TEXT NOT NULL DEFAULT ''")
        if 'referral_code' not in intent_cols:
            db.execute("ALTER TABLE booking_intents ADD COLUMN referral_code TEXT NOT NULL DEFAULT ''")
        if 'preferred_date' not in intent_cols:
            db.execute("ALTER TABLE booking_intents ADD COLUMN preferred_date TEXT NOT NULL DEFAULT ''")
        if 'preferred_time' not in intent_cols:
            db.execute("ALTER TABLE booking_intents ADD COLUMN preferred_time TEXT NOT NULL DEFAULT ''")
        conversion_cols={row['name'] for row in db.execute('PRAGMA table_info(booking_conversions)')}
        if 'referral_code' not in conversion_cols:
            db.execute("ALTER TABLE booking_conversions ADD COLUMN referral_code TEXT NOT NULL DEFAULT ''")
        _migrate_attribution_keys_locked(db)
        db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_intents_attribution_key
          ON booking_intents(attribution_key) WHERE attribution_key<>'' ''')
    analytics.DB.chmod(0o600)
    referrals.init_db()
    ensure_secret()


def retire_expired_browser_tokens(*, now=None, dry_run=False):
    current=now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    cutoff=(current-datetime.timedelta(hours=BOOKING_BROWSER_TOKEN_TTL_HOURS)).isoformat(timespec='seconds')
    with analytics.connect() as db:
        rows=db.execute('''SELECT token,attribution_key FROM booking_intents
          WHERE created_at<? AND token<>attribution_key''',(cutoff,)).fetchall()
        if dry_run:
            return len(rows)
        db.execute('BEGIN IMMEDIATE')
        retired=0
        for row in rows:
            raw=str(row['token'] or '')
            key=str(row['attribution_key'] or '') or _attribution_key(raw)
            if not raw or not _BOOKING_ATTRIBUTION_KEY_RE.fullmatch(key):
                raise RuntimeError('clé attribution réservation invalide')
            updated=db.execute(
                'UPDATE booking_intents SET token=?,attribution_key=? WHERE token=? AND created_at<?',
                (key,key,raw,cutoff),
            ).rowcount
            retired+=int(updated or 0)
    return retired


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


def _checkout_requirements(token):
    with analytics.connect() as db:
        intent=db.execute(
            'SELECT preferred_date,preferred_time FROM booking_intents WHERE token=?',
            (token,),
        ).fetchone()
    preferred_date=str(intent['preferred_date'] or '') if intent else ''
    preferred_time=str(intent['preferred_time'] or '') if intent else ''
    requires_immediate=True
    if preferred_date:
        try:
            chosen=datetime.date.fromisoformat(preferred_date)
            today=datetime.datetime.now(ZoneInfo('Europe/Paris')).date()
            requires_immediate=chosen <= today+datetime.timedelta(days=14)
        except ValueError:
            requires_immediate=True
    return {
        'preferredDate':preferred_date,
        'preferredTime':preferred_time,
        'requiresImmediatePerformance':requires_immediate,
    }


class BookingTermsUnavailable(RuntimeError):
    """Checkout must remain closed until approved terms are published."""


def require_published_terms():
    terms = compliance.published_document("terms")
    if not terms:
        raise BookingTermsUnavailable("CGV non publiées")
    return terms


def auto_submit_html(token, service, nonce=""):
    prestation=mercure_prestation(service)
    if not prestation: return None
    terms=require_published_terms()
    cct=browser_token(token)
    action='https://rdv.checkupauto.fr/prendre_rdv?ccid='+token+'&cct='+cct
    parts=prestation.split('|')
    price=parts[2] if len(parts)>2 else ''
    requirements=_checkout_requirements(token)
    preferred=' · '.join(
        x for x in (requirements['preferredDate'],requirements['preferredTime']) if x
    )
    immediate_required=bool(requirements['requiresImmediatePerformance'])
    immediate_markup=(
        '<label><input id="immediate" type="checkbox"> '
        'Je demande expressément que la prestation puisse commencer avant la fin du délai '
        'de rétractation et je reconnais qu’après exécution complète de la prestation, '
        'je perdrai mon droit de rétractation.</label>'
        if immediate_required else
        '<input id="immediate" type="hidden" value="">'
    )
    preferred_markup=(
        '<br>Créneau souhaité : '+html.escape(preferred)
        if preferred else ''
    )
    token_js=json.dumps(token)
    cct_js=json.dumps(cct)
    version_js=json.dumps(terms["version"])
    hash_js=json.dumps(terms["contentHash"])
    immediate_required_js='true' if immediate_required else 'false'
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Vérification de votre réservation</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#f5f6f1;color:#111;padding:24px}}main{{max-width:680px;margin:24px auto;background:#fff;border:1px solid #dedfd8;border-radius:24px;padding:28px}}.summary{{padding:18px;border-radius:16px;background:#f3f4ef;margin:18px 0}}label{{display:block;margin:18px 0;line-height:1.45}}button{{border:0;border-radius:999px;padding:14px 20px;background:#111;color:#fff;font-weight:700}}button:disabled{{opacity:.45}}a{{color:#111}}#error{{color:#9a1b1b;min-height:1.5em}}</style></head><body><main><h1>Vérifiez avant de continuer</h1><p>Vous allez être redirigé vers Mercure pour finaliser votre rendez-vous.</p><div class="summary"><strong>{html.escape(str(service))}</strong><br>Prix affiché : {html.escape(str(price))} € TTC{preferred_markup}</div><p><a href="/">Modifier mon choix</a></p><form id="mercure" method="post" action="{html.escape(action,quote=True)}"><input type="hidden" name="id" value="240"><input type="hidden" name="prestation" value="{html.escape(prestation,quote=True)}"><label><input id="terms" type="checkbox"> J’ai lu et j’accepte les <a href="/cgv">conditions générales de vente</a> applicables à cette réservation.</label>{immediate_markup}<button id="continue" type="submit" disabled>Accepter et continuer vers la réservation</button><p id="error" role="alert"></p></form><script nonce="{html.escape(str(nonce),quote=True)}">const form=document.getElementById('mercure'),terms=document.getElementById('terms'),immediate=document.getElementById('immediate'),button=document.getElementById('continue'),error=document.getElementById('error'),requiresImmediate={immediate_required_js};const update=()=>{{button.disabled=!terms.checked||(requiresImmediate&&!immediate.checked)}};terms.addEventListener('change',update);if(requiresImmediate)immediate.addEventListener('change',update);form.addEventListener('submit',async(e)=>{{e.preventDefault();if(!terms.checked||(requiresImmediate&&!immediate.checked))return;button.disabled=true;error.textContent='';try{{const r=await fetch('/api/booking/accept-terms',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ccid:{token_js},cct:{cct_js},termsVersion:{version_js},termsContentHash:{hash_js},accepted:true,reviewed:true,immediatePerformance:requiresImmediate?immediate.checked:false}})}});if(!r.ok)throw new Error('acceptance_failed');form.submit()}}catch(_e){{error.textContent='Impossible d’enregistrer votre acceptation. Réessayez.';button.disabled=false}}}});</script><noscript>JavaScript est nécessaire afin d’enregistrer la preuve d’acceptation des CGV avant la réservation.</noscript></main></body></html>'''.encode()


def create_intent(params, booking_url):
    token=secrets.token_urlsafe(20)
    attribution_key=_attribution_key(token)
    created=now_iso()
    source=analytics.classify_source(params.get('referrer',''),params.get('utmSource',''))
    campaign=analytics._safe_dimension(params.get('utmCampaign'),100)
    device=_device(params.get('device'))
    path=analytics._safe_path(params.get('path') or '/')
    service=analytics._safe_dimension(params.get('service'),100)
    referral_code=referrals.valid_code_or_empty(params.get('referralCode'))
    preferred_date=analytics.clean(params.get('preferredDate'),10)
    preferred_time=analytics.clean(params.get('preferredTime'),8)
    if preferred_date:
        datetime.date.fromisoformat(preferred_date)
    if preferred_time and not re.fullmatch(r'\d{2}:\d{2}',preferred_time):
        raise ValueError('preferredTime invalid')
    with analytics.connect() as db:
        db.execute('INSERT INTO booking_intents(token,attribution_key,created_at,source,campaign,device,path,service,referral_code,preferred_date,preferred_time) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (token,attribution_key,created,source,campaign,device,path,service,referral_code,preferred_date,preferred_time))
        db.execute("INSERT INTO events(occurred_at,event,path,source,campaign,device,referrer_host,service) VALUES(?,?,?,?,?,?,?,?)",
                   (created,'booking_click',path,source,campaign,device,'',service))
    parts=urlsplit(booking_url)
    query=dict(parse_qsl(parts.query,keep_blank_values=True)); query['ccid']=token; query['cct']=browser_token(token)
    target=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))
    return {'token':token,'target':target,'source':source,'campaign':campaign,'referralCode':referral_code or None}


def record_terms_acceptance(payload):
    if not isinstance(payload,dict): raise ValueError('invalid payload')
    ccid=analytics.clean(payload.get('ccid'),120)
    cct=analytics.clean(payload.get('cct'),128)
    if not verify_browser_token(ccid,cct): raise PermissionError('invalid browser token')
    with analytics.connect() as db:
        intent=db.execute('SELECT * FROM booking_intents WHERE token=?',(ccid,)).fetchone()
    if not intent: raise ValueError('unknown attribution token')
    created=datetime.datetime.fromisoformat(intent['created_at'].replace('Z','+00:00'))
    if datetime.datetime.now(datetime.timezone.utc)-created>datetime.timedelta(hours=BOOKING_BROWSER_TOKEN_TTL_HOURS):
        raise ValueError('attribution token expired')
    requirements=_checkout_requirements(ccid)
    immediate=payload.get('immediatePerformance') is True
    if requirements['requiresImmediatePerformance'] and not immediate:
        raise ValueError('early performance acknowledgement required')
    return compliance.record_checkout_acceptance(
        ccid,
        terms_version=payload.get('termsVersion'),
        terms_content_hash=payload.get('termsContentHash'),
        accepted=payload.get('accepted') is True,
        reviewed=payload.get('reviewed') is True,
        immediate_performance=immediate,
        source='checkout_review',
    )


def _money_cents(value):
    if value in (None,''): return 0
    if isinstance(value,bool): raise ValueError('amount invalid')
    try: amount=float(value)
    except Exception: raise ValueError('amount invalid')
    if amount<0 or amount>100000: raise ValueError('amount invalid')
    return int(round(amount*100))


_MERCURE_APPOINTMENT_FORMATS = (
    (re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$'), '%Y-%m-%dT%H:%M'),
    (re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'), '%Y-%m-%d %H:%M:%S'),
)


def _appointment_at(value):
    raw=analytics.clean(value,80)
    if not raw: return ''
    for pattern,fmt in _MERCURE_APPOINTMENT_FORMATS:
        if not pattern.fullmatch(raw): continue
        try:
            datetime.datetime.strptime(raw,fmt)
        except ValueError as exc:
            raise ValueError('appointmentDate invalid') from exc
        return raw
    raise ValueError('appointmentDate invalid')


def authoritative_external_id_for_browser_token(ccid, cct):
    ccid=analytics.clean(ccid,120)
    cct=analytics.clean(cct,128)
    if not ccid or not verify_browser_token(ccid,cct):
        raise PermissionError('invalid browser token')
    with analytics.connect() as db:
        intent=db.execute(
            'SELECT created_at,attribution_key FROM booking_intents WHERE token=? LIMIT 1',
            (ccid,),
        ).fetchone()
        if not intent:
            raise ValueError('unknown attribution token')
        created=datetime.datetime.fromisoformat(str(intent['created_at']).replace('Z','+00:00'))
        if datetime.datetime.now(datetime.timezone.utc)-created>datetime.timedelta(hours=BOOKING_BROWSER_TOKEN_TTL_HOURS):
            raise ValueError('attribution token expired')
        token_key=str(intent['attribution_key'] or '') or _attribution_key(ccid)
        row=_authoritative_conversion_for_token(db,token_key)
    if not row or str(row['status']) not in CONFIRMED:
        raise ValueError('confirmed booking required')
    external_id=analytics.clean(row['external_id'],120)
    if not external_id or external_id.startswith(_BROWSER_SYNTHETIC_PREFIX):
        raise ValueError('authoritative booking reference required')
    return external_id


def authoritative_payment_basis(external_id):
    external_id=analytics.clean(external_id,120)
    if not external_id or external_id.startswith(_BROWSER_SYNTHETIC_PREFIX):
        raise ValueError('authoritative booking reference required')
    with analytics.connect() as db:
        row=db.execute(
            '''SELECT provider,external_id,status,amount_cents,service,appointment_at
               FROM booking_conversions
               WHERE provider=? AND external_id=? LIMIT 1''',
            (PROVIDER,external_id),
        ).fetchone()
    if not row or str(row['status']) not in CONFIRMED:
        raise ValueError('confirmed booking required')

    folded=_fold(row['service'])
    service_map={
        'controle technique':('technical',8000),
        'tout vehicule hors camping car':('technical',8000),
        'vehicule amenage':('fitted',9000),
        'visite technique vasp (camping car,sanitaire,food truck,...)':('fitted',9000),
    }
    resolved=service_map.get(folded)
    if not resolved:
        raise ValueError('payable service required')
    service_key,maximum=resolved
    amount=int(row['amount_cents'] or 0)
    if amount<1 or amount>maximum:
        raise ValueError('authoritative payment amount invalid')
    booking_reference='mercure:'+hashlib.sha256(
        ('mercure-rdv\x00'+str(row['external_id'])).encode('utf-8')
    ).hexdigest()[:40]
    return {
        'bookingReference':booking_reference,
        'provider':PROVIDER,
        'status':str(row['status']),
        'service':service_key,
        'amountCents':amount,
        'appointmentAt':str(row['appointment_at'] or ''),
    }


def _authoritative_conversion_for_token(db, token_key):
    if not token_key:
        return None
    return db.execute(
        '''SELECT * FROM booking_conversions
           WHERE provider=? AND attribution_token=? AND external_id NOT LIKE ?
           ORDER BY updated_at DESC,external_id DESC LIMIT 1''',
        (PROVIDER,token_key,_BROWSER_SYNTHETIC_PREFIX+'%'),
    ).fetchone()


def apply_conversion(payload, *, acceptance_source="mercure_contract_confirmation"):
    if not isinstance(payload,dict): raise ValueError('invalid payload')
    external_id=analytics.clean(payload.get('externalId') or payload.get('id'),120)
    if not external_id: raise ValueError('externalId required')
    status=analytics.clean(payload.get('status') or 'confirmed',30).lower()
    if status not in ALLOWED_STATUS: raise ValueError('unsupported status')
    appointment=_appointment_at(payload.get('appointmentDate'))
    token=analytics.clean(payload.get('attributionToken') or payload.get('ccid'),120)
    token_key=_attribution_key(token)
    acceptance=None
    if token and status in CONFIRMED:
        try:
            acceptance=compliance.finalize_checkout_acceptance(
                token,external_id,source=acceptance_source
            )
        except PermissionError:
            acceptance=None
    service=analytics._safe_dimension(payload.get('service'),120)
    amount_cents=_money_cents(payload.get('amount'))
    source='Non attribué'; campaign=''; device='unknown'; referral_code=''
    synthetic_reconciled=0
    authoritative_reused=False
    with analytics.connect() as db:
        if token:
            intent=db.execute(
                'SELECT * FROM booking_intents WHERE token=? OR attribution_key=? LIMIT 1',
                (token,token_key),
            ).fetchone()
            if intent:
                source=intent['source']; campaign=intent['campaign']; device=intent['device']
                referral_code=referrals.valid_code_or_empty(intent['referral_code'] if 'referral_code' in intent.keys() else '')
                if not service: service=intent['service']
        if not referral_code and payload.get('referralCode'):
            referral_code=referrals.valid_code_or_empty(payload.get('referralCode'))
        if source=='Non attribué' and payload.get('source'):
            source=analytics._safe_dimension(payload.get('source'),100)

        if external_id.startswith(_BROWSER_SYNTHETIC_PREFIX) and token_key:
            authoritative=_authoritative_conversion_for_token(db,token_key)
            if authoritative:
                external_id=str(authoritative['external_id'])
                status=str(authoritative['status'])
                source=str(authoritative['source'])
                referral_code=str(authoritative['referral_code'] or referral_code)
                authoritative_reused=True

        if not authoritative_reused:
            now=now_iso(); confirmed=now if status in CONFIRMED else None
            db.execute('''INSERT INTO booking_conversions(
              provider,external_id,status,first_seen_at,updated_at,confirmed_at,appointment_at,
              amount_cents,service,attribution_token,source,campaign,device,referral_code)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(provider,external_id) DO UPDATE SET
              status=excluded.status,updated_at=excluded.updated_at,
              confirmed_at=CASE WHEN excluded.status IN ('confirmed','completed') THEN COALESCE(booking_conversions.confirmed_at,excluded.confirmed_at) ELSE booking_conversions.confirmed_at END,
              appointment_at=excluded.appointment_at,amount_cents=excluded.amount_cents,
              service=excluded.service,attribution_token=CASE WHEN excluded.attribution_token<>'' THEN excluded.attribution_token ELSE booking_conversions.attribution_token END,
              source=CASE WHEN excluded.source<>'Non attribué' THEN excluded.source ELSE booking_conversions.source END,
              campaign=CASE WHEN excluded.campaign<>'' THEN excluded.campaign ELSE booking_conversions.campaign END,
              device=CASE WHEN excluded.device<>'unknown' THEN excluded.device ELSE booking_conversions.device END,
              referral_code=CASE WHEN excluded.referral_code<>'' THEN excluded.referral_code ELSE booking_conversions.referral_code END''',
              (PROVIDER,external_id,status,now,now,confirmed,appointment,amount_cents,service,token_key,source,campaign,device,referral_code))
            if token_key and not external_id.startswith(_BROWSER_SYNTHETIC_PREFIX):
                synthetic_reconciled=int(db.execute(
                    '''DELETE FROM booking_conversions
                       WHERE provider=? AND attribution_token=? AND external_id LIKE ?''',
                    (PROVIDER,token_key,_BROWSER_SYNTHETIC_PREFIX+'%'),
                ).rowcount or 0)

    reward=referrals.record_pending(referral_code,PROVIDER,external_id,token) if referral_code else referrals.reward_status(PROVIDER,external_id)
    if status=='completed': reward=referrals.complete_control(PROVIDER,external_id) or reward
    elif status in ('cancelled','no_show'): reward=referrals.cancel_pending(PROVIDER,external_id) or reward
    return {'ok':True,'externalId':external_id,'status':status,'attributed':source!='Non attribué','source':source,
            'contractAcceptanceBound':bool(acceptance),
            'syntheticConversionsReconciled':synthetic_reconciled,
            'authoritativeConversionReused':authoritative_reused,
            'referralCode':referral_code or (reward.get('referral_code') if reward else None),
            'referralStatus':reward.get('status') if reward else None}


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
    if datetime.datetime.now(datetime.timezone.utc)-created>datetime.timedelta(hours=BOOKING_BROWSER_TOKEN_TTL_HOURS):
        raise ValueError('attribution token expired')
    # The provider callback only fires after a successful appointment creation.
    # Use a deterministic id so retries/beacons remain idempotent until the
    # authoritative provider conversion can be reconciled through attribution.
    external=_BROWSER_SYNTHETIC_PREFIX+hashlib.sha256((ccid+'|'+route).encode()).hexdigest()[:24]
    service=intent['service']
    amount=0.0
    presta=mercure_prestation(service)
    if presta:
        try: amount=float(presta.split('|')[2])
        except Exception: amount=0.0
    acceptance=compliance.finalize_checkout_acceptance(ccid,external)
    result=apply_conversion({'externalId':external,'status':'confirmed','ccid':ccid,'service':service,'amount':amount})
    result['contractAcceptanceBound']=bool(acceptance)
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
        pending=db.execute("SELECT COUNT(*) n FROM booking_intents i WHERE i.created_at>=? AND NOT EXISTS(SELECT 1 FROM booking_conversions c WHERE c.attribution_token=i.attribution_key AND c.status IN ('confirmed','completed'))",(start,)).fetchone()['n']
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