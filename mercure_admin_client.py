from pathlib import Path
import datetime, json, os, requests
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PRIVATE_DIR = Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
SESSION_FILE = PRIVATE_DIR / 'mercure-admin-session.json'
BASE = 'https://rdv.checkupauto.fr'
MERCURE_TIMEZONE = ZoneInfo('Europe/Paris')

def business_today(now=None):
    current = now if now is not None else datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(current, datetime.datetime):
        raise TypeError('datetime attendu')
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    return current.astimezone(MERCURE_TIMEZONE).date()

class MercureSessionError(RuntimeError):
    pass

def _session():
    if not SESSION_FILE.exists():
        raise MercureSessionError('Session Mercure non configurée')
    data = json.loads(SESSION_FILE.read_text())
    cookies = data.get('cookies') or {}
    if not cookies:
        raise MercureSessionError('Session Mercure vide')
    s = requests.Session()
    s.cookies.update(cookies)
    return s

def _check_auth(response):
    if response.status_code in (301, 302, 303, 307, 308):
        if '/admin/login' in (response.headers.get('Location') or ''):
            raise MercureSessionError('Session Mercure expirée')
    if 'inputUtl_username' in response.text[:12000]:
        raise MercureSessionError('Session Mercure expirée')
    return response

def _session_error_state(exc):
    if isinstance(exc, MercureSessionError):
        return 'session_unavailable'
    if isinstance(exc, requests.Timeout):
        return 'timeout'
    if isinstance(exc, requests.ConnectionError):
        return 'connection_error'
    if isinstance(exc, requests.RequestException):
        return 'request_error'
    if isinstance(exc, (json.JSONDecodeError, OSError, ValueError)):
        return 'session_invalid'
    return 'unexpected_error'


def session_status():
    try:
        s = _session()
        r = _check_auth(s.get(BASE + '/admin/calendrier', timeout=20, allow_redirects=False))
        connected = r.status_code == 200
        return {'connected': connected, 'status': r.status_code, 'state': 'ready' if connected else 'http_error'}
    except Exception as exc:
        return {
            'connected': False,
            'state': _session_error_state(exc),
            'error': 'Session Mercure indisponible',
        }

def _price(value):
    if value is None:
        return 0.0
    raw = str(value).replace('€', '').replace(' ', '').replace(',', '.').strip()
    try:
        return float(raw)
    except Exception:
        return 0.0

def _period(days):
    days = max(1, min(int(days), 365))
    today = business_today()
    start = today - datetime.timedelta(days=days - 1)
    end = today + datetime.timedelta(days=1)
    return days, start.isoformat(), end.isoformat()

def _appointments(s, start, end):
    r = _check_auth(s.post(BASE + '/admin/rdv_by_client', data={
        'name': '', 'startDate': start, 'endDate': end
    }, timeout=30, allow_redirects=False))
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError('Réponse Mercure rendez-vous invalide')
    return data

def _chart_data(s, period='month', display='day'):
    r = _check_auth(s.post(BASE + '/admin/chartData', data={
        'period': period, 'affichage': display
    }, timeout=30, allow_redirects=False))
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError('Réponse Mercure statistiques invalide')
    return data

def live_summary(days=30):
    days, start, end = _period(days)
    s = _session()
    rows = _appointments(s, start, end)
    partners = Counter((str(x.get('partenaire') or '').strip() or 'Direct / interne') for x in rows)
    payment = Counter(str(x.get('etat_paiement') or 'inconnu').strip().lower() for x in rows)
    honored = Counter(bool(x.get('est_honore')) for x in rows)
    services = defaultdict(lambda: {'count': 0, 'value': 0.0})
    total_value = paid_value = 0.0
    for row in rows:
        value = _price(row.get('prix_tcc'))
        total_value += value
        if str(row.get('etat_paiement') or '').strip().lower() == 'payé':
            paid_value += value
        name = str(row.get('prestation') or 'Non renseignée').strip()[:120]
        services[name]['count'] += 1
        services[name]['value'] += value
    online = sum(v for k, v in partners.items() if k != 'Direct / interne')
    by_service = [
        {'service': k, 'count': v['count'], 'value': round(v['value'], 2)}
        for k, v in sorted(services.items(), key=lambda item: item[1]['count'], reverse=True)
    ]
    chart = _chart_data(s, 'month', 'day') if days == 30 else None
    return {
        'connected': True,
        'days': days,
        'period': {'start': start, 'endExclusive': end},
        'appointments': len(rows),
        'onlineAppointments': online,
        'onlineRate': round((online / len(rows) * 100) if rows else 0, 2),
        'partners': [{'partner': k, 'count': v} for k, v in partners.most_common()],
        'paid': payment.get('payé', 0),
        'unpaid': payment.get('non payé', 0),
        'paymentStates': dict(payment),
        'honored': honored.get(True, 0),
        'notHonored': honored.get(False, 0),
        'scheduledValue': round(total_value, 2),
        'paidScheduledValue': round(paid_value, 2),
        'averageScheduledValue': round(total_value / len(rows), 2) if rows else 0,
        'services': by_service[:20],
        'dashboard30d': chart,
    }


