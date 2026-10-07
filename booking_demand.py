"""Evidence-backed low-demand slot offers. Mercure remains the pricing authority.

Only aggregate appointment counts are cached. Publication is explicitly gated by
CYBERCHECK_LOW_DEMAND_PROMO_PUBLISH=1 on ONE production controller. Staging
and default installations are read-only; an uncertain write is never retried.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path
from collections import Counter, defaultdict

import analytics_store as analytics
import mercure_admin_client as mercure_admin
import mercure_public_client as mercure_public
import migration_write_freeze

DISCOUNT_EUR = 5.0
HISTORY_DAYS = 84
CACHE_SECONDS = 4 * 3600
MIN_WEEKDAY_BOOKINGS = 20
MIN_PEAK_BOOKINGS = 5
MAX_HIGHLIGHTS_PER_DAY = 2
MAX_NEW_PROMOTIONS_PER_RUN = 4
MAX_PROMOTION_DAYS_AHEAD = 6
PUBLISH_ENV = 'CYBERCHECK_LOW_DEMAND_PROMO_PUBLISH'
CONTROLLER_ENV = 'CYBERCHECK_LOW_DEMAND_PROMO_CONTROLLER'
AUTHORIZED_CONTROLLER = 'remoteops-thor'

_CACHE_LOCK = threading.Lock()
_CACHE = {'expires': 0.0, 'data': None}
_STOP = threading.Event()
_WORKER = None
_LAST_RUN = {'status': 'not_started'}


def _parse_appointment(value):
    try:
        value = str(value or '').strip()
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(mercure_admin.MERCURE_TIMEZONE)
        return parsed
    except (TypeError, ValueError):
        for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S'):
            try:
                return dt.datetime.strptime(str(value), fmt)
            except (TypeError, ValueError):
                continue
        return None


def _count_history(rows, today):
    """Discard individual rows/identities immediately after aggregation."""
    counts = Counter()
    totals = Counter()
    seen = set()
    first = today - dt.timedelta(days=HISTORY_DAYS)
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get('id') or '').strip()
        if not rid or rid in seen:
            continue
        # Mercure stores historical services as CTP, VTP, CV... instead
        # of the full public service labels. Compare the demand of the shared
        # centre's appointment capacity, irrespective of service code.
        centre = mercure_admin._fold_service(row.get('centre') or '')
        if centre and centre not in {'CHECK UP AUTO', 'CHECKUPAUTO'}:
            continue
        parsed = _parse_appointment(row.get('date_rdv'))
        if parsed is None or not first <= parsed.date() < today:
            continue
        status = mercure_admin._fold_service(row.get('statut') or row.get('status') or '')
        if any(word in status for word in ('ANNULE', 'CANCEL', 'SUPPRIME')):
            continue
        if 'CYBERCHECK TEST' in mercure_admin._fold_service(
            row.get('nom') or row.get('name') or row.get('commentaire')
        ):
            continue
        seen.add(rid)
        weekday = (parsed.weekday() + 1) % 7  # Mercure: Sunday=0.
        totals[weekday] += 1
        counts[(weekday, parsed.hour)] += 1
    peaks = {weekday: max(
        (counts[(weekday, hour)] for hour in range(24)), default=0)
        for weekday in totals}
    return {'counts': dict(counts), 'totals': dict(totals), 'peaks': peaks,
            'historyDays': HISTORY_DAYS}


def _load_history():
    today = mercure_admin.business_today()
    start = (today - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    session = mercure_admin._session()
    try:
        rows = mercure_admin._appointments(session, start, today.isoformat())
        return _count_history(rows, today)
    finally:
        session.close()


def snapshot():
    now = time.monotonic()
    with _CACHE_LOCK:
        if _CACHE['data'] is not None and now < _CACHE['expires']:
            return _CACHE['data']
    # No upstream call holding the cache lock; a missed cache only adds a read.
    data = _load_history()
    with _CACHE_LOCK:
        _CACHE.update(data=data, expires=time.monotonic() + CACHE_SECONDS)
    return data


def weakness(history, service, date_string, time_string):
    """Return evidence ratio (lower means weaker demand), or None.

    Compare like-for-like weekday and one-hour bands for the whole centre,
    with sample-size requirements; no evidence means no promotion.
    """
    try:
        date = dt.date.fromisoformat(str(date_string))
        clock = dt.time.fromisoformat(str(time_string))
    except ValueError:
        return None
    weekday = (date.weekday() + 1) % 7
    total = history['totals'].get(weekday, 0)
    peak = history['peaks'].get(weekday, 0)
    if total < MIN_WEEKDAY_BOOKINGS or peak < MIN_PEAK_BOOKINGS:
        return None
    booked = history['counts'].get((weekday, clock.hour), 0)
    ratio = (booked + 1) / (peak + 1)
    return ratio if ratio <= 0.5 and booked + 3 <= peak else None


def decorate_availability(data, *, authenticated, policy, history=None):
    """Copy the Mercure-cached payload; never leak member offers to guests.

    Only flag an actual server-reported price reduction, never a guessed or
    front-end-only discount. Existing provider promotions remain unchanged.
    """
    result = copy.deepcopy(data)
    if not authenticated or not policy.get('enabled', False):
        return result
    try:
        historic = history if history is not None else snapshot()
    except Exception:
        return result  # Fail closed if Mercure history cannot be authenticated.
    service = result.get('service', {}).get('key', '')
    if not policy.get('eligibleServices', {}).get(service, False):
        return result
    for day in result.get('days', []):
        candidates = []
        for slot in day.get('slots', []):
            try:
                base = float(slot['basePrice'])
                price = float(slot['price'])
            except (KeyError, TypeError, ValueError):
                continue
            saving = round(base - price, 2)
            if saving < DISCOUNT_EUR or not slot.get('promotion', False):
                continue
            score = weakness(historic, service, day.get('date'), slot.get('time'))
            if score is not None:
                candidates.append((score, str(slot.get('time')), slot, saving))
        for _, _, slot, saving in sorted(candidates, key=lambda item: (item[0], item[1]))[:MAX_HIGHLIGHTS_PER_DAY]:
            slot['lowDemandOffer'] = {'savingEuro': saving, 'kind': 'low-demand'}
    return result


def _ledger_connect():
    """Give the unique RemoteOps publisher its own root-owned SQLite ledger.

    Do not redirect CYBERCHECK_DATA_DIR: migration freeze checks must continue
    to inspect the application's authoritative data directory.
    """
    override = os.environ.get('CYBERCHECK_LOW_DEMAND_PROMO_LEDGER_DB', '').strip()
    if not override:
        return analytics.connect()
    if not _publisher_enabled():
        raise PermissionError('private promotion ledger requires RemoteOps authorization')
    location = Path(override)
    if not location.is_absolute():
        raise ValueError('private promotion ledger path must be absolute')
    parent = location.parent
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise PermissionError('private promotion ledger directory is not isolated')
    try:
        info = location.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise PermissionError('private promotion ledger file is not isolated')
    db = sqlite3.connect(location, timeout=5)
    db.row_factory = sqlite3.Row
    location.chmod(0o600)
    return db


def init_db():
    with _ledger_connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS booking_demand_promotion_attempts (
            slot_key TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            state TEXT NOT NULL,
            final_price REAL NOT NULL,
            promotion_id TEXT NOT NULL DEFAULT ''
        )''')


def _claim_promotion(key, price):
    # Across every run and service, cap attempts at two per day and one per
    # physical slot. Pending, uncertain, and verified attempts all count.
    _service, day, clock = key.split('|')
    dt.date.fromisoformat(day)
    dt.time.fromisoformat(clock)
    with _ledger_connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = [
            str(row[0]).split('|')
            for row in db.execute(
                'SELECT slot_key FROM booking_demand_promotion_attempts '
                'WHERE slot_key LIKE ?', (f'%|{day}|%',)
            )
        ]
        if (len(existing) >= MAX_HIGHLIGHTS_PER_DAY
                or any(len(parts) == 3 and parts[2] == clock for parts in existing)):
            return False
        row = db.execute(
            'INSERT OR IGNORE INTO booking_demand_promotion_attempts '
            '(slot_key,created_at,state,final_price) VALUES(?,?,?,?)',
            (key, dt.datetime.now(dt.timezone.utc).isoformat(), 'pending', price),
        )
        return row.rowcount == 1


def _record_result(key, state, promotion_id=''):
    with _ledger_connect() as db:
        db.execute(
            'UPDATE booking_demand_promotion_attempts SET state=?,promotion_id=? WHERE slot_key=?',
            (state, str(promotion_id)[:80], key),
        )


def candidate_slots(history, policy, availability_by_service, today=None):
    today = today or mercure_admin.business_today()
    cutoff = today + dt.timedelta(days=min(
        MAX_PROMOTION_DAYS_AHEAD, int(policy.get('horizonDays', 30))))
    allowed = set(policy.get('allowedWeekdays', []))
    cap = float(policy.get('maxDiscountPercent') or 0)
    grouped = defaultdict(list)
    for service, result in availability_by_service.items():
        if not policy.get('eligibleServices', {}).get(service, False):
            continue
        for day in result.get('days', []):
            try:
                day_date = dt.date.fromisoformat(day['date'])
            except (KeyError, ValueError, TypeError):
                continue
            if not today < day_date <= cutoff or (day_date.weekday() + 1) % 7 not in allowed:
                continue
            for slot in day.get('slots', []):
                clock = str(slot.get('time') or '')
                try:
                    start = dt.datetime.combine(day_date, dt.time.fromisoformat(clock))
                    finish = (start + dt.timedelta(minutes=5)).strftime('%H:%M')
                    base = float(slot.get('basePrice'))
                    price = float(slot.get('price'))
                except (TypeError, ValueError):
                    continue
                if (not slot.get('promotion') and abs(price - base) < 0.01
                        and base > DISCOUNT_EUR
                        and (cap <= 0 or DISCOUNT_EUR / base * 100 <= cap)
                        and policy.get('timeStart', '09:00') <= clock
                        and finish <= policy.get('timeEnd', '19:00')
                        and start.date() == (start + dt.timedelta(minutes=5)).date()):
                    score = weakness(history, service, day['date'], clock)
                    if score is not None:
                        grouped[day['date']].append({
                            'service': service, 'date': day['date'],
                            'time': clock, 'timeEnd': finish,
                            'finalPrice': round(base - DISCOUNT_EUR, 2),
                            'score': score,
                        })
    ranked = []
    for day in sorted(grouped):
        seen_times = set()
        for candidate in sorted(grouped[day], key=lambda item:
                                (item['score'], item['time'], item['service'])):
            if candidate['time'] in seen_times:
                continue
            ranked.append(candidate)
            seen_times.add(candidate['time'])
            if len(seen_times) >= MAX_HIGHLIGHTS_PER_DAY:
                break
    return ranked[:MAX_NEW_PROMOTIONS_PER_RUN]


def _publisher_enabled():
    return (os.environ.get(PUBLISH_ENV) == '1'
            and os.environ.get(CONTROLLER_ENV) == AUTHORIZED_CONTROLLER)


def run_once(policy, *, max_new_promotions=MAX_NEW_PROMOTIONS_PER_RUN):
    """Bounded publication requiring the approved RemoteOps controller."""
    global _LAST_RUN
    if type(max_new_promotions) is not int or not 1 <= max_new_promotions <= MAX_NEW_PROMOTIONS_PER_RUN:
        raise ValueError('invalid promotional publication limit')
    if not _publisher_enabled():
        return {'status': 'read_only', 'published': 0}
    if not policy.get('enabled') or migration_write_freeze.status().get('active', True):
        return {'status': 'blocked', 'published': 0}
    history = snapshot()  # History failure aborts without external writes.
    today = mercure_admin.business_today()
    date = (today + dt.timedelta(days=1)).isoformat()
    availability = {}
    for service in ('technical', 'fitted'):
        if policy.get('eligibleServices', {}).get(service, False):
            availability[service] = mercure_public.availability(service, date)
    candidates = candidate_slots(history, policy, availability, today)
    if not candidates:
        return {'status': 'no_candidates', 'published': 0}
    init_db()
    # Cross-host guard: a deterministic promotion name must also be absent
    # upstream. Only one production controller may have publishing enabled.
    existing = {mercure_admin._promotion_identity(row)[1]
                for row in mercure_admin.list_promotions()}
    published = 0
    attempted = 0
    for candidate in candidates:
        if attempted >= max_new_promotions:
            break
        service, day, clock = candidate['service'], candidate['date'], candidate['time']
        name = f"CHECKUPAUTO CRENEAU CALME {service} {day} {clock} {candidate['finalPrice']:.2f} EUR"
        key = f'{service}|{day}|{clock}'
        if name in existing or not _claim_promotion(key, candidate['finalPrice']):
            continue
        attempted += 1
        try:
            info = mercure_admin.plan_promotion_slot(
                name=name, final_price=candidate['finalPrice'],
                prestation_id=mercure_public.service(service)['id'],
                date_start=day, date_end=day,
                time_start=clock, time_end=candidate['timeEnd'],
                weekdays=[str((dt.date.fromisoformat(day).weekday() + 1) % 7)],
            )
            # A provider write acknowledgement is not proof of the customer
            # price. Re-read Mercure without the site's 20-second cache.
            meta = mercure_public.service(service)
            try:
                raw = mercure_public._provider_availability(meta['id'], day)
                verified_days = mercure_public._normalize_availability(
                    service, meta, day, raw)['days']
                verified = any(
                    entry.get('date') == day
                    and any(str(slot.get('time')) == clock
                            and abs(float(slot.get('price', 0)) - candidate['finalPrice']) < 0.01
                            for slot in entry.get('slots', []))
                    for entry in verified_days
                )
            except Exception:
                verified = False
            _record_result(key, 'verified' if verified else 'submitted_unverified',
                           info.get('promotionId', ''))
            existing.add(name)
            if verified:
                published += 1
        except Exception:
            # The HTTP request may have succeeded before raising; never retry.
            _record_result(key, 'uncertain')
    state = ('no_new_offers' if attempted == 0 else
             'verified' if published == attempted else 'unverified')
    _LAST_RUN = {'status': state, 'attempted': attempted,
                 'published': published,
                 'at': dt.datetime.now(dt.timezone.utc).isoformat()}
    return _LAST_RUN.copy()


def worker_status():
    return {'publicationEnabled': _publisher_enabled(), **_LAST_RUN}


def _loop(policy_loader):
    while not _STOP.is_set():
        try:
            run_once(policy_loader())
        except Exception:
            # No client data or privileged Mercure error is ever logged.
            global _LAST_RUN
            _LAST_RUN = {'status': 'upstream_unavailable'}
        if _STOP.wait(12 * 3600):
            break


def start(policy_loader):
    global _WORKER
    if not _publisher_enabled() or (_WORKER and _WORKER.is_alive()):
        return
    _STOP.clear()
    _WORKER = threading.Thread(target=_loop, args=(policy_loader,),
                               name='CheckupAutoLowDemandPromos', daemon=True)
    _WORKER.start()


def stop():
    _STOP.set()
