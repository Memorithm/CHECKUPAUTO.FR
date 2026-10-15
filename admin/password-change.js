/* Changement du mot de passe administrateur : aucun secret dans l'URL,
 * dans le DOM de statut ni dans les journaux. Ne dépend pas de l'éditeur SEO. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const errors = {
    admin_password_current_invalid: 'Le mot de passe actuel est incorrect.',
    admin_password_confirmation_mismatch: 'Les deux nouveaux mots de passe sont différents.',
    admin_password_new_invalid: 'Choisissez au moins 8 caractères, sans espaces en début ou en fin.',
    admin_password_unchanged: 'Le nouveau mot de passe doit être différent de l’ancien.',
    admin_password_csrf_invalid: 'Session de sécurité expirée. Rechargez l’administration.',
    two_factor_required: 'Validez d’abord votre double authentification.',
  };
  async function request(url, options) {
    const response = await fetch(url, {
      credentials: 'same-origin', cache: 'no-store',
      headers: {Accept: 'application/json', ...(options?.headers || {})},
      ...options
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true) {
      const error = new Error(errors[data.error] || (
        response.status === 401 ? 'Reconnectez-vous à l’administration.' :
        'Opération indisponible. Vérifiez votre session puis réessayez.'
      ));
      throw error;
    }
    return data;
  }
  function bind() {
    const button = $('adminPasswordChange');
    const old = $('adminPasswordCurrent');
    const next = $('adminPasswordNew');
    const confirm = $('adminPasswordConfirm');
    const state = $('adminPasswordMessage');
    if (!button || !old || !next || !confirm || !state) return;
    button.addEventListener('click', async () => {
      const oldValue = old.value, nextValue = next.value, confirmValue = confirm.value;
      if (nextValue.length < 8 || nextValue.length > 128) {
        state.textContent = 'Le nouveau mot de passe doit contenir entre 8 et 128 caractères.';
        return;
      }
      if (nextValue !== confirmValue) {
        state.textContent = errors.admin_password_confirmation_mismatch;
        return;
      }
      if (!oldValue) {
        state.textContent = 'Saisissez votre mot de passe actuel.';
        return;
      }
      button.disabled = true;
      state.textContent = 'Vérification de la session…';
      try {
        const challenge = await request('/api/admin/auth/password/csrf');
        const result = await request('/api/admin/auth/password/change', {
          method: 'POST',
          headers: {'Content-Type': 'application/json',
                    'X-CheckupAuto-Admin-Password-CSRF': challenge.csrfToken},
          body: JSON.stringify({
            currentPassword: oldValue,
            newPassword: nextValue,
            confirmPassword: confirmValue
          })
        });
        if (result.reloginRequired !== true) throw new Error('Réponse serveur non confirmée.');
        state.textContent = 'Mot de passe modifié. Fermez l’onglet puis reconnectez-vous avec le nouveau mot de passe et la double authentification.';
        button.disabled = true;
      } catch (error) {
        state.textContent = error.message || 'Modification impossible.';
        button.disabled = false;
      } finally {
        // Secrets must never remain in the page after an attempt.
        old.value = '';
        next.value = '';
        confirm.value = '';
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