def list_promotions():
    s = _session()
    r = _check_auth(s.get(BASE + '/admin/get_promotion', timeout=20, allow_redirects=False))
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError('Réponse Mercure promotions invalide')
    return data


def promotion_events(start, end):
    datetime.date.fromisoformat(start)
    datetime.date.fromisoformat(end)
    s = _session()
    r = _check_auth(s.get(BASE + '/admin/promotion/json', params={'start': start, 'end': end}, timeout=20, allow_redirects=False))
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError('Réponse Mercure créneaux promotionnels invalide')
    return data


def _promotion_identity(row):
    if not isinstance(row, dict):
        return '', ''
    pid = row.get('promotion_id') or row.get('id') or row.get('promo_id') or ''
    name = row.get('promotion_name') or row.get('nom') or row.get('name') or row.get('libelle') or ''
    return str(pid), str(name).strip()


def ensure_promotion(name, final_price, prestation_id):
    name = str(name).strip()[:120]
    final_price = round(float(final_price), 2)
    if not name or final_price <= 0:
        raise ValueError('Promotion invalide')
    s = _session()
    rows = list_promotions()
    pid = next((pid for row in rows for pid, n in [_promotion_identity(row)] if pid and n == name), '')
    if not pid:
        r = _check_auth(s.post(BASE + '/admin/promotion_add', data={'nom': name, 'reduction': f'{final_price:.2f}'}, timeout=20, allow_redirects=False))
        if r.status_code not in (200, 201, 302, 303):
            raise RuntimeError(f'Création promotion Mercure refusée ({r.status_code})')
        rows = list_promotions()
        pid = next((pid for row in rows for pid, n in [_promotion_identity(row)] if pid and n == name), '')
        if not pid:
            raise RuntimeError('Promotion créée mais identifiant Mercure introuvable')
    r = _check_auth(s.post(BASE + '/admin/promotion_prestation_update/' + pid,
        data=[('type_visite[]', str(prestation_id))], timeout=20, allow_redirects=False))
    if r.status_code not in (200, 201, 302, 303):
        raise RuntimeError(f'Association promotion/prestation refusée ({r.status_code})')
    return pid


def plan_promotion_slot(*, name, final_price, prestation_id, date_start, date_end, time_start, time_end, weekdays):
    datetime.date.fromisoformat(date_start); datetime.date.fromisoformat(date_end)
    if date_end < date_start:
        raise ValueError('Période promotionnelle invalide')
    if time_end <= time_start:
        raise ValueError('Plage horaire promotionnelle invalide')
    weekdays = [str(int(x)) for x in weekdays]
    if not weekdays or any(x not in {'0','1','2','3','4','5','6'} for x in weekdays):
        raise ValueError('Jours promotionnels invalides')
    pid = ensure_promotion(name, final_price, prestation_id)
    s = _session()
    data = [
        ('promotion_id', pid), ('promotion_creneau_id', ''), ('promotion_recurrence_id', ''),
        ('hDebutPromotion', time_start), ('hFinPromotion', time_end),
        ('dateDebutPromotion', date_start), ('dateFinPromotion', date_end),
        ('addPromoDynHeu1', ''), ('addPromoDynHeu2', ''), ('addPromoDynHeu3', ''),
        ('addPromoDynPrix1', ''), ('addPromoDynPrix2', ''), ('addPromoDynPrix3', ''),
    ] + [('joursRecurrences[]', x) for x in weekdays]
    r = _check_auth(s.post(BASE + '/admin/promotion_creneau_add', data=data, timeout=20, allow_redirects=False))
    if r.status_code not in (200, 201):
        raise RuntimeError(f'Créneau promotionnel Mercure refusé ({r.status_code})')
    return {'ok': True, 'promotionId': pid, 'providerStatus': r.status_code}


