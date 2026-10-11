import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';

const require = createRequire(import.meta.url);
const J = require('./booking-journey.js');

const DATA = {
  ccid: 'intent-token-000000000001', cct: 'cct-fixed', termsVersion: '2026-10-01',
  termsContentHash: 'a'.repeat(64), requiresImmediatePerformance: false,
  service: 'technical', date: '2026-12-15', time: '09:00',
  vehicleId: '00000000-0000-4000-8000-0000000000aa', csrf: 'c'.repeat(64)
};
const KEY = 'k'.repeat(32);

function fakeFetch(routes) {
  const calls = [];
  const impl = async (url, options = {}) => {
    const path = url.split('?')[0];
    calls.push({ url, path, method: options.method || 'GET', headers: options.headers || {},
      body: options.body ? JSON.parse(options.body) : null });
    const handler = routes[path];
    if (!handler) throw new Error('unexpected ' + url);
    const out = typeof handler === 'function' ? handler(calls[calls.length - 1]) : handler;
    if (out === 'network') throw new TypeError('network');
    return { status: out.status, json: async () => out.body };
  };
  return { impl, calls };
}
const ok = { status: 200, body: { ok: true } };
const preflightReady = { status: 200, body: { ok: true, bookingEnabled: true, slotAvailableAtCheck: true, priceCents: 7200 } };

test('confirmed: consent, preflight then a single create with the idempotency key', async () => {
  const f = fakeFetch({
    [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
    [J.ROUTES.create]: { status: 200, body: { ok: true, confirmed: true, state: 'confirmed' } }
  });
  const steps = [];
  const result = await J.submitBooking({ fetchImpl: f.impl, data: DATA, requestKey: KEY, onStep: s => steps.push(s) });
  assert.equal(result.state, 'confirmed');
  assert.equal(result.priceCents, 7200);
  assert.deepEqual(f.calls.map(c => c.path), [J.ROUTES.acceptTerms, J.ROUTES.preflight, J.ROUTES.create]);
  assert.deepEqual(steps, ['consent', 'preflight', 'create']);
  assert.deepEqual(f.calls[1].body, { service: 'technical', date: '2026-12-15', time: '09:00', vehicleId: DATA.vehicleId });
  assert.equal(f.calls[2].body.requestKey, KEY);
  assert.equal(f.calls[2].headers['X-CheckupAuto-Customer-CSRF'], DATA.csrf);
  assert.equal(f.calls[0].body.accepted, true);
  assert.equal(f.calls[0].body.immediatePerformance, false);
});

test('consent failure stops before any booking call', async () => {
  const f = fakeFetch({ [J.ROUTES.acceptTerms]: { status: 400, body: { ok: false } } });
  const result = await J.submitBooking({ fetchImpl: f.impl, data: DATA, requestKey: KEY });
  assert.equal(result.state, 'consent_error');
  assert.equal(f.calls.length, 1);
});

test('slot lost at preflight or create offers a repick, never a create', async () => {
  const a = fakeFetch({ [J.ROUTES.acceptTerms]: ok,
    [J.ROUTES.preflight]: { status: 422, body: { ok: false, error: 'booking_slot_unavailable' } } });
  const r1 = await J.submitBooking({ fetchImpl: a.impl, data: DATA, requestKey: KEY });
  assert.equal(r1.state, 'slot_lost');
  assert.ok(!a.calls.some(c => c.path === J.ROUTES.create));
  const b = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
    [J.ROUTES.create]: { status: 422, body: { ok: false, error: 'booking_slot_evidence_changed' } } });
  assert.equal((await J.submitBooking({ fetchImpl: b.impl, data: DATA, requestKey: KEY })).state, 'slot_lost');
});

test('server not qualified falls back to the delegated path without status lookup', async () => {
  for (const code of ['booking_provider_not_qualified', 'booking_writer_not_connected']) {
    const f = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
      [J.ROUTES.create]: { status: 503, body: { ok: false, error: code } } });
    const result = await J.submitBooking({ fetchImpl: f.impl, data: DATA, requestKey: KEY });
    assert.equal(result.state, 'fallback');
    assert.equal(result.reason, code);
    assert.equal(result.consentRecorded, true);
    assert.ok(!f.calls.some(c => c.path === J.ROUTES.status));
  }
});

test('preflight saying booking disabled falls back', async () => {
  const f = fakeFetch({ [J.ROUTES.acceptTerms]: ok,
    [J.ROUTES.preflight]: { status: 200, body: { ok: true, bookingEnabled: false, slotAvailableAtCheck: true } } });
  assert.equal((await J.submitBooking({ fetchImpl: f.impl, data: DATA, requestKey: KEY })).state, 'fallback');
});

