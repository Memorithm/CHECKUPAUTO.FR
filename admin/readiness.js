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

function readinessAction(row, remediation) {
  const cell = document.createElement('td');
  if (!remediation || !remediation.summary) {
    cell.textContent = '—';
  } else {
    const summary = document.createElement('span');
    summary.textContent = remediation.summary;
    cell.appendChild(summary);
    if (typeof remediation.target === 'string' && remediation.target.startsWith('#')) {
      const link = document.createElement('a');
      link.href = remediation.target;
      link.textContent = ' Ouvrir';
      cell.appendChild(link);
    }
  }
  row.appendChild(cell);
}

function readinessGitSha(value) {
  const sha = String(value || '').trim().toLowerCase();
  return /^[0-9a-f]{40}$/.test(sha) ? sha : '';
}

function readinessRuntimeCard(label, id) {
  const article = document.createElement('article');
  const small = document.createElement('small');
  const strong = document.createElement('strong');
  small.textContent = label;
  strong.id = id;
  strong.textContent = '—';
  article.append(small, strong);
  return article;
}

function ensureRuntimeProvenancePanel() {
  const section = readinessEl('readiness');
  if (!section) return null;
  const existing = readinessEl('readinessRuntimeProvenance');
  if (existing) return existing;

  const panel = document.createElement('div');
  panel.id = 'readinessRuntimeProvenance';
  panel.className = 'integration-box';

  const heading = document.createElement('div');
  heading.className = 'panel-head compact';
  const copy = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = 'Provenance du runtime';
  const hint = document.createElement('p');
  hint.className = 'hint';
  hint.textContent = 'Compare le code réellement exécuté au baseline d’intégrité local. Une correspondance avec ce baseline ne prouve pas, à elle seule, que le runtime exécute le dernier main GitHub.';
  copy.append(title, hint);
  heading.appendChild(copy);

  const grid = document.createElement('div');
  grid.className = 'metric-grid';
  grid.append(
    readinessRuntimeCard('RUNTIME SHA', 'readinessRuntimeSha'),
    readinessRuntimeCard('BRANCHE RUNTIME', 'readinessRuntimeBranch'),
    readinessRuntimeCard('WORKTREE', 'readinessRuntimeDirty'),
    readinessRuntimeCard('BASELINE SHA', 'readinessBaselineSha'),
    readinessRuntimeCard('BASELINE / RUNTIME', 'readinessBaselineMatch'),
  );
  panel.append(heading, grid);

  const table = section.querySelector('.table-scroll');
  if (table) table.before(panel);
  else section.appendChild(panel);
  return panel;
}

function renderRuntimeProvenance(runtime) {
  ensureRuntimeProvenancePanel();
  runtime = runtime && typeof runtime === 'object' ? runtime : {};
  const runtimeSha = runtime.gitShaAvailable === true ? readinessGitSha(runtime.gitSha) : '';
  const baselineSha = readinessGitSha(runtime.baselineGitSha);
  const branch = typeof runtime.gitBranch === 'string' ? runtime.gitBranch.trim().slice(0, 100) : '';
  const dirty = runtime.gitDirty === false ? 'PROPRE' : runtime.gitDirty === true ? 'MODIFIÉ' : 'NON VÉRIFIÉ';
  let baselineMatch = 'NON VÉRIFIÉ';
  if (runtimeSha && baselineSha && runtime.baselineMatchesRuntime === true) baselineMatch = 'CONFORME';
  else if (runtimeSha && baselineSha && runtime.baselineMatchesRuntime === false) baselineMatch = 'ÉCART';

  const shaEl = readinessEl('readinessRuntimeSha');
  const branchEl = readinessEl('readinessRuntimeBranch');
  const dirtyEl = readinessEl('readinessRuntimeDirty');
  const baselineEl = readinessEl('readinessBaselineSha');
  const matchEl = readinessEl('readinessBaselineMatch');
  if (shaEl) shaEl.textContent = runtimeSha || '—';
  if (branchEl) branchEl.textContent = branch || '—';
  if (dirtyEl) dirtyEl.textContent = dirty;
  if (baselineEl) baselineEl.textContent = baselineSha || '—';
  if (matchEl) matchEl.textContent = baselineMatch;
}

function renderReadinessComponents(items) {
  const body = readinessEl('readinessComponents');
  if (!body) return;
  body.replaceChildren();
  if (!items.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 5;
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
    readinessAction(row, item.remediation);
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
    const gate = data.activationGate || {};
    const activationAllowed = gate.allowed === true;
    readinessEl('readinessLaunch').textContent = activationAllowed ? 'PRÊT' : 'BLOQUÉ';
    const gateReason = readinessEl('readinessGateReason');
    if (gateReason) {
      const blockers = Array.isArray(gate.blockingComponents) ? gate.blockingComponents : [];
      gateReason.textContent = activationAllowed
        ? 'Garde de publication ouverte : tous les composants critiques sont prêts.'
        : 'Garde de publication fermée : ' + (blockers.length ? blockers.join(', ') : 'diagnostic critique incomplet');
    }
    readinessEl('readinessReady').textContent = counts.ready || 0;
    readinessEl('readinessConfig').textContent = counts.configuration_required || 0;
    readinessEl('readinessExternal').textContent = counts.blocked_external || 0;
    readinessEl('readinessDegraded').textContent = counts.degraded || 0;
    renderRuntimeProvenance(data.runtime);
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
    renderRuntimeProvenance({});
    renderReadinessComponents([]);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  readinessEl('readinessRefresh')?.addEventListener('click', loadProductionReadiness);
  loadProductionReadiness();
});