def remove_promotion_slot(creneau_id):
    creneau_id = str(creneau_id or '').strip()
    if not creneau_id:
        raise ValueError('Identifiant créneau requis')
    s = _session()
    r = _check_auth(s.post(BASE + '/admin/promotion_creneau_remove', data={'promotion_creneau_id': creneau_id}, timeout=20, allow_redirects=False))
    if r.status_code not in (200, 201):
        raise RuntimeError(f'Suppression créneau promotionnel refusée ({r.status_code})')
    return {'ok': True, 'providerStatus': r.status_code}


def _calendar_events(s, start, end):
    r=_check_auth(s.get(BASE+'/admin/rendez-vous/json',params={'start':start,'end':end},timeout=25,allow_redirects=False))
    r.raise_for_status(); data=r.json()
    if not isinstance(data,list): raise RuntimeError('Réponse calendrier Mercure invalide')
    return data


def _event_id(event):
    if not isinstance(event,dict): return ''
    ext=event.get('extendedProps') or {}
    return str(event.get('id') or ext.get('rendezVousId') or ext.get('rendezvousId') or '')


def create_synthetic_test_appointment(service_key, date_value, time_value):
    import mercure_public_client as mercure_public
    meta=mercure_public.service(service_key)
    datetime.date.fromisoformat(date_value)
    datetime.time.fromisoformat(time_value)
    s=_session()
    payload={
      'centre_type':'1','ligne_id':'454','duree':str(meta['duration']),'client_compte':'',
      'nom':'CYBERCHECK TEST','prenom':'E2E','email':'','telephone':'','civilite':'Autre',
      'marque':'132','modele':'1','marque_cl':'','modele_cl':'','energie':'2','immatriculation':'',
      'vehicule_client':'','prestation':str(meta['id']),'utilisateur':'464',
      'commentaire':'TEST CYBERCHECK E2E - SUPPRIMER','date':f'{date_value}T{time_value}',
      'convoyage':'false','pret':'false','depot':'false','rendezvous_id':'',
      'email_confirmation_vl':'false','imprime_confirmation_vl':'false','envoi_sms_vl':'false','rappel_sms_vl':'false',
      'tcheckDispo':'true','coupon_ct_easy':'','bon_commande':''
    }
    r=_check_auth(s.post(BASE+'/admin/rendez_vous_add',data=payload,timeout=30,allow_redirects=False))
    r.raise_for_status()
    try: body=r.json()
    except Exception: raise RuntimeError('Réponse de création Mercure non JSON')
    appointment_id=str((body or {}).get('id') or ((body or {}).get('event') or {}).get('id') or '')
    if not appointment_id: raise RuntimeError('Mercure n’a pas retourné l’identifiant du rendez-vous test')
    end=(datetime.date.fromisoformat(date_value)+datetime.timedelta(days=1)).isoformat()
    events=_calendar_events(s,date_value,end)
    verified=any(_event_id(e)==appointment_id for e in events)
    if not verified: raise RuntimeError('Rendez-vous créé mais non retrouvé dans le calendrier Mercure')
    return {'appointmentId':appointment_id,'verified':True,'providerStatus':r.status_code}


def remove_synthetic_test_appointment(appointment_id, appointment_at=''):
    appointment_id=str(appointment_id or '').strip()
    if not appointment_id: raise ValueError('Identifiant rendez-vous requis')
    s=_session()
    r=_check_auth(s.post(BASE+'/admin/rendez_vous_remove',data={'rendezvous_id':appointment_id},timeout=25,allow_redirects=False))
    if r.status_code not in (200,201): raise RuntimeError(f'Suppression Mercure refusée ({r.status_code})')
    if appointment_at:
        date_value=str(appointment_at).split('T',1)[0]
    else:
        date_value=business_today().isoformat()
    end=(datetime.date.fromisoformat(date_value)+datetime.timedelta(days=1)).isoformat()
    events=_calendar_events(s,date_value,end)
    verified=all(_event_id(e)!=appointment_id for e in events)
    if not verified: raise RuntimeError('Mercure signale encore le rendez-vous après suppression')
    return {'ok':True,'appointmentId':appointment_id,'verified':True,'providerStatus':r.status_code}


