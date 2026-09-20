const notificationEl = id => document.getElementById(id);
const permanentRecipientStates = new Map();
let lastPermanentFailures = [];

function notificationCell(row, value) {
  const cell = document.createElement('td');
  cell.textContent = value == null || value === '' ? '—' : String(value);
  row.appendChild(cell);
}

function renderTransportHealth(items) {
  const body = notificationEl('notificationTransportHealth');
  if (!body) return;
  body.replaceChildren();
  if (!items.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.textContent = 'Aucun incident transport';
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }
  for (const item of items) {
    const row = document.createElement('tr');
    notificationCell(row, item.transport);
    notificationCell(row, item.circuitOpen ? 'OUVERT' : 'FERMÉ');
    notificationCell(row, Number(item.consecutiveFailures) || 0);
    notificationCell(row, Number(item.transientFailures) || 0);
    notificationCell(row, Number(item.configurationFailures) || 0);
    notificationCell(row, item.circuitOpen ? `${Number(item.retryAfterSeconds) || 0} s` : '—');
    body.appendChild(row);
  }
}

function renderPreflight(items) {
  const body = notificationEl('notificationPreflightRows');
  if (!body) return;
  body.replaceChildren();
  if (!items.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.textContent = 'Aucun diagnostic disponible';
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }
  for (const item of items) {
    const row = document.createElement('tr');
    notificationCell(row, item.transport);
    notificationCell(row, item.ready ? 'PRÊT' : String(item.state || 'INDISPONIBLE').toUpperCase());
    notificationCell(row, item.reason || item.failureClass || '—');
    notificationCell(row, Number(item.status) || '—');
    body.appendChild(row);
  }
}

function renderNotificationRows(items) {
  const body = notificationEl('notificationRecent');
  if (!body) return;
  body.replaceChildren();
  if (!items.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.textContent = 'Aucune livraison enregistrée';
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }
  for (const item of items) {
    const row = document.createElement('tr');
    notificationCell(row, item.channel);
    notificationCell(row, item.category);
    notificationCell(row, item.reference);
    notificationCell(row, item.status);
    notificationCell(row, item.attempts);
    notificationCell(row, item.sent_at || item.last_attempt_at || item.created_at);
    body.appendChild(row);
  }
}

function permanentRecipientLabel(state) {
  const labels = {
    unchanged: 'INCHANGÉ',
    changed: 'CORRIGÉ',
    missing: 'ABSENT',
    lookup_failed: 'MERCURE INDISPONIBLE',
    recipient_lookup_failed: 'MERCURE INDISPONIBLE',
    recipient_unchanged: 'INCHANGÉ',
    waiting_email_preflight: 'CORRIGÉ · EMAIL NON PRÊT',
    email_preflight_failed: 'CORRIGÉ · PRÉFLIGHT INDISPONIBLE',
    retry_deferred: 'CORRIGÉ · RETRY DIFFÉRÉ',
    retry_in_flight: 'CORRIGÉ · RETRY EN COURS',
  };
  return labels[state] || 'NON VÉRIFIÉ';
}

