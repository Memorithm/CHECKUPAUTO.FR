from pathlib import Path
import datetime, json, os, requests
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
PRIVATE_DIR = Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
SESSION_FILE = PRIVATE_DIR / 'mercure-admin-session.json'
BASE = 'https://rdv.checkupauto.fr'

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

def session_status():
    try:
        s = _session()
        r = _check_auth(s.get(BASE + '/admin/calendrier', timeout=20, allow_redirects=False))
        return {'connected': r.status_code == 200, 'status': r.status_code}
    except Exception as exc:
        return {'connected': False, 'error': str(exc)}

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
    today = datetime.date.today()
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