def login(username, password):
    import re
    username=str(username or '').strip(); password=str(password or '')
    if not username or not password: raise ValueError('Identifiant et mot de passe Mercure requis')
    s=requests.Session()
    r=s.get(BASE+'/admin',timeout=20)
    r.raise_for_status()
    m=re.search(r'name=["\']_csrf_token["\'][^>]*value=["\']([^"\']+)',r.text,re.I)
    if not m: raise RuntimeError('Jeton CSRF Mercure introuvable')
    r=s.post(BASE+'/admin/login',data={'utl_username':username,'password':password,'_csrf_token':m.group(1)},timeout=20,allow_redirects=False)
    location=r.headers.get('Location') or ''
    if r.status_code not in (301,302,303) or '/admin/calendrier' not in location:
        raise PermissionError('Connexion Mercure refusée')
    cookies=requests.utils.dict_from_cookiejar(s.cookies)
    if not cookies: raise RuntimeError('Mercure n’a retourné aucun cookie de session')
    SESSION_FILE.parent.mkdir(parents=True,exist_ok=True)
    owner=None
    try:
        st=SESSION_FILE.stat(); owner=(st.st_uid,st.st_gid)
    except FileNotFoundError:
        pass
    tmp=SESSION_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'cookies':cookies},separators=(',',':'))+'\n')
    tmp.chmod(0o600)
    if owner is not None and hasattr(os,'chown'):
        try: os.chown(tmp,*owner)
        except PermissionError: pass
    os.replace(tmp,SESSION_FILE)
    return {'connected':True,'status':302,'cookiesStored':len(cookies)}

def _centre_parameter_form_values(html_text):
    from html.parser import HTMLParser
    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_form=False; self.depth=0; self.values=[]
            self.textarea=None; self.textbuf=[]; self.select=None; self.options=[]; self.selected=None
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='form' and a.get('name')=='parametre_centre':
                self.in_form=True; self.depth=1; return
            if not self.in_form: return
            if tag=='form': self.depth+=1
            if tag=='input':
                name=a.get('name')
                if not name: return
                typ=(a.get('type') or 'text').lower()
                if typ in ('submit','button','file','image','reset'): return
                if typ in ('checkbox','radio') and 'checked' not in a: return
                self.values.append((name,a.get('value','')))
            elif tag=='textarea':
                self.textarea=a.get('name'); self.textbuf=[]
            elif tag=='select':
                self.select=a.get('name'); self.options=[]; self.selected=None
            elif tag=='option' and self.select:
                val=a.get('value','')
                self.options.append(val)
                if 'selected' in a: self.selected=val
        def handle_data(self,data):
            if self.in_form and self.textarea: self.textbuf.append(data)
        def handle_endtag(self,tag):
            if not self.in_form: return
            if tag=='textarea' and self.textarea:
                self.values.append((self.textarea,''.join(self.textbuf)))
                self.textarea=None; self.textbuf=[]
            elif tag=='select' and self.select:
                value=self.selected if self.selected is not None else (self.options[0] if self.options else '')
                self.values.append((self.select,value)); self.select=None; self.options=[]; self.selected=None
            elif tag=='form':
                self.depth-=1
                if self.depth<=0: self.in_form=False
    p=P(); p.feed(html_text); return p.values

def native_review_email_status():
    s=_session()
    r=_check_auth(s.get(BASE+'/admin/parametre_centre/240',timeout=20,allow_redirects=False)); r.raise_for_status()
    values=_centre_parameter_form_values(r.text)
    enabled=any(k=='parametre_centre[pc_envoi_email_avis]' and str(v)=='1' for k,v in values)
    return {'connected':True,'nativeFavorableOnlyEmailEnabled':enabled}

def disable_native_review_email_automation():
    s=_session()
    r=_check_auth(s.get(BASE+'/admin/parametre_centre/240',timeout=20,allow_redirects=False)); r.raise_for_status()
    values=_centre_parameter_form_values(r.text)
    before=any(k=='parametre_centre[pc_envoi_email_avis]' and str(v)=='1' for k,v in values)
    if not before:
        return {'ok':True,'changed':False,'nativeFavorableOnlyEmailEnabled':False}
    values=[(k,v) for k,v in values if k!='parametre_centre[pc_envoi_email_avis]']
    files=[(k,(None,str(v))) for k,v in values]
    resp=_check_auth(s.post(BASE+'/admin/parametre_centre/240',files=files,timeout=30,allow_redirects=False))
    if resp.status_code not in (200,201,302,303):
        raise RuntimeError(f'Désactivation automatisme avis Mercure refusée ({resp.status_code})')
    verify=_check_auth(s.get(BASE+'/admin/parametre_centre/240',timeout=20,allow_redirects=False)); verify.raise_for_status()
    now=_centre_parameter_form_values(verify.text)
    enabled=any(k=='parametre_centre[pc_envoi_email_avis]' and str(v)=='1' for k,v in now)
    if enabled: raise RuntimeError('Mercure a conservé l’automatisme favorable uniquement')
    return {'ok':True,'changed':True,'nativeFavorableOnlyEmailEnabled':False}

