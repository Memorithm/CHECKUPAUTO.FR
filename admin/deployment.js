(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let state = {profiles: {}, targets: [], currentSha: '', jobs: []};
  let updateState = null;
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
    resetUpdateState();
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
    renderSourceState();
    $('deploymentKnownHosts').textContent = state.knownHostsConfigured ? 'Configuré' : 'À confirmer';
    populateProfiles();
    populateTargets();
    renderJobs(state.jobs || []);
    resetUpdateState();
    setMessage('Deployment Center prêt.');
  }

  async function refreshStatusPreservingForm(name = currentName()) {
    const payload = await api('/api/admin/deployment/status');
    state = payload;
    $('deploymentCurrentSha').textContent = (state.currentSha || '—').slice(0, 12);
    renderSourceState();
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
      body: JSON.stringify({name: currentName(), sha: ''})
    });
    const plan = result.plan || {};
    $('deploymentPlan').textContent = JSON.stringify({
      assessment: plan.assessment,
      actions: plan.actions,
      rollback: plan.rollback
    }, null, 2);
    setMessage(plan.assessment?.ok ? 'Plan prêt pour activation.' : 'Plan bloqué par le diagnostic.');
  }

  function sourceBuildCapable() {
    return Boolean(state.source && state.source.buildCapable);
  }

  function renderSourceState() {
    const source = state.source || {};
    const remote = source.remote || {};
    const labels = {
      git_checkout: 'Git local prêt',
      github_remote: 'GitHub prêt',
      packaged_release: 'Release packagée',
      git_invalid: 'Git invalide',
      unavailable: 'Indisponible'
    };
    $('deploymentSourceState').textContent = labels[source.mode] || 'Inconnue';
    $('deploymentInstall').disabled = !sourceBuildCapable();
    if (!sourceBuildCapable()) {
      $('deploymentUpdate').disabled = true;
    }

    if ($('deploymentGitHubRepository')) {
      $('deploymentGitHubRepository').value =
        remote.repository || 'Memorithm/CHECKUPAUTO.FR';
      $('deploymentGitHubBranch').value = remote.branch || 'main';
      $('deploymentGitHubToken').value = '';
      $('deploymentGitHubState').textContent =
        remote.tokenConfigured ? 'Configurée' : 'Token absent';
      $('deploymentGitHubState').className =
        'gsc-status ' + (remote.tokenConfigured ? 'online' : 'warning');
    }
  }

  async function saveUpdateSource() {
    const repository = $('deploymentGitHubRepository').value.trim();
    const branch = $('deploymentGitHubBranch').value.trim();
    const token = $('deploymentGitHubToken').value.trim();
    setMessage('Enregistrement de la source GitHub…');
    const result = await api('/api/admin/deployment/source', {
      method: 'POST',
      body: JSON.stringify({repository, branch, token})
    });
    $('deploymentGitHubToken').value = '';
    $('deploymentGitHubState').textContent =
      result.source?.tokenConfigured ? 'Configurée' : 'Token absent';
    $('deploymentGitHubDetail').textContent =
      'Source ' + (result.source?.repository || repository) +
      ' · branche ' + (result.source?.branch || branch) + '.';
    await refreshStatusPreservingForm();
  }

  async function testUpdateSource() {
    setMessage('Vérification de la source GitHub…');
    const result = await api('/api/admin/deployment/source/test', {
      method: 'POST',
      body: JSON.stringify({})
    });
    const sha = result.latestSha || '';
    $('deploymentGitHubState').textContent = 'Vérifiée';
    $('deploymentGitHubState').className = 'gsc-status online';
    $('deploymentGitHubDetail').textContent =
      'Source accessible · dernier SHA : ' + sha.slice(0, 12);
    setMessage('Source GitHub vérifiée.');
  }

  async function deleteUpdateSourceToken() {
    if (!window.confirm('Supprimer le token GitHub de mise à jour ?')) return;
    await api('/api/admin/deployment/source', {method: 'DELETE'});
    $('deploymentGitHubToken').value = '';
    $('deploymentGitHubState').textContent = 'Token absent';
    $('deploymentGitHubState').className = 'gsc-status warning';
    $('deploymentGitHubDetail').textContent =
      'Le dépôt et la branche restent enregistrés, mais Install/Update distant est désactivé.';
    await refreshStatusPreservingForm();
  }

  function resetUpdateState() {
    updateState = null;
    $('deploymentRemoteSha').textContent = '—';
    $('deploymentUpdateState').textContent = 'Non vérifiée';
    $('deploymentUpdateDetail').textContent = 'Version distante non vérifiée.';
    $('deploymentUpdate').disabled = true;
    const candidates = $('deploymentRollbackCandidates');
    if (candidates) candidates.replaceChildren();
  }

  function renderUpdateState(result) {
    updateState = result || {};
    const deployed = updateState.deployedSha || '';
    $('deploymentRemoteSha').textContent = deployed ? deployed.slice(0, 12) : 'Non installée';

    const labels = {
      not_installed: 'Non installée',
      up_to_date: 'À jour',
      update_available: 'Disponible',
      remote_ahead: 'Cible en avance',
      diverged: 'Divergence',
      source_unavailable: 'Source indisponible'
    };
    $('deploymentUpdateState').textContent = labels[updateState.state] || 'Inconnue';
    $('deploymentUpdate').disabled = !updateState.updateAvailable || !sourceBuildCapable();

    const candidates = $('deploymentRollbackCandidates');
    candidates.replaceChildren();
    (updateState.rollbackCandidates || []).forEach((sha) => {
      const option = document.createElement('option');
      option.value = sha;
      option.label = sha.slice(0, 12);
      candidates.append(option);
    });

    const releaseCount = (updateState.releases || []).length;
    if (updateState.state === 'update_available') {
      $('deploymentUpdateDetail').textContent =
        'Mise à jour disponible : ' + deployed.slice(0, 12) + ' → ' +
        (updateState.desiredSha || '').slice(0, 12) + '. ' +
        releaseCount + ' release(s) vérifiée(s) disponible(s) pour rollback.';
    } else if (updateState.state === 'up_to_date') {
      $('deploymentUpdateDetail').textContent =
        'La cible exécute déjà la version locale courante. ' +
        releaseCount + ' release(s) vérifiée(s) conservée(s).';
    } else if (updateState.state === 'not_installed') {
      $('deploymentUpdateDetail').textContent =
        'Aucune release active détectée : utilise Installer depuis un contrôleur Git.';
    } else if (updateState.state === 'source_unavailable') {
      $('deploymentUpdateDetail').textContent =
        'Cette instance est une release packagée sans source GitHub de build. Configure la source de mise à jour ci-dessus ; le rollback reste disponible.';
    } else if (updateState.state === 'remote_ahead') {
      $('deploymentUpdateDetail').textContent =
        'La cible distante est plus récente que le checkout local. Mise à jour bloquée.';
    } else {
      $('deploymentUpdateDetail').textContent =
        'Historique Git divergent : mise à jour automatique bloquée, diagnostic requis.';
    }
  }

  async function checkUpdateStatus() {
    const name = currentName();
    if (!name) throw new Error('Nom de cible requis');
    setMessage('Lecture de la version réellement déployée…');
    const payload = await api('/api/admin/deployment/update-status', {
      method: 'POST',
      body: JSON.stringify({name})
    });
    renderUpdateState(payload.update || {});
    setMessage(
      payload.update?.updateAvailable
        ? 'Une mise à jour vérifiée est disponible.'
        : 'État de mise à jour vérifié.'
    );
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
      setMessage(job.state === 'succeeded'
        ? ('Déploiement terminé sur ' + shortSha + '.')
        : 'Le déploiement a échoué. Relance un diagnostic avant de réessayer.');
    }
  }

  async function startJob(action) {
    if ((action === 'install' || action === 'update') && !sourceBuildCapable()) {
      throw new Error('Source Git de build indisponible sur cette instance');
    }
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
    bind('deploymentGitHubSave', 'click', saveUpdateSource);
    bind('deploymentGitHubTest', 'click', testUpdateSource);
    bind('deploymentGitHubDelete', 'click', deleteUpdateSourceToken);
    bind('deploymentDelete', 'click', deleteTarget);
    bind('deploymentScanHostKey', 'click', scanHostKey);
    bind('deploymentTrustHostKey', 'click', trustHostKey);
    bind('deploymentProbe', 'click', probeTarget);
    bind('deploymentPlanButton', 'click', buildPlan);
    bind('deploymentCheckUpdate', 'click', checkUpdateStatus);
    bind('deploymentInstall', 'click', () => startJob('install'));
    bind('deploymentUpdate', 'click', () => startJob('update'));
    bind('deploymentRollback', 'click', () => startJob('rollback'));
    bind('deploymentRefresh', 'click', () => refreshStatusPreservingForm());
    updateAuthFields();
    resetUpdateState();
    loadStatus().catch(showError);
  });
})();