function renderPermanentFailures(items) {
  lastPermanentFailures = Array.isArray(items) ? items : [];
  const body = notificationEl('notificationPermanentRows');
  if (!body) return;
  body.replaceChildren();
  if (!lastPermanentFailures.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 8;
    cell.textContent = 'Aucun échec permanent enregistré';
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }
  for (const item of lastPermanentFailures) {
    const row = document.createElement('tr');
    notificationCell(row, item.channel);
    notificationCell(row, item.category);
    notificationCell(row, item.reference);
    notificationCell(row, item.permanent_state || 'open');
    const recipientCell = document.createElement('td');
    const incidentId = String(item.incident_id || '');
    const recipientState = permanentRecipientStates.get(incidentId) || item.recipient_check_state || '';
    const recipientLabel = document.createElement('span');
    recipientLabel.textContent = permanentRecipientLabel(recipientState);
    if (item.recipient_checked_at) recipientLabel.title = `Dernière vérification ${item.recipient_checked_at}`;
    recipientCell.appendChild(recipientLabel);
    if ((item.permanent_state === 'open' || item.permanent_state === 'acknowledged') &&
        item.channel === 'email' && item.category === 'ct_due_reminder' && incidentId) {
      const check = document.createElement('button');
      check.type = 'button';
      check.className = 'secondary';
      check.dataset.recipientCheck = incidentId;
      check.textContent = 'Vérifier';
      recipientCell.appendChild(document.createTextNode(' '));
      recipientCell.appendChild(check);
      if (recipientState === 'changed' || recipientState === 'waiting_email_preflight' || recipientState === 'email_preflight_failed' || recipientState === 'retry_deferred' || recipientState === 'retry_in_flight') {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'secondary';
        retry.dataset.recipientRetry = incidentId;
        retry.textContent = 'Retenter';
        recipientCell.appendChild(document.createTextNode(' '));
        recipientCell.appendChild(retry);
      }
    }
    row.appendChild(recipientCell);
    notificationCell(row, item.last_error || '—');
    notificationCell(row, item.permanent_state_at || item.last_attempt_at || '—');
    const actionCell = document.createElement('td');
    if (item.permanent_state === 'open' || item.permanent_state === 'acknowledged') {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.dataset.incidentId = incidentId;
      button.dataset.permanentAction = item.permanent_state === 'open' ? 'acknowledge' : 'reopen';
      button.textContent = item.permanent_state === 'open' ? 'Acquitter' : 'Réouvrir';
      button.disabled = !incidentId;
      actionCell.appendChild(button);
    } else {
      actionCell.textContent = item.permanent_resolution === 'superseded_by_success' ? 'Réconcilié par succès' : '—';
    }
    row.appendChild(actionCell);
    body.appendChild(row);
  }
}

async function loadNotificationStatus() {
  const state = notificationEl('notificationState');
  try {
    const [brokerResponse, reminderResponse, devicesResponse, appResponse] = await Promise.all([
      fetch('/api/admin/notifications/status?limit=20', { cache: 'no-store' }),
      fetch('/api/admin/reminders/status', { cache: 'no-store' }),
      fetch('/api/admin/mobile/devices/status', { cache: 'no-store' }),
      fetch('/api/app/status', { cache: 'no-store' }),
    ]);
    const data = await brokerResponse.json();
    const reminder = await reminderResponse.json();
    const devices = await devicesResponse.json();
    const appStatus = await appResponse.json();
    if (!brokerResponse.ok || data.ok === false) throw new Error(data.error || 'Statut indisponible');
    if (!reminderResponse.ok || reminder.ok === false) throw new Error(reminder.error || 'Relances indisponibles');
    if (!devicesResponse.ok || devices.ok === false) throw new Error(devices.error || 'Appareils iOS indisponibles');
    if (!appResponse.ok) throw new Error('Distribution iOS indisponible');
    const counts = data.counts || {};
    notificationEl('notificationSent').textContent = counts.sent || 0;
    notificationEl('notificationFailed').textContent = counts.failed || 0;
    notificationEl('notificationDeferred').textContent = counts.deferred || 0;
    notificationEl('notificationDelivering').textContent = counts.delivering || 0;
    const resilience=data.resilience||{};
    const transportHealth=Array.isArray(resilience.transports)?resilience.transports:[];
    notificationEl('notificationTransient').textContent = transportHealth.reduce((sum,item)=>sum+(Number(item.transientFailures)||0),0);
    notificationEl('notificationPermanent').textContent = resilience.permanentFailures || 0;
    notificationEl('notificationPermanentAcknowledged').textContent = resilience.permanentAcknowledged || 0;
    notificationEl('notificationPermanentResolved').textContent = resilience.permanentResolved || 0;
    notificationEl('notificationConfigErrors').textContent = transportHealth.reduce((sum,item)=>sum+(Number(item.configurationFailures)||0),0);
    notificationEl('notificationCircuits').textContent = resilience.circuitsOpen || 0;
    renderTransportHealth(transportHealth);
    const emailChannel=data.channels?.email||{};
    const emailTransport=emailChannel.transport==='gmail-api'?'GMAIL':emailChannel.transport==='smtp-relay'?'SMTP':'';
    notificationEl('notificationEmail').textContent = emailChannel.configured ? `PRÊT${emailTransport?' · '+emailTransport:''}` : 'À CONFIGURER';
    const pushChannel=data.channels?.push||{};
    const mobileDispatch=devices.reminderDispatch||{};
    notificationEl('notificationPush').textContent = !pushChannel.configured ? 'À CONFIGURER' : mobileDispatch.active ? 'ACTIF' : 'PRÊT · INACTIF';
    const distributionChannel=appStatus.ios?.channel||'pending';
    notificationEl('notificationAppDistribution').textContent = distributionChannel==='app-store' ? 'APP STORE' : distributionChannel==='testflight' ? 'TESTFLIGHT' : 'EN PRÉPARATION';
    const claimDelivery=devices.claimDelivery||{};
    notificationEl('notificationClaimDelivery').textContent = claimDelivery.ready ? 'PRÊT' : 'À CONFIGURER';
    notificationEl('notificationDevices').textContent = devices.active || 0;
    const retiredByReason=devices.disabledByReason||{};
    notificationEl('notificationDevicesRetired').textContent = Object.values(retiredByReason).reduce((sum,value)=>sum+(Number(value)||0),0);
    notificationEl('notificationMobileDeadlines').textContent = devices.deadlines || 0;
    notificationEl('notificationReminderInventory').textContent = reminder.inventory || 0;
    notificationEl('notificationReminderDue').textContent = reminder.eligibleNow || 0;
    notificationEl('notificationReminderPermanentSuppressed').textContent = Number(reminder.lastProcess?.permanentSuppressed) || 0;
    notificationEl('notificationReminderBackfill').textContent = reminder.backfillComplete ? 'COMPLET' : 'EN COURS';
    const reminderState = notificationEl('notificationReminderState');
    if (reminderState) {
      const parts = [`Mercure ${reminder.sessionConnected ? 'connecté' : 'déconnecté'}`,
        `email ${reminder.emailTransportConfigured ? 'prêt' : 'à configurer'}`,
        `push mobile ${mobileDispatch.active ? 'actif' : mobileDispatch.enabled ? 'en attente APNs' : 'inactif'}`,
        `J-${(reminder.leadDays || []).join(' / J-')}`];
      reminderState.textContent = parts.join(' · ');
    }
    if (state) {
      state.textContent = 'Broker opérationnel';
      state.className = 'gsc-status online';
    }
    renderPermanentFailures(Array.isArray(data.permanentFailures) ? data.permanentFailures : []);
    renderNotificationRows(data.recent || []);
  } catch (error) {
    if (state) {
      state.textContent = 'Erreur';
      state.className = 'gsc-status offline';
    }
  }
}

