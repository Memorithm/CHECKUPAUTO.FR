from __future__ import annotations

import datetime
import threading
import time
from typing import Any

import requests

BASE = 'https://rdv.checkupauto.fr'
CENTRE_ID = '240'

SERVICES = {
    'technical': {
        'id': '1763',
        'label': 'Contrôle technique',
        'providerLabel': 'TOUT VEHICULE HORS CAMPING CAR',
        'basePrice': 80.0,
        'duration': 40,
    },
    'fitted': {
        'id': '1771',
        'label': 'Véhicule aménagé',
        'providerLabel': 'VISITE TECHNIQUE VASP (CAMPING CAR,SANITAIRE,FOOD TRUCK,...)',
        'basePrice': 90.0,
        'duration': 40,
    },
}

_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL = 20.0


def service(service_key: str) -> dict[str, Any]:
    item = SERVICES.get(str(service_key or '').strip())
    if not item:
        raise ValueError('Prestation non réservable en ligne')
    return item


def public_services() -> list[dict[str, Any]]:
    return [{'key': key, **value} for key, value in SERVICES.items()]


def _date(value: str) -> str:
    try:
        parsed = datetime.date.fromisoformat(str(value))
    except Exception as exc:
        raise ValueError('Date invalide') from exc
    today = datetime.date.today()
    if parsed < today:
        raise ValueError('La date est passée')
    if parsed > today + datetime.timedelta(days=180):
        raise ValueError('Date trop éloignée')
    return parsed.isoformat()


def _provider_session() -> requests.Session:
    s = requests.Session()
    r = s.post(BASE + '/prendre_rdv', data={'id': CENTRE_ID}, timeout=20)
    r.raise_for_status()
    if 'Prestation_id' not in r.text:
        raise RuntimeError('Initialisation Mercure impossible')
    return s


def _provider_availability(service_id: str, start_date: str) -> dict[str, Any]:
    s = _provider_session()
    r = s.post(BASE + '/rech_dispon_rdv', data={
        'prestation_vl': service_id,
        'prestation_pl': '',
        'date': start_date,
        'iframe': 'false',
        'id': '',
    }, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or data.get('status') != 200:
        raise RuntimeError('Disponibilités Mercure invalides')
    return data


def availability(service_key: str, start_date: str) -> dict[str, Any]:
    meta = service(service_key)
    start_date = _date(start_date)
    cache_key = (service_key, start_date)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    raw = _provider_availability(meta['id'], start_date)
    provider_base = float(raw.get('tarif') or meta['basePrice'])
    days = []
    for item in raw.get('message', {}).get('donnees', []):
        d = item.get('date') or {}
        day_date = f"{d.get('annee')}-{d.get('mois', {}).get('numero')}-{d.get('jour')}"
        slots = []
        for period in ('AM', 'PM'):
            for slot in (item.get(period) or {}).get('creneaux', []):
                price = round(float(slot.get('prix') or provider_base), 2)
                saving = round(max(0.0, provider_base - price), 2)
                pct = round((saving / provider_base * 100) if provider_base else 0, 1)
                slots.append({
                    'time': str(slot.get('heure') or ''),
                    'price': price,
                    'basePrice': provider_base,
                    'promotion': price < provider_base,
                    'saving': saving,
                    'discountPercent': pct,
                })
        days.append({
            'date': day_date,
            'weekday': str(d.get('dow') or ''),
            'day': str(d.get('jour') or ''),
            'month': str((d.get('mois') or {}).get('nom') or ''),
            'available': bool(slots),
            'slots': slots,
        })
    result = {
        'service': {'key': service_key, **meta},
        'providerBasePrice': provider_base,
        'startDate': start_date,
        'days': days,
        'generatedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, result)
    return result
