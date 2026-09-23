from pathlib import Path
from urllib.parse import unquote, urlparse
import datetime, re, sqlite3, os

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('CYBERCHECK_DATA_DIR','/root/CyberCheckData'))
DB = DATA_DIR / 'analytics.sqlite3'
ALLOWED_EVENTS = {
    'page_view','hero_cta_click','booking_click','phone_click','directions_click',
    'service_selected','offer_viewed','app_landing_view','app_store_click','app_testflight_click'
}

_SOURCE_NEEDLES = (
    ('chatgpt', 'ChatGPT', 'chatgpt.com'),
    ('perplexity', 'Perplexity', 'perplexity.ai'),
    ('gemini', 'Gemini', 'gemini.google.com'),
    ('claude', 'Claude', 'claude.ai'),
    ('google', 'Google', 'google'),
    ('bing', 'Bing', 'bing.com'),
    ('facebook', 'Facebook', 'facebook.com'),
    ('instagram', 'Instagram', 'instagram.com'),
    ('linkedin', 'LinkedIn', 'linkedin.com'),
    ('tiktok', 'TikTok', 'tiktok.com'),
)
_EMAIL_RE = re.compile(r'[^\s/@]+@[^\s/@]+\.[^\s/@]+', re.I)
_UUID_RE = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b', re.I)
_PHONE_RE = re.compile(r'(?<!\d)(?:\+?\d[\s().-]*){8,}(?!\d)')


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_at TEXT NOT NULL,
          event TEXT NOT NULL,
          path TEXT NOT NULL,
          source TEXT NOT NULL,
          campaign TEXT NOT NULL DEFAULT '',
          device TEXT NOT NULL,
          referrer_host TEXT NOT NULL DEFAULT '',
          service TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_events_time ON events(occurred_at);
        CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
        CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
        ''')
    DB.chmod(0o600)


def clean(value, limit=180):
    if value is None: return ''
    value = str(value).strip().replace('\x00','')
    return value[:limit]


def _decoded(value: object) -> str:
    raw = clean(value, 1000)
    try:
        return unquote(raw)
    except Exception:
        return raw


def _looks_subject_specific(value: object) -> bool:
    raw = _decoded(value)
    return bool(_EMAIL_RE.search(raw) or _UUID_RE.search(raw) or _PHONE_RE.search(raw))


def _safe_dimension(value: object, limit: int) -> str:
    raw = clean(value, limit)
    return '[redacted]' if raw and _looks_subject_specific(raw) else raw


def _safe_path(value: object) -> str:
    raw = clean(value or '/', 600)
    try:
        path = urlparse(raw).path or '/'
    except Exception:
        path = '/'
    if not path.startswith('/'):
        return '/'
    path = clean(path, 300)
    if _looks_subject_specific(path):
        return '/redacted'
    return path


def _host(value: object) -> str:
    try:
        return (urlparse(clean(value, 500)).hostname or '').lower()
    except Exception:
        return ''


def _known_source_from_host(host: str) -> tuple[str, str] | None:
    host = str(host or '').lower()
    if not host:
        return None
    known = [
        ('google.', 'Google', 'google'), ('bing.com', 'Bing', 'bing.com'),
        ('chatgpt.com', 'ChatGPT', 'chatgpt.com'), ('perplexity.ai', 'Perplexity', 'perplexity.ai'),
        ('gemini.google.com', 'Gemini', 'gemini.google.com'), ('claude.ai', 'Claude', 'claude.ai'),
        ('facebook.com', 'Facebook', 'facebook.com'), ('instagram.com', 'Instagram', 'instagram.com'),
        ('linkedin.com', 'LinkedIn', 'linkedin.com'), ('tiktok.com', 'TikTok', 'tiktok.com')
    ]
    for needle, label, canonical_host in known:
        if needle in host:
            return label, canonical_host
    return None


def classify_source(referrer='', utm_source=''):
    utm = clean(utm_source, 80).lower()
    if utm:
        for needle, label, _canonical_host in _SOURCE_NEEDLES:
            if needle in utm:
                return label
        if re.fullmatch(r'app:[a-z0-9_.:-]{1,70}', utm):
            return 'App'
        # Do not persist arbitrary public query-string attribution verbatim.
        return 'UTM'
    host = _host(referrer)
    known = _known_source_from_host(host)
    if known:
        return known[0]
    return 'Referral' if host else 'Direct'


def _referrer_host_dimension(referrer: object) -> str:
    known = _known_source_from_host(_host(referrer))
    return known[1] if known else ('other' if _host(referrer) else '')


def record_event(payload, retention_days=180):
    event = clean(payload.get('event'), 60)
    if event not in ALLOWED_EVENTS: raise ValueError('unsupported event')
    path = _safe_path(payload.get('path') or '/')
    device = clean(payload.get('device') or 'unknown', 20).lower()
    if device not in ('mobile','tablet','desktop','unknown'): device = 'unknown'
    referrer = clean(payload.get('referrer'), 500)
    host = _referrer_host_dimension(referrer)
    source = classify_source(referrer, payload.get('utmSource'))
    campaign = _safe_dimension(payload.get('utmCampaign'), 100)
    service = _safe_dimension(payload.get('service'), 100)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    cutoff = (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=retention_days)).isoformat(timespec='seconds')
    with connect() as db:
        db.execute('DELETE FROM events WHERE occurred_at < ?', (cutoff,))
        db.execute('INSERT INTO events(occurred_at,event,path,source,campaign,device,referrer_host,service) VALUES(?,?,?,?,?,?,?,?)',
                   (now,event,path,source,campaign,device,host,service))
    return {'ok': True}


def privacy_profile(retention_days=180):
    days = max(1, min(int(retention_days), 36500))
    return {
      'subjectKeyed': False,
      'clientIpStored': False,
      'cookieOrSessionStored': False,
      'queryStringStored': False,
      'unknownReferrerHostStored': False,
      'obviousSubjectIdentifiersRedacted': True,
      'retentionDays': days,
      'retentionEnforcedBy': ['record_event', 'retention_enforcement'],
    }


def _pct_delta(current, previous):
    if previous == 0:
        return None if current else 0.0
    return round((current - previous) / previous * 100, 2)


def _period_counts(db, start, end=None):
    where='occurred_at>=?'; args=[start]
    if end is not None:
        where+=' AND occurred_at<?'; args.append(end)
    rows=db.execute(f'SELECT event,COUNT(*) n FROM events WHERE {where} GROUP BY event',args)
    counts={r['event']:r['n'] for r in rows}
    views=counts.get('page_view',0); bookings=counts.get('booking_click',0)
    app_landings=counts.get('app_landing_view',0); app_store_clicks=counts.get('app_store_click',0); app_testflight_clicks=counts.get('app_testflight_click',0); app_clicks=app_store_clicks+app_testflight_clicks
    return {
      'pageViews':views,'bookingClicks':bookings,
      'bookingRate':round((bookings/views*100) if views else 0,2),
      'appLandingViews':app_landings,'appStoreClicks':app_store_clicks,'appTestFlightClicks':app_testflight_clicks,
      'appDistributionClicks':app_clicks,
      'appStoreClickRate':round((app_store_clicks/app_landings*100) if app_landings else 0,2),
      'appDistributionClickRate':round((app_clicks/app_landings*100) if app_landings else 0,2),
      'heroCtaClicks':counts.get('hero_cta_click',0),
      'phoneClicks':counts.get('phone_click',0),
      'directionsClicks':counts.get('directions_click',0),
      'offerViews':counts.get('offer_viewed',0),'events':counts
    }


def summary(days=30):
    days=max(1,min(int(days),365))
    now=datetime.datetime.now(datetime.timezone.utc)
    current_start=now-datetime.timedelta(days=days)
    previous_start=current_start-datetime.timedelta(days=days)
    current_iso=current_start.isoformat(timespec='seconds')
    previous_iso=previous_start.isoformat(timespec='seconds')
    with connect() as db:
        current=_period_counts(db,current_iso)
        previous=_period_counts(db,previous_iso,current_iso)
        sources=[dict(r) for r in db.execute('''
          SELECT source,
          SUM(event='page_view') views,
          SUM(event='booking_click') bookings,
          SUM(event='phone_click') phoneClicks,
          SUM(event='directions_click') directionsClicks,
          SUM(event='app_landing_view') appLandings,
          SUM(event='app_store_click') appStoreClicks,
          SUM(event='app_testflight_click') appTestFlightClicks
          FROM events WHERE occurred_at>=? GROUP BY source
          HAVING views>0 OR bookings>0 OR appLandings>0 OR appStoreClicks>0 OR appTestFlightClicks>0
          ORDER BY views DESC,appLandings DESC,bookings DESC LIMIT 30''',(current_iso,))]
        for row in sources:
            row['bookingRate']=round((row['bookings']/row['views']*100) if row['views'] else 0,2)
        campaigns=[dict(r) for r in db.execute('''
          SELECT campaign,
          SUM(event='page_view') views,
          SUM(event='booking_click') bookings,
          SUM(event='app_landing_view') appLandings,
          SUM(event='app_store_click') appStoreClicks,
          SUM(event='app_testflight_click') appTestFlightClicks
          FROM events WHERE occurred_at>=? AND campaign<>'' GROUP BY campaign
          HAVING views>0 OR bookings>0 OR appLandings>0 OR appStoreClicks>0 OR appTestFlightClicks>0
          ORDER BY views DESC,appLandings DESC,bookings DESC LIMIT 30''',(current_iso,))]
        for row in campaigns:
            row['bookingRate']=round((row['bookings']/row['views']*100) if row['views'] else 0,2)
        devices=[dict(r) for r in db.execute("SELECT device,COUNT(*) views FROM events WHERE occurred_at>=? AND event='page_view' GROUP BY device ORDER BY views DESC",(current_iso,))]
        services=[dict(r) for r in db.execute("SELECT service,COUNT(*) selections FROM events WHERE occurred_at>=? AND event='service_selected' AND service<>'' GROUP BY service ORDER BY selections DESC",(current_iso,))]
        raw_daily={r['day']:dict(r) for r in db.execute('''
          SELECT substr(occurred_at,1,10) day,
          SUM(event='page_view') views,
          SUM(event='booking_click') bookings,
          SUM(event='phone_click') phoneClicks
          FROM events WHERE occurred_at>=?
          GROUP BY day ORDER BY day''',(current_iso,))}
    daily=[]
    for offset in range(days-1,-1,-1):
        day=(now-datetime.timedelta(days=offset)).date().isoformat()
        daily.append(raw_daily.get(day,{'day':day,'views':0,'bookings':0,'phoneClicks':0}))
    delta={
      'pageViewsPct':_pct_delta(current['pageViews'],previous['pageViews']),
      'bookingClicksPct':_pct_delta(current['bookingClicks'],previous['bookingClicks']),
      'bookingRatePoints':round(current['bookingRate']-previous['bookingRate'],2),
      'heroCtaClicksPct':_pct_delta(current['heroCtaClicks'],previous['heroCtaClicks']),
      'phoneClicksPct':_pct_delta(current['phoneClicks'],previous['phoneClicks']),
      'directionsClicksPct':_pct_delta(current['directionsClicks'],previous['directionsClicks']),
      'appLandingViewsPct':_pct_delta(current['appLandingViews'],previous['appLandingViews']),
      'appStoreClicksPct':_pct_delta(current['appStoreClicks'],previous['appStoreClicks']),
      'appTestFlightClicksPct':_pct_delta(current['appTestFlightClicks'],previous['appTestFlightClicks']),
      'appDistributionClicksPct':_pct_delta(current['appDistributionClicks'],previous['appDistributionClicks'])
    }
    return {
      **current,'days':days,'previous':previous,'delta':delta,
      'sources':sources,'sourceFunnels':sources,'campaignFunnels':campaigns,
      'devices':devices,'services':services,'daily':daily,
      'period':{
        'start':current_start.date().isoformat(),
        'end':now.date().isoformat(),
        'previousStart':previous_start.date().isoformat(),
        'previousEnd':current_start.date().isoformat()
      }
    }