function renderClaimCandidates(items, delivery) {
  const select = notificationEl('claimVehicleSelect');
  const issue = notificationEl('claimIssue');
  const state = notificationEl('claimDeliveryState');
  if (!select || !issue || !state) return;
  select.replaceChildren();
  const ready = Boolean(delivery?.ready);
  if (!ready) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Configuration Apple requise';
    select.appendChild(option);
    select.disabled = true;
    issue.disabled = true;
    state.textContent = delivery?.appIdentifierPrefixPresent
      ? 'Associated Domains indisponible.'
      : 'Préfixe d’identifiant d’app Apple requis avant émission d’un QR client.';
    return;
  }
  select.disabled = false;
  for (const item of items) {
    const option = document.createElement('option');
    option.value = String(item.vehicleId || '');
    const rdv = item.appointmentId ? `RDV ${item.appointmentId}` : 'véhicule Mercure';
    option.textContent = `${rdv} · échéance ${item.dueDate || '—'} · ${item.vehicleId || '—'}`;
    select.appendChild(option);
  }
  issue.disabled = items.length === 0;
  state.textContent = items.length
    ? `Associated Domains prêt · ${items.length} véhicule(s) récent(s)`
    : 'Associated Domains prêt · aucun véhicule éligible.';
}

async function loadClaimCandidates() {
  const state = notificationEl('claimDeliveryState');
  try {
    const response = await fetch('/api/admin/mobile/claims/candidates?limit=30', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Claims indisponibles');
    renderClaimCandidates(Array.isArray(data.candidates) ? data.candidates : [], data.claimDelivery || {});
  } catch {
    if (state) state.textContent = 'Inventaire de rattachement indisponible.';
    renderClaimCandidates([], {});
  }
}

async function issueVehicleClaim() {
  const select = notificationEl('claimVehicleSelect');
  const button = notificationEl('claimIssue');
  const state = notificationEl('claimDeliveryState');
  const panel = notificationEl('claimQrPanel');
  const image = notificationEl('claimQrImage');
  const expiry = notificationEl('claimExpiry');
  const vehicleId = String(select?.value || '');
  if (!vehicleId) return;
  if (button) button.disabled = true;
  if (panel) panel.hidden = true;
  if (state) state.textContent = 'Génération du QR à usage unique…';
  try {
    const response = await fetch('/api/admin/mobile/claims/issue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vehicleId, ttlSeconds: 1800 }),
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Génération impossible');
    const claim = data.claim || {};
    if (!String(claim.qrDataUrl || '').startsWith('data:image/svg+xml;base64,')) {
      throw new Error('QR invalide');
    }
    if (image) image.src = claim.qrDataUrl;
    if (expiry) expiry.textContent = `Véhicule ${claim.vehicleId || '—'} · échéance ${claim.dueDate || '—'} · expire ${claim.expiresAt || '—'}`;
    if (panel) panel.hidden = false;
    if (state) state.textContent = 'QR généré localement · usage unique · valable 30 minutes.';
  } catch {
    if (state) state.textContent = 'Impossible de générer le QR de rattachement.';
  } finally {
    if (button) button.disabled = false;
  }
}

async function runNotificationPreflight() {
  const button = notificationEl('notificationPreflight');
  const state = notificationEl('notificationPreflightState');
  if (button) button.disabled = true;
  if (state) state.textContent = 'Diagnostic en cours…';
  try {
    const response = await fetch('/api/admin/notifications/preflight', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Préflight indisponible');
    renderPreflight(Array.isArray(data.transports) ? data.transports : []);
    if (state) state.textContent = `Vérifié ${data.checkedAt || ''} · aucun envoi effectué`;
  } catch (error) {
    if (state) state.textContent = 'Diagnostic impossible';
    renderPreflight([]);
  } finally {
    if (button) button.disabled = false;
  }
}

async function checkPermanentRecipient(incidentId) {
  const response = await fetch('/api/admin/notifications/permanent/recipient-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ incidentId }),
  });
  const data = await response.json();
  const state = String(data.recipientState || data.error || 'lookup_failed');
  permanentRecipientStates.set(incidentId, state);
  renderPermanentFailures(lastPermanentFailures);
  if (!response.ok && !data.recipientState) throw new Error(data.error || 'Vérification impossible');
  return data;
}

async function retryPermanentRecipient(incidentId) {
  const response = await fetch('/api/admin/notifications/permanent/retry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ incidentId }),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    permanentRecipientStates.set(incidentId, String(data.state || data.error || 'retry_blocked'));
    renderPermanentFailures(lastPermanentFailures);
    return data;
  }
  permanentRecipientStates.delete(incidentId);
  await loadNotificationStatus();
  return data;
}

async function updatePermanentFailure(incidentId, action) {
  const response = await fetch('/api/admin/notifications/permanent/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ incidentId, action }),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || 'Action impossible');
  await loadNotificationStatus();
}

async function processRemindersNow() {
  const button = notificationEl('reminderProcess');
  if (button) button.disabled = true;
  try {
    const response = await fetch('/api/admin/reminders/process', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || data.state || 'Synchronisation impossible');
    await loadNotificationStatus();
  } finally {
    if (button) button.disabled = false;
  }
}

notificationEl('notificationPermanentRows')?.addEventListener('click', async event => {
  const action = event.target.closest('button[data-permanent-action]');
  const check = event.target.closest('button[data-recipient-check]');
  const retry = event.target.closest('button[data-recipient-retry]');
  const button = action || check || retry;
  if (!button) return;
  button.disabled = true;
  try {
    if (check) await checkPermanentRecipient(check.dataset.recipientCheck || '');
    else if (retry) await retryPermanentRecipient(retry.dataset.recipientRetry || '');
    else await updatePermanentFailure(action.dataset.incidentId || '', action.dataset.permanentAction || '');
  } finally {
    button.disabled = false;
  }
});
notificationEl('notificationRefresh')?.addEventListener('click', loadNotificationStatus);
notificationEl('notificationPreflight')?.addEventListener('click', runNotificationPreflight);
notificationEl('reminderProcess')?.addEventListener('click', processRemindersNow);
notificationEl('claimRefresh')?.addEventListener('click', loadClaimCandidates);
notificationEl('claimIssue')?.addEventListener('click', issueVehicleClaim);
loadNotificationStatus();
loadClaimCandidates();
