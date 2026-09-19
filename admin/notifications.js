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
    const response = await fetch('/api/admin/notifications/status?limit=20', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Statut indisponible');
    const counts = data.counts || {};
    notificationEl('notificationSent').textContent = counts.sent || 0;
    notificationEl('notificationFailed').textContent = counts.failed || 0;
    notificationEl('notificationDelivering').textContent = counts.delivering || 0;
    notificationEl('notificationEmail').textContent = data.channels?.email?.configured ? 'PRÊT' : 'À CONFIGURER';
    notificationEl('notificationPush').textContent = data.channels?.push?.configured ? 'PRÊT' : 'À CONFIGURER';
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

notificationEl('notificationRefresh')?.addEventListener('click', loadNotificationStatus);
loadNotificationStatus();
