(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let state = {profiles: {}, targets: [], currentSha: '', jobs: []};
  let currentJobTimer = null;

  async function api(path, options = {}) {
    const init = {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {'Accept': 'application/json', ...(options.headers || {})}
    };
    if (init.body && !init.headers['Content-Type']) {
      init.headers['Content-Type'] = 'application/json';
    }
    const response = await fetch(path, init);
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok || payload.ok === false) {
      const error = new Error(payload.error || ('HTTP ' + response.status));
      error.code = payload.error || 'request_failed';
      throw error;
    }
    return payload;
  }

  function setMessage(text, type = '') {
    const node = $('deploymentMessage');
    if (!node) return;
    node.textContent = text;
    node.className = ('hint ' + type).trim();
  }

  function currentName() {
    return ($('deploymentName')?.value || '').trim();
  }

  function selectedProfile() {
    return state.profiles[$('deploymentProvider')?.value || ''] || null;
  }

  function applyProfileDefaults(force = false) {
    const profile = selectedProfile();
    if (!profile) return;
    if (force || !$('deploymentPort').value) {
      $('deploymentPort').value = String(profile.defaultPort || 22);
    }
    if (force || !$('deploymentRoot').value) {
      $('deploymentRoot').value = profile.defaultRoot || '';
    }
    if (force || !$('deploymentWebRoot').value) {
      $('deploymentWebRoot').value = profile.defaultWebRoot || '';
    }
    $('deploymentWebRootWrap').hidden = !profile.sharedHosting;
  }

  function populateProfiles() {
    const select = $('deploymentProvider');
    select.replaceChildren();
    Object.values(state.profiles).forEach((profile) => {
      const option = document.createElement('option');
      option.value = profile.id;
      option.textContent = profile.label;
      select.append(option);
    });
    if (state.profiles['planethoster-n0c']) select.value = 'planethoster-n0c';
    applyProfileDefaults(true);
  }

  function populateTargets() {
    const select = $('deploymentTargetSelect');
    select.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = state.targets.length ? 'Choisir une cible…' : 'Aucune cible enregistrée';
    select.append(placeholder);
    state.targets.forEach((target) => {
      const option = document.createElement('option');
      option.value = target.name;
      option.textContent = target.name + ' · ' + target.host;
      select.append(option);
    });
  }

  function loadTargetIntoForm(name) {
    const target = state.targets.find((item) => item.name === name);
    if (!target) return;
    $('deploymentName').value = target.name || '';
    $('deploymentProvider').value = target.provider || 'planethoster-n0c';
    $('deploymentHost').value = target.host || '';
    $('deploymentPort').value = String(target.port || '');
    $('deploymentUsername').value = target.username || '';
    $('deploymentDomain').value = target.domain || '';
    $('deploymentRoot').value = target.rootPath || '';
    $('deploymentWebRoot').value = target.webRootPath || '';
    $('deploymentAuthMode').value = target.authMode || 'password';
    $('deploymentPassword').value = '';
    $('deploymentIdentityFile').value = '';
    updateAuthFields();
    applyProfileDefaults(false);
  }

  function updateAuthFields() {
    const keyMode = $('deploymentAuthMode').value === 'key';
    $('deploymentPasswordWrap').hidden = keyMode;
    $('deploymentIdentityWrap').hidden = !keyMode;
  }

  function targetPayload() {
    const authMode = $('deploymentAuthMode').value;
    const target = {
      provider: $('deploymentProvider').value,
      host: $('deploymentHost').value.trim(),
      port: Number($('deploymentPort').value),
      username: $('deploymentUsername').value.trim(),
      domain: $('deploymentDomain').value.trim(),
      rootPath: $('deploymentRoot').value.trim(),
      webRootPath: $('deploymentWebRoot').value.trim(),
      authMode
    };
    const credential = authMode === 'password'
      ? {password: $('deploymentPassword').value}
      : {identityFile: $('deploymentIdentityFile').value.trim()};
    return {name: currentName(), target, credential};
  }

  async function loadStatus() {
    const payload = await api('/api/admin/deployment/status');
    state = payload;
    $('deploymentCurrentSha').textContent = (state.currentSha || '—').slice(0, 12);
    $('deploymentKnownHosts').textContent = state.knownHostsConfigured ? 'Configuré' : 'À confirmer';
    populateProfiles();
    populateTargets();
    renderJobs(state.jobs || []);
    setMessage('Deployment Center prêt.');
  }

  async function refreshStatusPreservingForm(name = currentName()) {
    const payload = await api('/api/admin/deployment/status');
    state = payload;
    $('deploymentCurrentSha').textContent = (state.currentSha || '—').slice(0, 12);
    $('deploymentKnownHosts').textContent = state.knownHostsConfigured ? 'Configuré' : 'À confirmer';
    populateProfiles();
    populateTargets();
    renderJobs(state.jobs || []);
    if (name) {
      $('deploymentTargetSelect').value = name;
      loadTargetIntoForm(name);
    }
  }

  async function saveTarget() {
    setMessage('Enregistrement de la cible…');
    const result = await api('/api/admin/deployment/target', {
      method: 'POST',
      body: JSON.stringify(targetPayload())
    });
    $('deploymentPassword').value = '';
    $('deploymentIdentityFile').value = '';
    setMessage('Cible ' + result.target.name + ' enregistrée.');
    await refreshStatusPreservingForm(result.target.name);
  }

  function renderHostKeys(keys, trusted) {
    const select = $('deploymentHostKey');
    select.replaceChildren();
    (keys || []).forEach((item) => {
      const option = document.createElement('option');
      option.value = item.fingerprint;
      option.textContent = item.keyType + ' · ' + item.fingerprint;
      select.append(option);
    });
    $('deploymentTrustedKey').textContent = trusted
      ? ('Approuvée : ' + trusted.fingerprint)
      : 'Aucune empreinte approuvée';
  }

  async function scanHostKey() {
    setMessage('Lecture de l’empreinte SSH distante…');
    const result = await api('/api/admin/deployment/hostkey/scan', {
      method: 'POST',
      body: JSON.stringify({name: currentName()})
    });
    renderHostKeys(result.keys, result.trusted);
    setMessage('Vérifie cette empreinte avec PlanetHoster avant de l’approuver.');
  }

  async function trustHostKey() {
    const fingerprint = $('deploymentHostKey').value;
    if (!fingerprint) throw new Error('Aucune empreinte SSH sélectionnée');
    const result = await api('/api/admin/deployment/hostkey/trust', {
      method: 'POST',
      body: JSON.stringify({name: currentName(), fingerprint})
    });
    renderHostKeys([], result.trusted);
    setMessage('Empreinte SSH approuvée et enregistrée.');
    await refreshStatusPreservingForm();
  }

  function renderProbe(result) {
    const body = $('deploymentProbeRows');
    body.replaceChildren();
    const assessment = result.assessment || {};
    (assessment.checks || []).forEach((check) => {
      const row = document.createElement('tr');
      [check.code, check.ok ? 'OK' : 'Bloquant', check.detail || '—'].forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = String(value);
        row.append(cell);
      });
      body.append(row);
    });
    $('deploymentProbeState').textContent = assessment.ok ? 'Compatible' : 'Bloqué';
    $('deploymentProbeState').className = 'gsc-status ' + (assessment.ok ? 'online' : 'warning');
  }

  async function probeTarget() {
    setMessage('Diagnostic SSH en cours…');
    const result = await api('/api/admin/deployment/probe', {
      method: 'POST',
      body: JSON.stringify({name: currentName()})
    });
    renderProbe(result);
    setMessage(result.assessment.ok ? 'Hébergement compatible.' : 'Des prérequis restent bloquants.');
  }

  async function buildPlan() {
    setMessage('Construction du plan vérifié…');
    const result = await api('/api/admin/deployment/plan', {
      method: 'POST',
      body: JSON.stringify({name: currentName(), sha: state.currentSha || ''})
    });
    const plan = result.plan || {};
    $('deploymentPlan').textContent = JSON.stringify({
      assessment: plan.assessment,
      actions: plan.actions,
      rollback: plan.rollback
    }, null, 2);
    setMessage(plan.assessment?.ok ? 'Plan prêt pour activation.' : 'Plan bloqué par le diagnostic.');
  }

  function renderJobs(jobs) {
    const body = $('deploymentJobs');
    body.replaceChildren();
    if (!jobs.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 6;
      cell.textContent = 'Aucun déploiement exécuté.';
      row.append(cell);
      body.append(row);
      return;
    }
    jobs.forEach((job) => {
      const row = document.createElement('tr');
      const values = [
        job.action || '—',
        (job.sha || '').slice(0, 12) || '—',
        job.state || '—',
        job.result?.readinessState || '—',
        job.result ? String(job.result.blockerCount ?? '—') : '—',
        job.finishedAt || job.startedAt || job.createdAt || '—'
      ];
      values.forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = String(value);
        row.append(cell);
      });
      body.append(row);
    });
  }

  async function pollJob(id) {
    if (currentJobTimer) clearTimeout(currentJobTimer);
    const payload = await api('/api/admin/deployment/job?id=' + encodeURIComponent(id));
    const job = payload.job;
    $('deploymentJobState').textContent = job.action + ' · ' + job.state;
    await refreshStatusPreservingForm();
    if (job.state === 'queued' || job.state === 'running') {
      currentJobTimer = setTimeout(() => pollJob(id).catch(showError), 2000);
    } else {
      const shortSha = (job.result?.sha || job.sha || '').slice(0, 12);
      if (job.state === 'succeeded') {
        setMessage('Déploiement terminé sur ' + shortSha + '.');
      } else if (job.state === 'waiting_external') {
        setMessage(
          'Release ' + shortSha +
          ' prête sur l’hébergement. Bascule DNS/SSL requise avant activation publique.'
        );
      } else {
        setMessage('Le déploiement a échoué. Relance un diagnostic avant de réessayer.');
      }
    }
  }

  async function startJob(action) {
    const payload = {name: currentName(), action};
    if (action === 'rollback') {
      payload.sha = $('deploymentRollbackSha').value.trim();
      if (!payload.sha) throw new Error('SHA de rollback requis');
    }
    setMessage(action + ' lancé…');
    const result = await api('/api/admin/deployment/job', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    $('deploymentJobState').textContent = action + ' · queued';
    await pollJob(result.job.id);
  }

  async function deleteTarget() {
    const name = currentName();
    if (!name) throw new Error('Nom de cible requis');
    if (!window.confirm('Supprimer la cible ' + name + ' du coffre ?')) return;
    await api('/api/admin/deployment/target?name=' + encodeURIComponent(name), {
      method: 'DELETE'
    });
    setMessage('Cible ' + name + ' supprimée.');
    $('deploymentName').value = '';
    await refreshStatusPreservingForm('');
  }

  function showError(error) {
    setMessage('Erreur : ' + (error.code || error.message || 'opération impossible'), 'error');
  }

  function bind(id, event, handler) {
    $(id)?.addEventListener(event, (...args) => {
      Promise.resolve(handler(...args)).catch(showError);
    });
  }

  window.addEventListener('DOMContentLoaded', () => {
    bind('deploymentProvider', 'change', () => applyProfileDefaults(true));
    bind('deploymentAuthMode', 'change', updateAuthFields);
    bind('deploymentTargetSelect', 'change', (event) => loadTargetIntoForm(event.target.value));
    bind('deploymentSave', 'click', saveTarget);
    bind('deploymentDelete', 'click', deleteTarget);
    bind('deploymentScanHostKey', 'click', scanHostKey);
    bind('deploymentTrustHostKey', 'click', trustHostKey);
    bind('deploymentProbe', 'click', probeTarget);
    bind('deploymentPlanButton', 'click', buildPlan);
    bind('deploymentInstall', 'click', () => startJob('install'));
    bind('deploymentUpdate', 'click', () => startJob('update'));
    bind('deploymentRollback', 'click', () => startJob('rollback'));
    bind('deploymentRefresh', 'click', () => refreshStatusPreservingForm());
    updateAuthFields();
    loadStatus().catch(showError);
  });
})();
