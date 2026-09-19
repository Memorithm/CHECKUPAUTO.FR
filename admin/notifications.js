const notificationEl = id => document.getElementById(id);

function notificationCell(row, value) {
  const cell = document.createElement('td');
  cell.textContent = value == null || value === '' ? '—' : String(value);
  row.appendChild(cell);
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

async function loadNotificationStatus() {
  const state = notificationEl('notificationState');
  try {
    const [brokerResponse, reminderResponse] = await Promise.all([
      fetch('/api/admin/notifications/status?limit=20', { cache: 'no-store' }),
      fetch('/api/admin/reminders/status', { cache: 'no-store' }),
    ]);
    const data = await brokerResponse.json();
    const reminder = await reminderResponse.json();
    if (!brokerResponse.ok || data.ok === false) throw new Error(data.error || 'Statut indisponible');
    if (!reminderResponse.ok || reminder.ok === false) throw new Error(reminder.error || 'Relances indisponibles');
    const counts = data.counts || {};
    notificationEl('notificationSent').textContent = counts.sent || 0;
    notificationEl('notificationFailed').textContent = counts.failed || 0;
    notificationEl('notificationDelivering').textContent = counts.delivering || 0;
    notificationEl('notificationEmail').textContent = data.channels?.email?.configured ? 'PRÊT' : 'À CONFIGURER';
    notificationEl('notificationPush').textContent = data.channels?.push?.configured ? 'PRÊT' : 'À CONFIGURER';
    notificationEl('notificationReminderInventory').textContent = reminder.inventory || 0;
    notificationEl('notificationReminderDue').textContent = reminder.eligibleNow || 0;
    notificationEl('notificationReminderBackfill').textContent = reminder.backfillComplete ? 'COMPLET' : 'EN COURS';
    const reminderState = notificationEl('notificationReminderState');
    if (reminderState) {
      const parts = [`Mercure ${reminder.sessionConnected ? 'connecté' : 'déconnecté'}`,
        `email ${reminder.emailTransportConfigured ? 'prêt' : 'à configurer'}`,
        `J-${(reminder.leadDays || []).join(' / J-')}`];
      reminderState.textContent = parts.join(' · ');
    }
    if (state) {
      state.textContent = 'Broker opérationnel';
      state.className = 'gsc-status online';
    }
    renderNotificationRows(data.recent || []);
  } catch (error) {
    if (state) {
      state.textContent = 'Erreur';
      state.className = 'gsc-status offline';
    }
  }
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

notificationEl('notificationRefresh')?.addEventListener('click', loadNotificationStatus);
notificationEl('reminderProcess')?.addEventListener('click', processRemindersNow);
loadNotificationStatus();
