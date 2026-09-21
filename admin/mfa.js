(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let enrollmentStarted = false;

  async function request(path, options = {}) {
    const init = {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {
        'Accept': 'application/json',
        ...(options.headers || {})
      }
    };
    if (init.body && !init.headers['Content-Type']) {
      init.headers['Content-Type'] = 'application/json';
    }
    const response = await fetch(path, init);
    let payload = {};
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) {
      try { payload = await response.json(); } catch (_) {}
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(payload.error || ('HTTP ' + response.status));
      error.code = payload.error || 'request_failed';
      throw error;
    }
    return payload;
  }

  function show(node, visible) {
    if (node) node.hidden = !visible;
  }

  function setError(message = '') {
    const node = $('mfaError');
    if (node) node.textContent = message;
  }

  function lockGate() {
    show($('mfaGate'), true);
    document.documentElement.classList.add('mfa-locked');
  }

  function unlockGate() {
    show($('mfaGate'), false);
    document.documentElement.classList.remove('mfa-locked');
  }

  function modeSetup() {
    lockGate();
    $('mfaTitle').textContent = 'Activer la double authentification';
    $('mfaText').textContent =
      'Le mot de passe administrateur reste le premier facteur. Ajoute maintenant Google Authenticator pour protéger les API du back-office.';
    show($('mfaSetup'), true);
    show($('mfaLogin'), false);
    show($('mfaRecovery'), false);
    show($('mfaEnrollment'), enrollmentStarted);
  }

  function modeLogin(remaining = 0) {
    lockGate();
    $('mfaTitle').textContent = 'Validation Google Authenticator';
    $('mfaText').textContent =
      'Saisis le code à 6 chiffres de Google Authenticator. Un code de récupération peut aussi être utilisé une seule fois.' +
      (remaining ? (' · ' + remaining + ' code(s) de récupération restant(s).') : '');
    show($('mfaSetup'), false);
    show($('mfaLogin'), true);
    show($('mfaRecovery'), false);
    $('mfaCode')?.focus();
  }

  async function refreshStatus() {
    setError('');
    const payload = await request('/api/admin/auth/2fa/status');
    const status = payload.twoFactor || {};
    if (!status.configured) {
      modeSetup();
      return;
    }
    if (!status.sessionAuthenticated) {
      modeLogin(Number(status.recoveryRemaining || 0));
      return;
    }
    unlockGate();
  }

  async function beginSetup() {
    setError('');
    const payload = await request('/api/admin/auth/2fa/setup', {
      method: 'POST',
      body: JSON.stringify({})
    });
    const enrollment = payload.enrollment || {};
    if (!enrollment.secret) throw new Error('Réponse d’enrôlement invalide');
    enrollmentStarted = true;
    $('mfaSecret').textContent = enrollment.secret;
    $('mfaQr').src = '/api/admin/auth/2fa/qr?ts=' + Date.now();
    show($('mfaEnrollment'), true);
    $('mfaConfirmCode')?.focus();
  }

  async function confirmSetup() {
    setError('');
    const code = ($('mfaConfirmCode')?.value || '').trim();
    if (!/^[0-9]{6}$/.test(code)) {
      throw new Error('Code à 6 chiffres requis');
    }
    const payload = await request('/api/admin/auth/2fa/confirm', {
      method: 'POST',
      body: JSON.stringify({code})
    });
    const codes = Array.isArray(payload.recoveryCodes)
      ? payload.recoveryCodes
      : [];
    if (!codes.length) throw new Error('Codes de récupération absents');
    $('mfaRecoveryCodes').textContent = codes.join('\n');
    show($('mfaSetup'), false);
    show($('mfaLogin'), false);
    show($('mfaRecovery'), true);
    $('mfaTitle').textContent = '2FA activée';
    $('mfaText').textContent =
      'Sauvegarde ces codes hors ligne. Ils ne seront pas réaffichés.';
  }

  async function verify() {
    setError('');
    const code = ($('mfaCode')?.value || '').trim();
    if (!code) throw new Error('Code requis');
    await request('/api/admin/auth/2fa/verify', {
      method: 'POST',
      body: JSON.stringify({code})
    });
    window.location.reload();
  }

  function bind(id, event, fn) {
    $(id)?.addEventListener(event, (...args) => {
      Promise.resolve(fn(...args)).catch((error) => {
        setError(error.message || error.code || 'Opération impossible');
      });
    });
  }

  lockGate();

  window.addEventListener('DOMContentLoaded', () => {
    bind('mfaStartSetup', 'click', beginSetup);
    bind('mfaConfirm', 'click', confirmSetup);
    bind('mfaVerify', 'click', verify);
    bind('mfaRecoveryDone', 'click', () => window.location.reload());

    $('mfaConfirmCode')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        confirmSetup().catch((error) => setError(error.message || 'Code invalide'));
      }
    });
    $('mfaCode')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        verify().catch((error) => setError(error.message || 'Code invalide'));
      }
    });

    refreshStatus().catch((error) => {
      lockGate();
      setError(error.message || 'État 2FA indisponible');
    });
  });
})();
