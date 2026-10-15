from __future__ import annotations

import datetime
import threading
import time
from typing import Any

import requests
import mercure_admin_client as mercure_admin

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
_KEY_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_PROVIDER_SEMAPHORE = threading.BoundedSemaphore(3)
_BREAKER_LOCK = threading.Lock()
_BREAKER_FAILURES = 0
_BREAKER_OPEN_UNTIL = 0.0
CACHE_TTL = 20.0
# Planning pages may show a list up to this old while a refresh runs in the
# background; booking checks always ask for a fresh read (allow_stale=False).
STALE_TTL = 300.0
SESSION_REUSE_SECONDS = 600.0
_SESSION_POOL: list[tuple[float, requests.Session]] = []
_REFRESHING: set[tuple[str, str]] = set()
BREAKER_THRESHOLD = 5
BREAKER_SECONDS = 60.0


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
    today = mercure_admin.business_today()
    if parsed < today:
        raise ValueError('La date est passée')
    if parsed > today + datetime.timedelta(days=180):
        raise ValueError('Date trop éloignée')
    return parsed.isoformat()


def _key_lock(key):
    with _CACHE_LOCK:
        return _KEY_LOCKS.setdefault(key, threading.Lock())


def _breaker_before():
    with _BREAKER_LOCK:
        if time.monotonic() < _BREAKER_OPEN_UNTIL:
            raise RuntimeError('Mercure temporairement protégé par le circuit breaker')


def _breaker_success():
    global _BREAKER_FAILURES, _BREAKER_OPEN_UNTIL
    with _BREAKER_LOCK:
        _BREAKER_FAILURES = 0
        _BREAKER_OPEN_UNTIL = 0.0


def _breaker_failure():
    global _BREAKER_FAILURES, _BREAKER_OPEN_UNTIL
    with _BREAKER_LOCK:
        _BREAKER_FAILURES += 1
        if _BREAKER_FAILURES >= BREAKER_THRESHOLD:
            _BREAKER_OPEN_UNTIL = time.monotonic() + BREAKER_SECONDS


def provider_health() -> dict[str, Any]:
    with _BREAKER_LOCK:
        remaining=max(0.0,_BREAKER_OPEN_UNTIL-time.monotonic()); failures=_BREAKER_FAILURES
    with _CACHE_LOCK:
        cache_entries=len(_CACHE)
    return {'circuitOpen':remaining>0,'retryAfterSeconds':round(remaining,1),'consecutiveFailures':failures,
            'maxConcurrentUpstream':3,'cacheEntries':cache_entries,'cacheTtlSeconds':CACHE_TTL}


def _provider_session() -> requests.Session:
    s = requests.Session()
    r = s.post(BASE + '/prendre_rdv', data={'id': CENTRE_ID}, timeout=20)
    r.raise_for_status()
    if 'Prestation_id' not in r.text:
        raise RuntimeError('Initialisation Mercure impossible')
    return s


def _pooled_session() -> tuple[requests.Session, bool]:
    """Reuse a recent Mercure browsing session: it saves the /prendre_rdv page
    load and a new TLS handshake on every planning read."""
    now = time.monotonic()
    with _CACHE_LOCK:
        while _SESSION_POOL:
            opened_at, session = _SESSION_POOL.pop()
            if now - opened_at < SESSION_REUSE_SECONDS:
                return session, True
            session.close()
    session = _provider_session()
    session._checkupauto_opened_at = now
    return session, False


def _release_session(session: requests.Session) -> None:
    opened_at = getattr(session, '_checkupauto_opened_at', None)
    if not isinstance(opened_at, float):
        session.close()
        return
    with _CACHE_LOCK:
        if len(_SESSION_POOL) < 3:
            _SESSION_POOL.append((opened_at, session))
            return
    session.close()


