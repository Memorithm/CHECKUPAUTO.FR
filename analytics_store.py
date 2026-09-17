from pathlib import Path
from urllib.parse import urlparse
import datetime, sqlite3, os

ROOT = Path(__file__).resolve().parent
PRIVATE_DIR = Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
DB = PRIVATE_DIR / 'analytics.sqlite3'
ALLOWED_EVENTS = {
    'page_view','hero_cta_click','booking_click','phone_click','directions_click',
    'service_selected','offer_viewed'
}

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

def classify_source(referrer='', utm_source=''):
    utm = clean(utm_source, 80).lower()
    if utm:
        for needle,label in (
            ('chatgpt','ChatGPT'),('perplexity','Perplexity'),('gemini','Gemini'),
            ('claude','Claude'),('google','Google'),('bing','Bing'),('facebook','Facebook'),
            ('instagram','Instagram'),('linkedin','LinkedIn'),('tiktok','TikTok')):
            if needle in utm: return label
        return 'UTM · ' + utm
    try: host = (urlparse(referrer).hostname or '').lower()
    except Exception: host = ''
    known = [
      ('google.', 'Google'), ('bing.com', 'Bing'), ('chatgpt.com', 'ChatGPT'),
      ('perplexity.ai', 'Perplexity'), ('gemini.google.com', 'Gemini'),
      ('claude.ai', 'Claude'), ('facebook.com', 'Facebook'), ('instagram.com', 'Instagram'),
      ('linkedin.com', 'LinkedIn'), ('tiktok.com', 'TikTok')
    ]
    for needle, label in known:
        if needle in host: return label
    return host or 'Direct'

def record_event(payload, retention_days=180):
    event = clean(payload.get('event'), 60)
    if event not in ALLOWED_EVENTS: raise ValueError('unsupported event')
    path = clean(payload.get('path') or '/', 300)
    if not path.startswith('/'): path = '/'
    device = clean(payload.get('device') or 'unknown', 20).lower()
    if device not in ('mobile','tablet','desktop','unknown'): device = 'unknown'
    referrer = clean(payload.get('referrer'), 500)
    try: host = clean(urlparse(referrer).hostname or '', 120)
    except Exception: host = ''
    source = classify_source(referrer, payload.get('utmSource'))
    campaign = clean(payload.get('utmCampaign'), 100)
    service = clean(payload.get('service'), 100)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    cutoff = (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=retention_days)).isoformat(timespec='seconds')
    with connect() as db:
        db.execute('DELETE FROM events WHERE occurred_at < ?', (cutoff,))
        db.execute('INSERT INTO events(occurred_at,event,path,source,campaign,device,referrer_host,service) VALUES(?,?,?,?,?,?,?,?)',
                   (now,event,path,source,campaign,device,host,service))
    return {'ok': True}

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
    return {
      'pageViews':views,'bookingClicks':bookings,
      'bookingRate':round((bookings/views*100) if views else 0,2),
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
          SUM(event='directions_click') directionsClicks
          FROM events WHERE occurred_at>=? GROUP BY source
          HAVING views>0 OR bookings>0
          ORDER BY views DESC,bookings DESC LIMIT 30''',(current_iso,))]
        for row in sources:
            row['bookingRate']=round((row['bookings']/row['views']*100) if row['views'] else 0,2)
        campaigns=[dict(r) for r in db.execute('''
          SELECT campaign,
          SUM(event='page_view') views,
          SUM(event='booking_click') bookings
          FROM events WHERE occurred_at>=? AND campaign<>'' GROUP BY campaign
          HAVING views>0 OR bookings>0
          ORDER BY views DESC,bookings DESC LIMIT 30''',(current_iso,))]
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
      'directionsClicksPct':_pct_delta(current['directionsClicks'],previous['directionsClicks'])
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