def send_google_review_email(rendezvous_id):
    raise RuntimeError('Envoi email via Mercure désactivé par la politique Checkup Auto')

def _customer_contact(s, client_kind, client_id):
    client_kind=str(client_kind or '').strip().lower()
    client_id=str(client_id or '').strip()
    if not client_id or client_kind not in {'account','free'}:
        return {'email':'','telephone':''}
    endpoint='/admin/get-client-compte/' if client_kind=='account' else '/admin/get-client-libre/'
    r=_check_auth(s.get(BASE+endpoint+client_id,timeout=20,allow_redirects=False))
    r.raise_for_status(); data=r.json()
    if not isinstance(data,dict): raise RuntimeError('Réponse Mercure client invalide')
    return {
      'email':str(data.get('email') or '').strip()[:254],
      'telephone':str(data.get('telephone') or '').strip()[:40],
    }


def customer_email(client_kind, client_id):
    return _customer_contact(_session(),client_kind,client_id).get('email','')


def vehicle_details(vehicle_id, session=None):
    vehicle_id=str(vehicle_id or '').strip()
    if not vehicle_id: raise ValueError('Identifiant véhicule requis')
    s=session or _session()
    r=_check_auth(s.get(BASE+'/admin/get-vehicule/'+vehicle_id,timeout=20,allow_redirects=False))
    r.raise_for_status(); data=r.json()
    if not isinstance(data,dict): raise RuntimeError('Réponse Mercure véhicule invalide')
    return data


def reminder_source_rows(start, end):
    datetime.date.fromisoformat(start); datetime.date.fromisoformat(end)
    s=_session(); events=_calendar_events(s,start,end); cache={}; out=[]; seen=set()
    for ev in events:
        if not isinstance(ev,dict): continue
        ext=ev.get('extendedProps') or {}
        rid=str(ext.get('rendezVousId') or '').strip()
        if not rid: continue
        account_id=str(ext.get('clientCompteId') or '').strip()
        free_id=str(ext.get('clientLibreId') or '').strip()
        client_kind='account' if account_id else ('free' if free_id else '')
        client_id=account_id or free_id
        if not client_kind: continue
        vehicle_ids=ext.get('vehiculeId') or []
        if not isinstance(vehicle_ids,list): vehicle_ids=[vehicle_ids]
        for raw_vid in vehicle_ids:
            vid=str(raw_vid or '').strip()
            if not vid: continue
            key=(vid,client_kind,client_id)
            if key in seen: continue
            seen.add(key)
            if vid not in cache:
                cache[vid]=vehicle_details(vid,s)
            due=str((cache[vid] or {}).get('date_echeance') or '').strip()[:10]
            try: datetime.date.fromisoformat(due)
            except Exception: continue
            out.append({'vehicleId':vid,'clientKind':client_kind,'clientId':client_id,'dueDate':due,'appointmentId':rid})
    return out


def review_followup_rows(days=2):
    days=max(1,min(int(days),7))
    today=business_today()
    start=(today-datetime.timedelta(days=days-1)).isoformat()
    end=(today+datetime.timedelta(days=1)).isoformat()
    s=_session(); rows=_appointments(s,start,end); events=_calendar_events(s,start,end)
    meta={}
    for ev in events:
        if not isinstance(ev,dict): continue
        ext=ev.get('extendedProps') or {}
        rid=str(ext.get('rendezVousId') or ev.get('id') or '').strip()
        if not rid: continue
        bg=str(ev.get('backgroundColor') or '').strip().lower().replace('#','')
        account_id=str(ext.get('clientCompteId') or '').strip()
        free_id=str(ext.get('clientLibreId') or '').strip()
        meta[rid]={
          'finished':bg in {'ccc','cccccc'},
          'email':str(ext.get('email') or '').strip()[:254],
          'clientKind':'account' if account_id else ('free' if free_id else ''),
          'clientId':account_id or free_id,
        }
    out=[]
    for row in rows:
        rid=str(row.get('id') or '').strip(); item=meta.get(rid,{})
        email=str(item.get('email') or '').strip()
        if not email and item.get('clientKind') and item.get('clientId'):
            try: email=_customer_contact(s,item['clientKind'],item['clientId']).get('email','')
            except Exception: email=''
        out.append({
          'id':rid,'dateRdv':str(row.get('date_rdv') or ''),
          'honored':bool(row.get('est_honore')),'finished':bool(item.get('finished')),
          'name':str(row.get('name') or '')[:120],'email':email[:254],
          'clientKind':str(item.get('clientKind') or ''),
          'clientId':str(item.get('clientId') or ''),
        })
    return out
