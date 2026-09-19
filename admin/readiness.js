const readinessEl = id => document.getElementById(id);

function readinessCell(row, value) {
  const cell = document.createElement('td');
  cell.textContent = value == null || value === '' ? '—' : String(value);
  row.appendChild(cell);
}

function readinessLabel(state) {
  if (state === 'ready') return 'PRÊT';
  if (state === 'configuration_required') return 'CONFIG REQUISE';
  if (state === 'blocked_external') return 'BLOCAGE EXTERNE';
  if (state === 'degraded') return 'DÉGRADÉ';
  return String(state || 'INCONNU').toUpperCase();
}

function renderReadinessComponents(items) {
  const body = readinessEl('readinessComponents');
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
    readinessCell(row, item.label || item.id);
    readinessCell(row, readinessLabel(item.state));
    readinessCell(row, item.critical ? 'OUI' : 'NON');
    readinessCell(row, item.detail || '—');
    body.appendChild(row);
  }
}

async function loadProductionReadiness() {
  const badge = readinessEl('readinessState');
  try {
    const response = await fetch('/api/admin/readiness', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Readiness indisponible');
    const counts = data.counts || {};
    readinessEl('readinessLaunch').textContent = data.launchReady ? 'PRÊT' : 'BLOQUÉ';
    readinessEl('readinessReady').textContent = counts.ready || 0;
    readinessEl('readinessConfig').textContent = counts.configuration_required || 0;
    readinessEl('readinessExternal').textContent = counts.blocked_external || 0;
    readinessEl('readinessDegraded').textContent = counts.degraded || 0;
    renderReadinessComponents(Array.isArray(data.components) ? data.components : []);
    if (badge) {
      badge.textContent = readinessLabel(data.state);
      badge.className = data.state === 'ready' ? 'gsc-status online' : data.state === 'degraded' ? 'gsc-status offline' : 'gsc-status warning';
    }
  } catch {
    if (badge) {
      badge.textContent = 'INDISPONIBLE';
      badge.className = 'gsc-status offline';
    }
    renderReadinessComponents([]);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  readinessEl('readinessRefresh')?.addEventListener('click', loadProductionReadiness);
  loadProductionReadiness();
});
