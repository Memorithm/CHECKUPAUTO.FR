from __future__ import annotations

from pathlib import Path
from collections import Counter
import datetime, json, math, os, sqlite3

DATA_DIR = Path(os.environ.get('CYBERCHECK_DATA_DIR','/root/CyberCheckData'))
DB = DATA_DIR / 'competitive.sqlite3'

TOPICS = {
    'accueil': ('accueil','aimable','sympa','gentil','courtois','chaleureux'),
    'professionnalisme': ('professionnel','professionnalisme','serieux','sérieux','conseil','explication'),
    'rapidite': ('rapide','rapidité','vite','temps voulu','ponctuel','ponctualité','à l’heure',"a l'heure"),
    'reservation': ('rendez-vous','rendez vous','rdv','réservation','reservation','prise de rendez'),
    'prix': ('prix','tarif','cher','pas cher','économ','promo','promotion'),
    'attente': ('attente','attendre','retard'),
    'confort': ('salle d’attente',"salle d'attente",'parking','café','cafe','toilette'),
}

WEIGHTS = {
    'price': 0.18, 'reviews': 0.21, 'convenience': 0.15, 'availability': 0.16,
    'digital': 0.10, 'visibility': 0.10, 'services': 0.05, 'promotion': 0.05,
}

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try: DATA_DIR.chmod(0o700)
    except PermissionError: pass
    db=sqlite3.connect(DB, timeout=10)
    db.row_factory=sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS competitors(
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          address TEXT NOT NULL DEFAULT '',
          website TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL DEFAULT '',
          distance_km REAL,
          is_self INTEGER NOT NULL DEFAULT 0,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          competitor_id TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          source TEXT NOT NULL,
          source_url TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          FOREIGN KEY(competitor_id) REFERENCES competitors(id)
        );
        CREATE INDEX IF NOT EXISTS idx_comp_obs ON observations(competitor_id,captured_at DESC);
        CREATE TABLE IF NOT EXISTS reviews(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          competitor_id TEXT NOT NULL,
          source TEXT NOT NULL,
          external_id TEXT NOT NULL DEFAULT '',
          reviewed_at TEXT NOT NULL DEFAULT '',
          rating REAL,
          text TEXT NOT NULL DEFAULT '',
          owner_response INTEGER NOT NULL DEFAULT 0,
          captured_at TEXT NOT NULL,
          UNIQUE(competitor_id,source,external_id)
        );
        """)
    DB.chmod(0o600)

def upsert_competitor(cid,name,address='',website='',phone='',distance_km=None,is_self=False):
    stamp=now_iso()
    with connect() as db:
        db.execute("""INSERT INTO competitors(id,name,address,website,phone,distance_km,is_self,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET name=excluded.name,address=excluded.address,website=excluded.website,
          phone=excluded.phone,distance_km=COALESCE(excluded.distance_km,competitors.distance_km),
          is_self=excluded.is_self,updated_at=excluded.updated_at""",
          (cid,name,address,website,phone,distance_km,1 if is_self else 0,stamp,stamp))

def add_observation(cid, source, category, payload, source_url='', captured_at=None):
    with connect() as db:
        db.execute('INSERT INTO observations(competitor_id,captured_at,source,source_url,category,payload_json) VALUES(?,?,?,?,?,?)',
                   (cid,captured_at or now_iso(),source,source_url,category,json.dumps(payload,ensure_ascii=False,separators=(',',':'))))

def add_review(cid, source, text, rating=None, external_id='', reviewed_at='', owner_response=False):
    ext=external_id or f'anon-{abs(hash((cid,source,text,reviewed_at)))%10**14}'
    with connect() as db:
        db.execute("""INSERT OR IGNORE INTO reviews(competitor_id,source,external_id,reviewed_at,rating,text,owner_response,captured_at)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (cid,source,ext,reviewed_at,float(rating) if rating is not None else None,str(text)[:2000],1 if owner_response else 0,now_iso()))

def latest_observations(cid):
    out={}
    with connect() as db:
        rows=db.execute('SELECT * FROM observations WHERE competitor_id=? ORDER BY captured_at DESC,id DESC',(cid,)).fetchall()
    for r in rows:
        if r['category'] not in out:
            try: payload=json.loads(r['payload_json'])
            except Exception: payload={}
            out[r['category']]={'capturedAt':r['captured_at'],'source':r['source'],'sourceUrl':r['source_url'],'data':payload}
    return out

def review_analysis(cid, days=365):
    cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=days)).isoformat(timespec='seconds')
    with connect() as db:
        rows=db.execute('SELECT rating,text,owner_response FROM reviews WHERE competitor_id=? AND captured_at>=?',(cid,cutoff)).fetchall()
    topic=Counter(); pos=Counter(); neg=Counter(); ratings=[]
    for r in rows:
        text=(r['text'] or '').lower()
        if r['rating'] is not None: ratings.append(float(r['rating']))
        for key,needles in TOPICS.items():
            if any(n in text for n in needles):
                topic[key]+=1
                if r['rating'] is not None:
                    if float(r['rating'])>=4: pos[key]+=1
                    elif float(r['rating'])<=2: neg[key]+=1
    return {
      'sampleSize':len(rows),
      'averageRating':round(sum(ratings)/len(ratings),2) if ratings else None,
      'responseRate':round(sum(int(r['owner_response']) for r in rows)/len(rows)*100,1) if rows else None,
      'topics':[{'topic':k,'mentions':v,'positive':pos[k],'negative':neg[k]} for k,v in topic.most_common()],
    }

