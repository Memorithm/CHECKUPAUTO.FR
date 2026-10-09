"""Customer-visible payment status; never infer a capture from a booking."""
from __future__ import annotations

VALID_MODES = frozenset({'centre', 'online'})
VALID_STATES = frozenset({'due_at_centre', 'awaiting_provider', 'captured', 'declined', 'cancelled'})


def assess(*, policy: dict, provider_state: str | None = None,
           provider_verified: bool = False) -> dict:
    if not isinstance(policy, dict) or policy.get('providerVerified') is not True:
        raise ValueError('payment_policy_unverified')
    mode = policy.get('paymentMode')
    if mode not in VALID_MODES or policy.get('paymentRequired') is not (mode == 'online'):
        raise ValueError('payment_mode_invalid')
    if mode == 'centre':
        if provider_state is not None or provider_verified:
            raise ValueError('centre_payment_proof_invalid')
        return {'mode': 'centre', 'state': 'due_at_centre', 'paid': False,
                'message': 'Paiement à effectuer au centre le jour du rendez-vous'}
    if provider_state is None:
        return {'mode': 'online', 'state': 'awaiting_provider', 'paid': False,
                'message': 'Paiement en ligne en attente de confirmation bancaire'}
    if provider_verified is not True or provider_state not in VALID_STATES - {'due_at_centre'}:
        raise ValueError('payment_provider_evidence_invalid')
    return {'mode': 'online', 'state': provider_state, 'paid': provider_state == 'captured',
            'message': {'captured': 'Paiement confirmé par le prestataire',
                        'declined': 'Paiement refusé',
                        'cancelled': 'Paiement annulé',
                        'awaiting_provider': 'Paiement en cours de vérification'}[provider_state]}