test('uncertain create is checked by status: unknown key falls back, known key stays pending', async () => {
  const notFound = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
    [J.ROUTES.create]: 'network',
    [J.ROUTES.status]: { status: 400, body: { ok: false, error: 'booking_key_invalid' } } });
  const r1 = await J.submitBooking({ fetchImpl: notFound.impl, data: DATA, requestKey: KEY });
  assert.equal(r1.state, 'fallback');
  assert.equal(notFound.calls.at(-1).url, J.ROUTES.status + '?requestKey=' + KEY);

  const pending = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
    [J.ROUTES.create]: { status: 502, body: { ok: false, error: 'booking_create_failed' } },
    [J.ROUTES.status]: { status: 200, body: { ok: true, confirmed: false, state: 'reconciliation_required' } } });
  assert.equal((await J.submitBooking({ fetchImpl: pending.impl, data: DATA, requestKey: KEY })).state, 'pending');

  const unreachable = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
    [J.ROUTES.create]: 'network', [J.ROUTES.status]: 'network' });
  assert.equal((await J.submitBooking({ fetchImpl: unreachable.impl, data: DATA, requestKey: KEY })).state, 'pending');
});

test('reconciliation_required from create is pending (status polling)', async () => {
  const f = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: preflightReady,
    [J.ROUTES.create]: { status: 200, body: { ok: true, confirmed: false, state: 'reconciliation_required' } } });
  const r = await J.submitBooking({ fetchImpl: f.impl, data: DATA, requestKey: KEY });
  assert.deepEqual([r.state, r.reason], ['pending', 'reconciliation_required']);
});

test('immediate performance consent is sent only when required', async () => {
  const f = fakeFetch({ [J.ROUTES.acceptTerms]: ok, [J.ROUTES.preflight]: { status: 401, body: { ok: false, error: 'customer_auth_required' } } });
  const r = await J.submitBooking({ fetchImpl: f.impl, data: Object.assign({}, DATA, { requiresImmediatePerformance: true }), requestKey: KEY, immediate: true });
  assert.equal(r.state, 'auth');
  assert.equal(f.calls[0].body.immediatePerformance, true);
});

test('request key is reused per intent and regenerated when invalid', () => {
  const store = new Map();
  const storage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const first = J.requestKeyFor(storage, 'ccid-1', webcrypto);
  assert.match(first, /^[A-Za-z0-9_-]{20,128}$/);
  assert.equal(J.requestKeyFor(storage, 'ccid-1', webcrypto), first);
  assert.notEqual(J.requestKeyFor(storage, 'ccid-2', webcrypto), first);
  store.set('checkupauto.booking.key.ccid-3', 'bad key');
  assert.match(J.requestKeyFor(storage, 'ccid-3', webcrypto), /^[A-Za-z0-9_-]{20,128}$/);
  const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.match(J.requestKeyFor(broken, 'x', webcrypto), /^[A-Za-z0-9_-]{20,128}$/);
});

test('"Autres modèles" is hidden unless enabled', () => {
  const models = [{ id: '1', label: 'Clio' }, { id: '2', label: 'Autres Modèles' }, { id: 3, label: 'bad' }];
  assert.deepEqual(J.filterModels(models, false).map(m => m.id), ['1']);
  assert.deepEqual(J.filterModels(models, true).map(m => m.id), ['1', '2']);
  assert.ok(J.isGenericModel('AUTRES   MODELES'));
});

test('status classification and formatting', () => {
  assert.equal(J.classifyStatus(200, { ok: true, confirmed: true }).state, 'confirmed');
  assert.equal(J.classifyStatus(200, { ok: true, confirmed: false }).state, 'pending');
  assert.equal(J.classifyStatus(400, { error: 'booking_key_invalid' }).state, 'not_found');
  assert.equal(J.classifyStatus(401, null).state, 'auth');
  assert.equal(J.classifyStatus(500, null).state, 'unknown');
  assert.equal(J.classifyCreate(429, null).state, 'verify');
  assert.equal(J.classifyCreate(403, { error: 'same_origin_required' }).state, 'fallback');
  assert.equal(J.formatPrice(7200), '72 € TTC');
  assert.match(J.formatPrice(7250), /^72,50 € TTC$/);
  assert.equal(J.formatPrice(null), '');
  assert.match(J.formatDate('2026-12-15'), /15 décembre 2026/);
});