def _clamp(v):
    return max(0.0,min(100.0,float(v)))

def _scores(cid, own_price=80.0):
    obs=latest_observations(cid)
    profile=(obs.get('profile') or {}).get('data',{})
    pricing=(obs.get('pricing') or {}).get('data',{})
    visibility=(obs.get('visibility') or {}).get('data',{})
    availability=(obs.get('availability') or {}).get('data',{})
    digital=(obs.get('digital') or {}).get('data',{})
    services=(obs.get('services') or {}).get('data',{})
    reviews=(obs.get('reviews_summary') or {}).get('data',{})
    price=pricing.get('carPrice')
    price_score=50 if price is None else _clamp(50+(own_price-float(price))*3.0)
    rating=reviews.get('rating'); count=reviews.get('reviewCount',0) or 0
    review_score=50 if rating is None else _clamp((float(rating)/5)*72 + min(math.log10(max(1,count))/3,1)*28)
    convenience=50
    convenience += 12 if profile.get('openSaturday') else 0
    convenience += 8 if profile.get('withoutAppointment') else 0
    convenience += 6 if profile.get('parking') else 0
    convenience += 4 if profile.get('waitingRoom') else 0
    return {
      'price':round(price_score,1),
      'reviews':round(review_score,1),
      'convenience':round(_clamp(convenience),1),
      'availability':round(_clamp(float(availability.get('score',50))),1),
      'digital':round(_clamp(float(digital.get('score',50))),1),
      'visibility':round(_clamp(float(visibility.get('score',50))),1),
      'services':round(_clamp(float(services.get('score',50))),1),
      'promotion':round(_clamp(float(pricing.get('promotionScore',50))),1),
    }

def attractiveness(cid, own_price=80.0):
    s=_scores(cid,own_price)
    return round(sum(s[k]*WEIGHTS[k] for k in WEIGHTS),1),s

def _factor_label(k):
    return {'price':'Prix','reviews':'Avis & réputation','convenience':'Commodité','availability':'Disponibilité',
            'digital':'Parcours digital','visibility':'Visibilité locale','services':'Étendue des services','promotion':'Promotions'}[k]

def choice_explanation(cid, self_id='checkup-auto'):
    self_total,self_scores=attractiveness(self_id,80.0)
    total,scores=attractiveness(cid,80.0)
    gaps=[]
    for k in WEIGHTS:
        delta=round(scores[k]-self_scores[k],1)
        if delta>=5:
            gaps.append({'factor':k,'label':_factor_label(k),'gap':delta,'competitorScore':scores[k],'ourScore':self_scores[k]})
    gaps.sort(key=lambda x:x['gap']*WEIGHTS[x['factor']],reverse=True)
    return {'attractivenessIndex':total,'ourIndex':self_total,'drivers':gaps[:6],
            'interpretation':'facteurs explicatifs observés, pas preuve causale individuelle'}