def _search_slots(session: requests.Session, service_id: str, start_date: str) -> dict[str, Any]:
    r = session.post(BASE + '/rech_dispon_rdv', data={
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


def _provider_availability(service_id: str, start_date: str) -> dict[str, Any]:
    _breaker_before()
    try:
        with _PROVIDER_SEMAPHORE:
            _breaker_before()
            s, reused = _pooled_session()
            try:
                data = _search_slots(s, service_id, start_date)
            except Exception:
                s.close()
                if not reused:
                    raise
                # A reused session may have expired on Mercure: retry once fresh.
                s = _provider_session()
                s._checkupauto_opened_at = time.monotonic()
                try:
                    data = _search_slots(s, service_id, start_date)
                except Exception:
                    s.close()
                    raise
            _release_session(s)
    except Exception:
        _breaker_failure()
        raise
    _breaker_success()
    return data


def _normalize_availability(service_key: str, meta: dict[str, Any], start_date: str, raw: dict[str, Any]) -> dict[str, Any]:
    provider_base = float(raw.get('tarif') or meta['basePrice'])
    days = []
    for item in raw.get('message', {}).get('donnees', []):
        d = item.get('date') or {}
        try:
            calendar_day = datetime.date(
                int(d.get('annee')), int((d.get('mois') or {}).get('numero')),
                int(d.get('jour')),
            )
        except (TypeError, ValueError):
            # Never expose provider records without a verifiable calendar day.
            continue
        if calendar_day.weekday() == 6:
            # Sunday is closed for public booking, even if Mercure labels it otherwise.
            continue
        day_date = calendar_day.isoformat()
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
        if not slots:
            # A Mercure day without bookable slots is not shown to customers.
            continue
        days.append({
            'date': day_date,
            'weekday': str(d.get('dow') or ''),
            'day': str(d.get('jour') or ''),
            'month': str((d.get('mois') or {}).get('nom') or ''),
            'available': bool(slots),
            'slots': slots,
        })
    return {
        'service': {'key': service_key, **meta},
        'providerBasePrice': provider_base,
        'startDate': start_date,
        'days': days,
        'generatedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }


def _refresh(service_key: str, meta: dict[str, Any], start_date: str) -> dict[str, Any]:
    raw = _provider_availability(meta['id'], start_date)
    result = _normalize_availability(service_key, meta, start_date, raw)
    with _CACHE_LOCK:
        _CACHE[(service_key, start_date)] = (time.monotonic(), result)
    return result


def _refresh_in_background(service_key: str, meta: dict[str, Any], start_date: str) -> None:
    key = (service_key, start_date)
    with _CACHE_LOCK:
        if key in _REFRESHING:
            return
        _REFRESHING.add(key)

    def run():
        try:
            with _key_lock(key):
                with _CACHE_LOCK:
                    hit = _CACHE.get(key)
                if hit and time.monotonic() - hit[0] < CACHE_TTL:
                    return
                _refresh(service_key, meta, start_date)
        except Exception:
            pass  # the stale list stays; the next visit retries
        finally:
            with _CACHE_LOCK:
                _REFRESHING.discard(key)

    threading.Thread(target=run, daemon=True, name='MercureAvailabilityRefresh').start()


def availability(service_key: str, start_date: str, *, allow_stale: bool = False) -> dict[str, Any]:
    """Mercure free slots for one week. ``allow_stale`` is for display only: it
    answers at once with a list up to STALE_TTL old and refreshes it behind."""
    meta = service(service_key)
    start_date = _date(start_date)
    cache_key = (service_key, start_date)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    if allow_stale and hit and now - hit[0] < STALE_TTL:
        _refresh_in_background(service_key, meta, start_date)
        return hit[1]
    with _key_lock(cache_key):
        now = time.monotonic()
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and now - hit[0] < CACHE_TTL:
                return hit[1]
        return _refresh(service_key, meta, start_date)


PAYMENT_OPTIONS_TTL = 300.0
_PAYMENT_OPTIONS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _provider_payment_options(service_id: str) -> dict[str, Any]:
    _breaker_before()
    try:
        with _PROVIDER_SEMAPHORE:
            _breaker_before()
            s = _provider_session()
            try:
                # Same read the public Mercure booking page performs once a
                # service is chosen; it does not create anything.
                r = s.post(BASE + '/get_energie_prestation', data={
                    'prestation': service_id, 'type_centre': '1', 'iframe': 'false', 'id': '',
                }, timeout=20, allow_redirects=False)
                r.raise_for_status()
                data = r.json()
                if (r.status_code != 200 or not isinstance(data, dict)
                        or type(data.get('paiementWeb')) is not bool
                        or type(data.get('paiementCentre')) is not bool):
                    raise RuntimeError('Options de paiement Mercure invalides')
            finally:
                s.close()
    except Exception:
        _breaker_failure()
        raise
    _breaker_success()
    return data


def payment_options(service_key: str) -> dict[str, Any]:
    """Payment modes Mercure offers for a service: ``online`` means Mercure's own
    web payment (Payline on rdv.checkupauto.fr) is switched on for it. This is a
    configuration read, never proof that a booking was paid."""
    meta = service(service_key)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _PAYMENT_OPTIONS_CACHE.get(service_key)
        if hit and now - hit[0] < PAYMENT_OPTIONS_TTL:
            return hit[1]
    raw = _provider_payment_options(meta['id'])
    energies = []
    for item in raw.get('energies') or []:
        value = item.get('id') if isinstance(item, dict) else None
        if value is not None and str(value).strip().isdigit():
            energies.append(str(value).strip())
    result = {
        'service': service_key,
        'online': raw['paiementWeb'],
        'centre': raw['paiementCentre'],
        # Mercure energy ids accepted for this service (1763: 1 Diesel,
        # 2 Essence, 3 Hybride, 4 Electrique on 2026-10-14).
        'energyIds': energies,
        'checkedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    with _CACHE_LOCK:
        _PAYMENT_OPTIONS_CACHE[service_key] = (time.monotonic(), result)
    return result
