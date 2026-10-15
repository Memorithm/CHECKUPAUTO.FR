/* Remboursement d'une réservation payée en ligne sur Mercure.
 * Tout est revérifié par le serveur ; la page n'affiche que du texte (textContent)
 * et ne conserve ni code à usage unique ni confirmation après une tentative. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const API = '/api/admin/mercure-refunds/';
  const errors = {
    refund_disabled: 'Les remboursements ne sont pas activés sur ce site.',
    two_factor_not_configured: 'Activez d’abord la double authentification du back-office.',
    two_factor_required: 'Validez votre double authentification depuis le back-office, puis revenez ici.',
    refund_appointment_invalid: 'Numéro de rendez-vous invalide (chiffres uniquement).',
    refund_date_invalid: 'Date invalide.',
    refund_amount_invalid: 'Montant invalide (ex. 80 ou 80,00).',
    refund_amount_exceeds_paid: 'Le montant dépasse ce que Mercure a encaissé pour ce rendez-vous.',
    refund_appointment_not_found: 'Aucun rendez-vous avec ce numéro à cette date dans Mercure.',
    refund_appointment_ambiguous: 'Plusieurs rendez-vous correspondent : vérifiez dans Mercure.',
    refund_confirmation_expired: 'La confirmation a expiré : recommencez la vérification.',
    refund_confirmation_invalid: 'Confirmation invalide : recommencez la vérification.',
    refund_confirmation_used: 'Cette confirmation a déjà servi : recommencez la vérification.',
    refund_retype_mismatch: 'Le numéro ou le montant retapé ne correspond pas.',
    refund_second_factor_invalid: 'Code Google Authenticator invalide ou déjà utilisé. Attendez le code suivant.',
    refund_already_recorded: 'Un remboursement est déjà enregistré pour ce rendez-vous.',
    refund_daily_cap_reached: 'Plafond quotidien de remboursement atteint.',
    refund_not_refundable: 'Ce rendez-vous n’a plus de paiement en ligne remboursable.',
    refund_refused_by_mercure: 'Mercure a refusé le remboursement. Rien n’a été prélevé ni rendu.',
    refund_outcome_uncertain: 'Résultat incertain : ne recommencez pas. Utilisez « Vérifier » dans l’historique.',
    refund_not_uncertain: 'Ce remboursement n’est pas en attente de vérification.',
    refund_csrf_invalid: 'Session de sécurité expirée. Rechargez la page.',
    mercure_session_unavailable: 'Session Mercure indisponible : reconnectez Mercure dans le back-office (Mercure RDV).',
  };
  const states = {pending: 'En cours', uncertain: 'À vérifier', refunded: 'Remboursé', refused: 'Refusé'};
  let confirmation = null;

  const euros = cents => (Number(cents || 0) / 100).toLocaleString('fr-FR', {style: 'currency', currency: 'EUR'});
  const say = (text, isError) => {
    const node = $('mercureRefundMessage');
    node.textContent = text || '';
    node.classList.toggle('error', Boolean(isError));
  };

  async function call(route, body) {
    const options = {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}};
    if (body !== undefined) {
      const csrf = await call('csrf');
      options.method = 'POST';
      options.headers['Content-Type'] = 'application/json';
      options.headers['X-CheckupAuto-Refund-CSRF'] = csrf.csrfToken;
      options.body = JSON.stringify(body);
    }
    const response = await fetch(API + route, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true) {
      throw new Error(errors[data.error] || (response.status === 401
        ? 'Reconnectez-vous à l’administration.'
        : 'Opération indisponible. Réessayez plus tard.'));
    }
    return data;
  }

  function row(cells) {
    const tr = document.createElement('tr');
    cells.forEach(cell => {
      const td = document.createElement('td');
      if (cell instanceof Node) td.appendChild(cell); else td.textContent = cell;
      tr.appendChild(td);
    });
    return tr;
  }

  async function loadHistory() {
    const body = $('mercureRefundHistory');
    try {
      const data = await call('history');
      body.replaceChildren();
      if (!data.refunds.length) { body.appendChild(row(['Aucun remboursement', '', '', '', '', ''])); return; }
      data.refunds.forEach(item => {
        let action = '';
        if (item.state === 'uncertain' || (item.state === 'pending' && Date.now() / 1000 - item.at > 120)) {
          action = document.createElement('button');
          action.type = 'button'; action.className = 'secondary'; action.textContent = 'Vérifier';
          action.addEventListener('click', async () => {
            action.disabled = true;
            try {
              const result = await call('verify', {appointmentId: item.appointmentId});
              say('Vérification : ' + (states[result.state] || result.state) + '.');
            } catch (error) { say(error.message, true); }
            loadHistory();
          });
        }
        body.appendChild(row([
          item.at ? new Date(item.at * 1000).toLocaleString('fr-FR') : '',
          item.appointmentId, euros(item.amountCents), states[item.state] || item.state,
          item.cancelled ? 'Oui' : 'Non', action,
        ]));
      });
    } catch (error) {
      body.replaceChildren(row([error.message, '', '', '', '', '']));
    }
  }

  function summaryLine(list, label, value) {
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = value;
    list.append(dt, dd);
  }

  function resetConfirm() {
    confirmation = null;
    ['mercureRefundRetypeId', 'mercureRefundRetypeAmount', 'mercureRefundCode'].forEach(id => { $(id).value = ''; });
    $('mercureRefundConfirm').hidden = true;
  }

  async function lookup(event) {
    event.preventDefault();
    resetConfirm();
    $('mercureRefundReview').hidden = true;
    const button = $('mercureRefundSearch');
    button.disabled = true;
    say('Lecture du planning Mercure…');
    try {
      const amount = $('mercureRefundAmount').value.trim();
      const data = await call('lookup', {
        appointmentId: $('mercureRefundId').value.trim(),
        date: $('mercureRefundDate').value,
        amount: amount || null,
        cancelAfter: $('mercureRefundCancel').checked,
      });
      const a = data.appointment;
      const list = $('mercureRefundSummary');
      list.replaceChildren();
      summaryLine(list, 'Rendez-vous', a.appointmentId);
      summaryLine(list, 'Date et heure', a.start ? new Date(a.start).toLocaleString('fr-FR') : '—');
      summaryLine(list, 'Prestation Mercure', a.service || '—');
      summaryLine(list, 'Client', [a.customer, a.email].filter(Boolean).join(' · ') || '—');
      summaryLine(list, 'Payé en ligne', a.paidOnline ? 'Oui, ' + euros(a.paidCents) + (a.paymentModes.length ? ' (' + a.paymentModes.join(', ') + ')' : '') : 'Non');
      if (a.previousRefund) summaryLine(list, 'Remboursement déjà enregistré', (states[a.previousRefund.state] || a.previousRefund.state) + ', ' + euros(a.previousRefund.amountCents));
      $('mercureRefundReview').hidden = false;
      if (!data.confirmation) {
        say(a.previousRefund ? errors.refund_already_recorded : errors.refund_not_refundable, true);
        return;
      }
      confirmation = data.confirmation;
      $('mercureRefundAsk').textContent = 'Rembourser ' + euros(data.amountCents) + ' sur le rendez-vous ' + a.appointmentId
        + (data.cancelAfter ? ', puis annuler le rendez-vous.' : ', sans annuler le rendez-vous.');
      $('mercureRefundConfirm').hidden = false;
      say('Vérifiez le récapitulatif, puis confirmez.');
      $('mercureRefundRetypeId').focus();
    } catch (error) {
      say(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function execute(event) {
    event.preventDefault();
    if (!confirmation) return;
    const button = $('mercureRefundExecute');
    button.disabled = true;
    say('Remboursement en cours, ne fermez pas la page…');
    try {
      const result = await call('execute', {
        confirmation,
        appointmentId: $('mercureRefundRetypeId').value.trim(),
        amount: $('mercureRefundRetypeAmount').value.trim(),
        code: $('mercureRefundCode').value.trim(),
      });
      let text = 'Remboursement de ' + euros(result.refundedCents) + ' accepté par Mercure.';
      if (result.cancelRequested) text += result.cancelled ? ' Rendez-vous annulé.' : ' L’annulation du rendez-vous a échoué : supprimez-le dans Mercure.';
      say(text);
      $('mercureRefundReview').hidden = true;
      $('mercureRefundLookup').reset();
    } catch (error) {
      say(error.message, true);
    } finally {
      button.disabled = false;
      resetConfirm();
      loadHistory();
    }
  }

  async function init() {
    $('mercureRefundLookup').addEventListener('submit', lookup);
    $('mercureRefundConfirm').addEventListener('submit', execute);
    $('mercureRefundAbort').addEventListener('click', () => { resetConfirm(); $('mercureRefundReview').hidden = true; say('Opération annulée.'); });
    try {
      const status = await call('csrf');
      $('refundCap').textContent = euros(status.dailyCapCents) + ' par jour';
      $('refundAvailability').textContent = status.enabled ? 'Remboursements activés.' : errors.refund_disabled;
      $('mercureRefundSearch').disabled = !status.enabled;
    } catch (error) {
      $('refundAvailability').textContent = error.message;
      $('mercureRefundSearch').disabled = true;
    }
    loadHistory();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
