from pathlib import Path
import json, unicodedata

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'geo-radius-50.01km.json'


def _fold(value):
    return ' '.join(unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower().split())


def catalog():
    data = json.loads(DATA.read_text())
    if not isinstance(data, dict) or not isinstance(data.get('communes'), list):
        raise RuntimeError('Catalogue géographique invalide')
    return data


def default_policy():
    return {
        'enabled': True,
        'radiusKm': 50.01,
        'hubEnabled': True,
        'priorityMarketCount': 36,
        'bands': [
            {'label': 'Proximité', 'minKm': 0.0, 'maxKm': 15.0, 'discountPercent': 0.0},
            {'label': 'Zone intermédiaire', 'minKm': 15.0, 'maxKm': 30.0, 'discountPercent': 0.0},
            {'label': 'Zone éloignée', 'minKm': 30.0, 'maxKm': 40.0, 'discountPercent': 0.0},
            {'label': 'Zone 50 km', 'minKm': 40.0, 'maxKm': 50.01, 'discountPercent': 0.0},
        ],
    }


def policy(config):
    base = default_policy()
    raw = (config or {}).get('geoAcquisition') or {}
    base.update({k: raw.get(k, base[k]) for k in ('enabled', 'radiusKm', 'hubEnabled', 'priorityMarketCount')})
    if isinstance(raw.get('bands'), list) and raw['bands']:
        base['bands'] = raw['bands']
    return base

def _band_for(distance_km, bands):
    for band in bands:
        lo = float(band.get('minKm', 0))
        hi = float(band.get('maxKm', 0))
        if lo <= distance_km <= hi + 1e-9:
            return band
    return None


def find_commune(query):
    q = _fold(query)
    if not q:
        raise ValueError('Ville ou code postal requis')
    rows = catalog()['communes']
    exact = []
    partial = []
    for row in rows:
        names = {_fold(row.get('name'))}
        postals = {str(x).strip() for x in row.get('postalCodes') or []}
        if q in names or q in postals:
            exact.append(row)
        elif q in _fold(row.get('name')):
            partial.append(row)
    choices = exact or partial
    if not choices:
        raise ValueError('Commune hors zone ou inconnue')
    return min(choices, key=lambda x: float(x.get('distanceKm') or 9999))


def quote(config, query, services):
    row = find_commune(query)
    p = policy(config)
    distance = float(row['distanceKm'])
    if not p.get('enabled', True) or distance > float(p.get('radiusKm', 50.01)):
        raise ValueError('Commune hors zone desservie')
    band = _band_for(distance, p.get('bands') or [])
    discount = max(0.0, min(float((band or {}).get('discountPercent', 0) or 0), 100.0))
    prices = []
    for service in services:
        base = float(service['basePrice'])
        final = round(base * (1 - discount / 100.0), 2)
        prices.append({'key': service['key'], 'label': service['label'], 'basePrice': base, 'discountPercent': discount, 'finalPrice': final})
    return {
        'city': row['name'], 'postalCodes': row.get('postalCodes') or [], 'distanceKm': distance,
        'band': (band or {}).get('label', ''), 'prices': prices,
    }

def priority_markets(config, services, limit=None):
    data = catalog()
    p = policy(config)
    count = int(limit or p.get('priorityMarketCount', 36) or 36)
    count = max(6, min(count, 100))
    selected = sorted(data.get('communes') or [], key=lambda x: (-(x.get('population') or 0), x.get('distanceKm') or 9999))[:count]
    out = []
    for row in selected:
        band = _band_for(float(row['distanceKm']), p.get('bands') or [])
        discount = max(0.0, min(float((band or {}).get('discountPercent', 0) or 0), 100.0))
        prices = {s['key']: round(float(s['basePrice']) * (1 - discount / 100.0), 2) for s in services}
        out.append({
            'name': row['name'], 'postalCodes': row.get('postalCodes') or [], 'population': row.get('population') or 0,
            'distanceKm': float(row['distanceKm']), 'band': (band or {}).get('label', ''),
            'discountPercent': discount, 'prices': prices,
        })
    return out


def coverage(config, services):
    data = catalog(); p = policy(config)
    return {
        'center': data['center'], 'radiusKm': float(p.get('radiusKm', 50.01)), 'communeCount': int(data.get('count') or 0),
        'policy': p, 'markets': priority_markets(config, services),
    }