def summary():
    with connect() as db:
        comps=[dict(r) for r in db.execute('SELECT * FROM competitors WHERE active=1 ORDER BY is_self DESC,name')]
    out=[]
    for c in comps:
        total,scores=attractiveness(c['id'])
        obs=latest_observations(c['id'])
        row={**c,'attractivenessIndex':total,'scores':scores,'reviewAnalysis':review_analysis(c['id']),'latest':obs}
        if not c['is_self']: row['choiceExplanation']=choice_explanation(c['id'])
        out.append(row)
    prices=[]
    for c in out:
        p=((c['latest'].get('pricing') or {}).get('data') or {}).get('carPrice')
        if p is not None: prices.append(float(p))
    prices.sort()
    median=None
    if prices:
        n=len(prices); median=prices[n//2] if n%2 else (prices[n//2-1]+prices[n//2])/2
    return {'generatedAt':now_iso(),'radiusKm':50.01,'competitors':out,
            'market':{'observedCarPrices':prices,'min':min(prices) if prices else None,'max':max(prices) if prices else None,'median':median},
            'method':'observations publiques + APIs/connecteurs autorisés + données first-party; aucune donnée privée concurrente'}

def seed_public_baseline():
    init_db()
    stamp='2026-09-18T00:00:00+00:00'
    upsert_competitor('checkup-auto','Check Up Auto','1 Rue Niépce, 78130 Les Mureaux',is_self=True)
    upsert_competitor('autocontrol-mureaux','AUTOCONTROL','132-134 Av. Paul Raoult, 78130 Les Mureaux')
    upsert_competitor('securitest-auchan-mureaux','Sécuritest Les Mureaux','Centre Commercial Auchan, Av. Paul Raoult, 78130 Les Mureaux')
    with connect() as db:
        exists=db.execute("SELECT COUNT(*) n FROM observations WHERE source='seed-2026-09-18'").fetchone()['n']
    if exists: return
    add_observation('checkup-auto','seed-2026-09-18','pricing',{'carPrice':80,'channelPriceFrom':44.99,'promotionScore':78},'https://www.cteasy.com/fr/controle-technique-centre/S078Z206/78130/les-mureaux/les-mureaux/',stamp)
    add_observation('checkup-auto','seed-2026-09-18','reviews_summary',{'rating':4.5,'reviewCount':434},'https://www.cteasy.com/fr/controle-technique-centre/S078Z206/78130/les-mureaux/les-mureaux/',stamp)
    add_observation('checkup-auto','seed-2026-09-18','profile',{'openSaturday':True,'parking':True,'waitingRoom':True},'',stamp)
    add_observation('checkup-auto','seed-2026-09-18','digital',{'score':82},'',stamp)
    add_observation('checkup-auto','seed-2026-09-18','availability',{'score':75},'',stamp)
    add_observation('checkup-auto','seed-2026-09-18','visibility',{'score':62},'',stamp)
    add_observation('checkup-auto','seed-2026-09-18','services',{'score':72},'',stamp)

    add_observation('autocontrol-mureaux','seed-2026-09-18','pricing',{'carPrice':90,'suvPrice':100,'utilityPrice':100,'promotionScore':35},'https://www.pagesjaunes.fr/pros/56124789',stamp)
    add_observation('autocontrol-mureaux','seed-2026-09-18','reviews_summary',{'rating':4.8,'reviewCount':242},'https://centre.contact/f/centre-controle-technique-autocontrol-7278938/',stamp)
    add_observation('autocontrol-mureaux','seed-2026-09-18','profile',{'openSaturday':True,'withoutAppointment':True,'parking':True},'https://www.pagesjaunes.fr/pros/56124789',stamp)
    add_observation('autocontrol-mureaux','seed-2026-09-18','digital',{'score':80,'booking24x7':True},'https://www.pagesjaunes.fr/pros/56124789',stamp)
    add_observation('autocontrol-mureaux','seed-2026-09-18','availability',{'score':80},'',stamp)
    add_observation('autocontrol-mureaux','seed-2026-09-18','visibility',{'score':72},'',stamp)
    add_observation('autocontrol-mureaux','seed-2026-09-18','services',{'score':88},'https://www.pagesjaunes.fr/pros/56124789',stamp)

    add_observation('securitest-auchan-mureaux','seed-2026-09-18','reviews_summary',{'rating':3.4,'reviewCount':119},'https://centre.contact/f/securitest-controle-technique-automobile-les-mureaux-7275581/',stamp)
    add_observation('securitest-auchan-mureaux','seed-2026-09-18','profile',{'openSaturday':True,'parking':True},'',stamp)
    add_observation('securitest-auchan-mureaux','seed-2026-09-18','digital',{'score':66},'',stamp)
    add_observation('securitest-auchan-mureaux','seed-2026-09-18','availability',{'score':68},'',stamp)
    add_observation('securitest-auchan-mureaux','seed-2026-09-18','visibility',{'score':70},'',stamp)
    add_observation('securitest-auchan-mureaux','seed-2026-09-18','services',{'score':70},'',stamp)
    add_observation('securitest-auchan-mureaux','seed-2026-09-18','pricing',{'carPrice':None,'promotionScore':45},'',stamp)

init_db()

def seed_review_baseline():
    # Short normalized summaries of public review themes, not full copied reviews.
    add_review('checkup-auto','CTeasy','Accueil très aimable et salle d’attente appréciée.',5,'cteasy-seed-1','2026-09-01')
    add_review('autocontrol-mureaux','public-web','Équipe sympathique et professionnelle, explications appréciées.',5,'auto-seed-1','2026-06-25')
    add_review('autocontrol-mureaux','public-web','Travail rapide et prise de rendez-vous facile.',5,'auto-seed-2','2026-06-09')
    add_review('autocontrol-mureaux','public-web','Rendez-vous à l’heure et personnel agréable.',5,'auto-seed-3','2026-05-31')
    add_review('securitest-auchan-mureaux','public-web','Personnel sérieux et rendez-vous rapide.',5,'sec-seed-1','2026-01-26')
    add_review('securitest-auchan-mureaux','public-web','Bon accueil et technicien professionnel.',5,'sec-seed-2','2025-09-30',True)

def connector_status():
    return {
      'googlePlacesConfigured': bool(os.environ.get('GOOGLE_PLACES_API_KEY','').strip()),
      'serpProviderConfigured': bool(os.environ.get('CYBERCHECK_SERP_API_KEY','').strip()),
      'firstPartyAvailable': True,
      'publicBaselineLoaded': True,
      'recommendedCadenceHours': 24,
      'reviewCadenceHours': 24,
      'priceCadenceHours': 6,
      'availabilityCadenceHours': 3,
    }
