/* Parcours de réservation sur le site Checkup Auto.
 * Chargé uniquement par les pages rendues quand le serveur a choisi le parcours
 * sur site (interrupteur désactivé par défaut). Toute issue incertaine est
 * vérifiée auprès du serveur avant de proposer la plateforme Mercure, pour ne
 * jamais créer de doublon. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CheckupAutoBookingJourney = api;
  if (typeof document !== 'undefined' && typeof window !== 'undefined' && document.getElementById('bookingJourneyData')) {
    const start = () => api.boot(document, window);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const ROUTES = {
    acceptTerms: '/api/booking/accept-terms',
    preflight: '/api/customer/booking/preflight',
    create: '/api/customer/booking/create',
    status: '/api/customer/booking/status',
    mapping: '/api/customer/booking/vehicle-mapping',
    references: '/api/customer/vehicle-references'
  };
  const SLOT_ERRORS = new Set([
    'booking_slot_unavailable', 'booking_slot_ambiguous', 'booking_slot_evidence_changed',
    'booking_fresh_slot_evidence_missing', 'booking_date_invalid', 'booking_time_invalid'
  ]);
  const VEHICLE_ERRORS = new Set(['booking_vehicle_incomplete', 'booking_vehicle_not_owned']);
  // Refusals raised before any provider write: falling back to Mercure is safe.
  const SAFE_UNAVAILABLE = new Set([
    'booking_provider_not_qualified', 'booking_writer_not_qualified',
    'booking_writer_not_connected', 'booking_provider_context_unqualified'
  ]);
  const GENERIC_MODELS = new Set(['autres modeles', 'autre modele']);

  function fold(value) {
    return String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().trim().replace(/\s+/g, ' ');
  }
  function isGenericModel(label) { return GENERIC_MODELS.has(fold(label)); }
  function filterModels(models, allowGeneric) {
    return (Array.isArray(models) ? models : []).filter(item => item && typeof item.id === 'string'
      && typeof item.label === 'string' && (allowGeneric === true || !isGenericModel(item.label)));
  }

  function newRequestKey(cryptoObj) {
    const bytes = new Uint8Array(24);
    cryptoObj.getRandomValues(bytes);
    let raw = '';
    bytes.forEach(b => { raw += String.fromCharCode(b); });
    const b64 = typeof btoa === 'function' ? btoa(raw) : Buffer.from(raw, 'binary').toString('base64');
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  /* Une seule clé d'idempotence par intention : un nouvel essai ou un
   * rechargement réutilise la même clé, le serveur ne crée donc pas de doublon. */
  function requestKeyFor(storage, ccid, cryptoObj) {
    const name = 'checkupauto.booking.key.' + ccid;
    let key = '';
    try { key = storage.getItem(name) || ''; } catch (_e) { key = ''; }
    if (!/^[A-Za-z0-9_-]{20,128}$/.test(key)) {
      key = newRequestKey(cryptoObj);
      try { storage.setItem(name, key); } catch (_e) { /* stockage indisponible : clé de page */ }
    }
    return key;
  }

  function errorCode(body) { return body && typeof body.error === 'string' ? body.error : ''; }

  function classifyPreflight(status, body) {
    if (status === 200 && body && body.ok === true) {
      if (body.bookingEnabled === true && body.slotAvailableAtCheck === true) {
        return { state: 'ready', priceCents: body.priceCents };
      }
      return { state: 'fallback', reason: 'booking_not_enabled' };
    }
    const code = errorCode(body) || (status === 0 ? 'network' : 'http_' + status);
    if (status === 401) return { state: 'auth', reason: code };
    if (SLOT_ERRORS.has(code)) return { state: 'slot_lost', reason: code };
    if (VEHICLE_ERRORS.has(code)) return { state: 'vehicle', reason: code };
    return { state: 'fallback', reason: code };
  }

  function classifyCreate(status, body) {
    if (status === 200 && body && body.ok === true) {
      if (body.confirmed === true && body.state === 'confirmed') return { state: 'confirmed' };
      return { state: 'pending', reason: String(body.state || 'reconciliation_required') };
    }
    const code = errorCode(body);
    if (status === 401) return { state: 'auth', reason: code || 'customer_auth_required' };
    if (status === 422 && SLOT_ERRORS.has(code)) return { state: 'slot_lost', reason: code };
    if (status === 422 && VEHICLE_ERRORS.has(code)) return { state: 'vehicle', reason: code };
    if (status === 422 || status === 403 || status === 400) return { state: 'fallback', reason: code || 'http_' + status };
    if (status === 503 && SAFE_UNAVAILABLE.has(code)) return { state: 'fallback', reason: code };
    // Réseau coupé, délai dépassé, 5xx générique, 429 : issue incertaine.
    return { state: 'verify', reason: code || (status === 0 ? 'network' : 'http_' + status) };
  }

  function classifyStatus(status, body) {
    if (status === 200 && body && body.ok === true) {
      if (body.confirmed === true) {
        return { state: 'confirmed', message: body.message || '', paymentMessage: body.paymentMessage || '' };
      }
      return { state: 'pending', message: body.message || '' };
    }
    if (status === 400 && errorCode(body) === 'booking_key_invalid') return { state: 'not_found' };
    if (status === 401) return { state: 'auth' };
    return { state: 'unknown' };
  }

  async function fetchJson(fetchImpl, url, options) {
    try {
      const response = await fetchImpl(url, Object.assign({ credentials: 'same-origin', cache: 'no-store' }, options || {}));
      let body = null;
      try { body = await response.json(); } catch (_e) { body = null; }
      return { status: response.status, body };
    } catch (_e) {
      return { status: 0, body: null };
    }
  }

  function jsonPost(csrf) {
    const headers = { 'Content-Type': 'application/json' };
    if (csrf) headers['X-CheckupAuto-Customer-CSRF'] = csrf;
    return body => ({ method: 'POST', headers, body: JSON.stringify(body) });
  }

  async function recordConsent({ fetchImpl, data, immediate }) {
    const result = await fetchJson(fetchImpl, ROUTES.acceptTerms, jsonPost('')({
      ccid: data.ccid, cct: data.cct, termsVersion: data.termsVersion,
      termsContentHash: data.termsContentHash, accepted: true, reviewed: true,
      immediatePerformance: data.requiresImmediatePerformance ? immediate === true : false
    }));
    return result.status >= 200 && result.status < 300;
  }

  /* Enchaînement : preuve d'acceptation des CGV, puis vérification du créneau,
   * puis création unique. Renvoie l'état final à afficher. */
  async function submitBooking({ fetchImpl, data, requestKey, immediate, onStep }) {
    const step = typeof onStep === 'function' ? onStep : () => {};
    const post = jsonPost(data.csrf);
    step('consent');
    if (!(await recordConsent({ fetchImpl, data, immediate }))) {
      return { state: 'consent_error', consentRecorded: false };
    }
    const slot = { service: data.service, date: data.date, time: data.time, vehicleId: data.vehicleId };
    step('preflight');
    const pre = await fetchJson(fetchImpl, ROUTES.preflight, post(slot));
    const preflight = classifyPreflight(pre.status, pre.body);
    if (preflight.state !== 'ready') return Object.assign({ consentRecorded: true }, preflight);
    step('create');
    const created = await fetchJson(fetchImpl, ROUTES.create, post(Object.assign({}, slot, { requestKey })));
    const outcome = classifyCreate(created.status, created.body);
    if (outcome.state !== 'verify') {
      return Object.assign({ consentRecorded: true, requestKey, priceCents: preflight.priceCents }, outcome);
    }
    step('verify');
    const check = await fetchJson(fetchImpl, ROUTES.status + '?requestKey=' + encodeURIComponent(requestKey));
    const known = classifyStatus(check.status, check.body);
    if (known.state === 'not_found') {
      // Aucune trace côté serveur : aucune écriture Mercure n'a été tentée.
      return { state: 'fallback', reason: 'create_not_recorded:' + outcome.reason, consentRecorded: true, requestKey };
    }
    if (known.state === 'confirmed') return { state: 'confirmed', consentRecorded: true, requestKey };
    return { state: 'pending', reason: outcome.reason, consentRecorded: true, requestKey };
  }

  function formatDate(iso) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    if (!match) return String(iso || '');
    const date = new Date(Date.UTC(+match[1], +match[2] - 1, +match[3], 12));
    try {
      return new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date);
    } catch (_e) { return match[3] + '/' + match[2] + '/' + match[1]; }
  }
  function formatPrice(cents) {
    if (typeof cents !== 'number' || !isFinite(cents)) return '';
    return (cents / 100).toLocaleString('fr-FR', { minimumFractionDigits: cents % 100 ? 2 : 0, maximumFractionDigits: 2 }) + ' € TTC';
  }

  /* ---------- Interface ---------- */
  function boot(doc, win) {
    let data;
    try { data = JSON.parse(doc.getElementById('bookingJourneyData').textContent); } catch (_e) { return; }
    if (data.mode === 'status') return bootStatus(doc, win, data);
    return bootSummary(doc, win, data);
  }

  function show(el, visible) { if (el) el.hidden = !visible; }
  function focusPanel(el) {
    if (!el) return;
    el.hidden = false;
    const heading = el.querySelector('h2') || el;
    heading.setAttribute('tabindex', '-1');
    heading.focus();
  }

  function bootSummary(doc, win, data) {
    const $ = id => doc.getElementById(id);
    const fetchImpl = win.fetch.bind(win);
    const terms = $('bjTerms'), immediate = $('bjImmediate'), confirm = $('bjConfirm'), status = $('bjStatus');
    const fallbackForm = $('bjFallbackForm');
    const panels = { slot: $('bjSlotLost'), failure: $('bjFailure'), auth: $('bjAuth') };
    const vehicleStatus = $('bjVehicleStatus'), picker = $('bjVehiclePicker');
    const brand = $('bjBrand'), model = $('bjModel'), energy = $('bjEnergy'), applyVehicle = $('bjVehicleApply');
    const state = { vehicleVerified: false, busy: false, consentRecorded: false, allowGeneric: false };
    const storage = win.sessionStorage;
    const requestKey = requestKeyFor(storage, data.ccid, win.crypto);

    const consentsOk = () => terms.checked && (!data.requiresImmediatePerformance || (immediate && immediate.checked));
    const sync = () => {
      confirm.disabled = state.busy || !state.vehicleVerified || !data.billingComplete || !consentsOk();
    };
    terms.addEventListener('change', sync);
    if (immediate && immediate.type === 'checkbox') immediate.addEventListener('change', sync);

    const setOptions = (select, rows, placeholder) => {
      select.textContent = '';
      const first = doc.createElement('option');
      first.value = ''; first.textContent = placeholder; select.appendChild(first);
      rows.forEach(row => { const o = doc.createElement('option'); o.value = row.id; o.textContent = row.label; select.appendChild(o); });
    };
    const syncPicker = () => { applyVehicle.disabled = !(brand.value && model.value && energy.value); };

    async function openPicker() {
      show(picker, true);
      const refs = await fetchJson(fetchImpl, ROUTES.references);
      if (refs.status !== 200 || !refs.body || refs.body.ok !== true) {
        vehicleStatus.textContent = 'Les listes de véhicules Mercure sont indisponibles. Vous pouvez poursuivre sur la plateforme Mercure.';
        showFailure('vehicle_reference_unavailable');
        return;
      }
      setOptions(brand, refs.body.brands || [], 'Choisir la marque');
      setOptions(energy, refs.body.energies || [], 'Choisir l’énergie');
      setOptions(model, [], 'Choisir d’abord la marque');
      syncPicker();
    }
    brand.addEventListener('change', async () => {
      setOptions(model, [], brand.value ? 'Chargement des modèles…' : 'Choisir d’abord la marque');
      syncPicker();
      if (!brand.value) return;
      const wanted = brand.value;
      const res = await fetchJson(fetchImpl, ROUTES.references + '?brandId=' + encodeURIComponent(wanted));
      if (brand.value !== wanted) return;
      const rows = res.status === 200 && res.body ? filterModels(res.body.models, state.allowGeneric) : [];
      setOptions(model, rows, rows.length ? 'Choisir le modèle' : 'Aucun modèle disponible');
      syncPicker();
    });
    model.addEventListener('change', syncPicker);
    energy.addEventListener('change', syncPicker);
    applyVehicle.addEventListener('click', async () => {
      applyVehicle.disabled = true;
      vehicleStatus.textContent = 'Enregistrement du véhicule…';
      const res = await fetchJson(fetchImpl, ROUTES.mapping, jsonPost(data.csrf)({
        vehicleId: data.vehicleId, brandId: brand.value, modelId: model.value, energyId: energy.value }));
      if (res.status === 200 && res.body && res.body.verified === true) {
        state.vehicleVerified = true;
        show(picker, false);
        vehicleStatus.textContent = 'Véhicule reconnu par le centre : ' + [brand, model, energy]
          .map(s => s.options[s.selectedIndex].textContent).join(' · ');
      } else {
        vehicleStatus.textContent = 'Ce choix n’a pas pu être validé. Vérifiez la marque, le modèle et l’énergie.';
        syncPicker();
      }
      sync();
    });

    async function checkVehicle() {
      vehicleStatus.textContent = 'Vérification du véhicule auprès du centre…';
      const res = await fetchJson(fetchImpl, ROUTES.mapping + '?vehicleId=' + encodeURIComponent(data.vehicleId));
      if (res.status === 200 && res.body && res.body.ok === true) {
        state.allowGeneric = res.body.genericModelAllowed === true;
        if (res.body.verified === true) {
          state.vehicleVerified = true;
          vehicleStatus.textContent = 'Véhicule reconnu par le centre.';
        } else {
          vehicleStatus.textContent = 'Le centre ne reconnaît pas exactement ce modèle. Sélectionnez-le dans la liste du centre.';
          await openPicker();
        }
      } else {
        vehicleStatus.textContent = 'Vérification du véhicule indisponible.';
        showFailure('vehicle_check_unavailable');
      }
      sync();
    }

    function hidePanels() { Object.values(panels).forEach(p => show(p, false)); }
    function showFailure(reason) {
      const detail = $('bjFailureReason');
      if (detail) detail.textContent = reason ? 'Code : ' + reason : '';
      focusPanel(panels.failure);
    }

    $('bjFallback').addEventListener('click', async () => {
      const error = $('bjFallbackError');
      error.textContent = '';
      if (!state.consentRecorded) {
        if (!consentsOk()) { error.textContent = 'Cochez les conditions ci-dessus pour poursuivre sur la plateforme Mercure.'; terms.focus(); return; }
        if (!(await recordConsent({ fetchImpl, data, immediate: immediate && immediate.checked }))) {
          error.textContent = 'Impossible d’enregistrer votre acceptation. Réessayez.'; return;
        }
        state.consentRecorded = true;
      }
      fallbackForm.submit();
    });

    const stepText = {
      consent: 'Enregistrement de votre acceptation…',
      preflight: 'Vérification du créneau auprès du centre…',
      create: 'Création du rendez-vous… ne fermez pas cette page.',
      verify: 'Vérification de l’état de votre demande…'
    };
    doc.getElementById('bjForm').addEventListener('submit', async event => {
      event.preventDefault();
      if (confirm.disabled) return;
      state.busy = true; sync(); hidePanels();
      const result = await submitBooking({
        fetchImpl, data, requestKey, immediate: immediate && immediate.checked,
        onStep: name => { status.textContent = stepText[name] || ''; }
      });
      state.consentRecorded = state.consentRecorded || result.consentRecorded === true;
      if (result.state === 'confirmed' || result.state === 'pending') {
        try {
          storage.setItem('checkupauto.booking.summary.' + requestKey, JSON.stringify({
            service: data.serviceLabel, date: data.date, time: data.time, vehicle: data.vehicleLabel,
            price: result.priceCents }));
        } catch (_e) { /* affichage minimal */ }
        status.textContent = result.state === 'confirmed' ? 'Rendez-vous confirmé.' : 'Vérification en cours…';
        win.location.assign(data.confirmationUrl + '?cle=' + encodeURIComponent(requestKey));
        return;
      }
      state.busy = false;
      status.textContent = '';
      if (result.state === 'slot_lost') focusPanel(panels.slot);
      else if (result.state === 'auth') focusPanel(panels.auth);
      else if (result.state === 'vehicle') { state.vehicleVerified = false; await openPicker(); }
      else if (result.state === 'consent_error') status.textContent = 'Impossible d’enregistrer votre acceptation. Réessayez.';
      else showFailure(result.reason);
      sync();
    });

    const price = $('bjPrice');
    if (price && typeof data.quoteCents === 'number') price.textContent = formatPrice(data.quoteCents);
    sync();
    checkVehicle();
  }

  function bootStatus(doc, win, data) {
    const $ = id => doc.getElementById(id);
    const fetchImpl = win.fetch.bind(win);
    const title = $('bjStatusTitle'), text = $('bjStatusText'), details = $('bjStatusDetails'), payment = $('bjStatusPayment');
    let summary = null;
    try { summary = JSON.parse(win.sessionStorage.getItem('checkupauto.booking.summary.' + data.requestKey) || 'null'); } catch (_e) { summary = null; }
    if (summary && details) {
      const rows = [['Prestation', summary.service], ['Date', formatDate(summary.date)], ['Heure', summary.time],
        ['Véhicule', summary.vehicle], ['Tarif', formatPrice(summary.price)]].filter(r => r[1]);
      details.textContent = '';
      rows.forEach(([label, value]) => {
        const dt = doc.createElement('dt'); dt.textContent = label;
        const dd = doc.createElement('dd'); dd.textContent = value;
        details.append(dt, dd);
      });
      details.hidden = false;
    }
    let attempts = 0;
    const maxAttempts = Number(data.maxPolls) > 0 ? Number(data.maxPolls) : 24;
    async function poll() {
      attempts += 1;
      const res = await fetchJson(fetchImpl, '/api/customer/booking/status?requestKey=' + encodeURIComponent(data.requestKey));
      const result = classifyStatus(res.status, res.body);
      if (result.state === 'confirmed') {
        title.textContent = 'Votre rendez-vous est confirmé.';
        text.textContent = 'Le centre a enregistré votre rendez-vous. Conservez cette page.';
        if (payment) { payment.textContent = result.paymentMessage; payment.hidden = !result.paymentMessage; }
        doc.body.dataset.bookingState = 'confirmed';
        return;
      }
      if (result.state === 'not_found') {
        title.textContent = 'Aucune réservation enregistrée pour cette demande.';
        text.textContent = 'Votre demande n’a pas été transmise au centre. Vous pouvez choisir à nouveau un créneau.';
        show($('bjStatusRestart'), true);
        doc.body.dataset.bookingState = 'not_found';
        return;
      }
      if (result.state === 'auth') {
        title.textContent = 'Connectez-vous pour consulter cette réservation.';
        text.textContent = '';
        show($('bjStatusLogin'), true);
        return;
      }
      title.textContent = 'Vérification de votre rendez-vous en cours.';
      text.textContent = 'Le centre confirme votre réservation. Ne relancez pas de nouvelle réservation : cela pourrait créer un doublon.';
      doc.body.dataset.bookingState = 'pending';
      if (attempts < maxAttempts) { win.setTimeout(poll, Number(data.pollMs) > 0 ? Number(data.pollMs) : 5000); return; }
      text.textContent = 'La vérification prend plus de temps que prévu. Revenez sur cette page plus tard ou appelez le centre ; ne relancez pas de réservation.';
      show($('bjStatusCall'), true);
    }
    poll();
  }

  return {
    ROUTES, fold, isGenericModel, filterModels, newRequestKey, requestKeyFor,
    classifyPreflight, classifyCreate, classifyStatus, fetchJson, submitBooking,
    recordConsent, formatDate, formatPrice, boot
  };
});
