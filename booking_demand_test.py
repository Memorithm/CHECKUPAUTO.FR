"""Synthetic tests: no Mercure writes and no real customer identifiers."""
import copy
import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import booking_demand as demand


TODAY = dt.date(2026, 10, 8)  # Thursday; next Monday is October 12.
MONDAY = '2026-10-12'
POLICY = {
    'enabled': True, 'eligibleServices': {'technical': True, 'fitted': True},
    'allowedWeekdays': [1, 2, 3, 4, 5, 6],
    'timeStart': '09:00', 'timeEnd': '19:00', 'horizonDays': 30,
}


def sample_history():
    rows = []
    for index in range(23):
        day = dt.date(2026, 10, 5) - dt.timedelta(days=(index // 4) * 7)
        rows.append({'id': str(index + 1),
                     'date_rdv': f'{day} 10:{index % 4 * 10:02d}:00',
                     'prestation': 'TOUT VEHICULE HORS CAMPING CAR'})
    for index in range(3):
        rows.append({'id': str(index + 100),
                     'date_rdv': f'2026-10-05 14:{index * 10:02d}:00',
                     'prestation': 'Contrôle technique'})
    return demand._count_history(rows, TODAY)


def response(*, discounted=True, available=True):
    base = 80.0
    cheap = 75.0 if discounted else base
    return {
        'service': {'key': 'technical', 'basePrice': base},
        'days': [{'date': MONDAY, 'available': available, 'slots': [
            {'time': '10:00', 'basePrice': base, 'price': cheap,
             'promotion': discounted, 'saving': base - cheap},
            {'time': '15:30', 'basePrice': base, 'price': cheap,
             'promotion': discounted, 'saving': base - cheap},
        ]}],
    }


class DemandHistoryTest(unittest.TestCase):
    def test_weak_slots_are_detected_with_weekday_matched_history(self):
        history = sample_history()
        self.assertEqual(history['totals'][1], 26)
        self.assertIsNone(demand.weakness(history, 'technical', MONDAY, '10:00'))
        self.assertIsNotNone(demand.weakness(history, 'technical', MONDAY, '15:30'))
        self.assertIsNone(demand.weakness(history, 'fitted', '2026-10-13', '15:30'))

    def test_insufficient_evidence_never_creates_an_offer(self):
        history = {'counts': {}, 'totals': {1: 8},
                   'peaks': {1: 4}}
        self.assertIsNone(demand.weakness(history, 'technical', MONDAY, '15:00'))

    def test_duplicate_cancelled_and_test_appointments_do_not_bias_counts(self):
        rows = [
            {'id': '1', 'date_rdv': '2026-10-05 10:30:00',
             'prestation': 'Contrôle technique'},
            {'id': '1', 'date_rdv': '2026-10-05 10:30:00',
             'prestation': 'Contrôle technique'},
            {'id': '2', 'date_rdv': '2026-10-05 10:00:00',
             'prestation': 'Contrôle technique', 'statut': 'Annulé'},
            {'id': '3', 'date_rdv': '2026-10-05 10:00:00',
             'prestation': 'Contrôle technique', 'nom': 'CYBERCHECK TEST'},
            {'id': '4', 'date_rdv': '2026-10-05 11:00:00',
             'prestation': 'CONTRE-VISITE'},
            {'id': '5', 'date_rdv': '2026-10-10 10:00:00',
             'prestation': 'Contrôle technique'},
        ]
        info = demand._count_history(rows, TODAY)
        self.assertEqual(info['totals'][1], 2)  # Inclut la contre-visite qui occupe la ligne.

    def test_actual_mercure_service_codes_are_counted_as_centre_demand(self):
        rows = [
            {'id': '11', 'centre': 'Check Up Auto',
             'date_rdv': '05/10/2026 15:30', 'prestation': 'CTP'},
            {'id': '12', 'centre': 'Check Up Auto',
             'date_rdv': '2026-10-05 15:40', 'prestation': 'VTP'},
            {'id': '13', 'centre': 'Un autre centre',
             'date_rdv': '2026-10-05 15:50', 'prestation': 'CTP'},
        ]
        actual = demand._count_history(rows, TODAY)
        self.assertEqual(actual['totals'][1], 2)
        self.assertEqual(actual['counts'][(1, 15)], 2)

    def test_anonymous_requests_never_probe_admin_history(self):
        initial = response()
        with patch.object(demand, 'snapshot', side_effect=AssertionError('must not read')):
            result = demand.decorate_availability(
                initial, authenticated=False, policy=POLICY)
        self.assertEqual(result, initial)
        self.assertIsNot(result, initial)

    def test_logged_in_offer_requires_real_mercure_discount(self):
        original = response()
        decorated = demand.decorate_availability(
            original, authenticated=True, policy=POLICY,
            history=sample_history())
        slots = decorated['days'][0]['slots']
        self.assertNotIn('lowDemandOffer', slots[0])  # Popular hour.
        self.assertEqual(slots[1]['lowDemandOffer']['savingEuro'], 5.0)
        self.assertNotIn('lowDemandOffer', original['days'][0]['slots'][1])
        full_price = demand.decorate_availability(
            response(discounted=False), authenticated=True, policy=POLICY,
            history=sample_history())
        self.assertTrue(all('lowDemandOffer' not in slot
                            for slot in full_price['days'][0]['slots']))

    def test_wrong_service_or_disabled_promotion_is_not_highlighted(self):
        for override in (
            {'enabled': False}, {'eligibleServices': {'technical': False}},
        ):
            policy = {**POLICY, **override}
            result = demand.decorate_availability(
                response(), authenticated=True, policy=policy,
                history=sample_history())
            self.assertFalse(any('lowDemandOffer' in s
                                 for s in result['days'][0]['slots']))

    def test_history_failure_fails_closed_without_false_discount(self):
        with patch.object(demand, 'snapshot', side_effect=RuntimeError('no session')):
            result = demand.decorate_availability(
                response(), authenticated=True, policy=POLICY)
        self.assertNotIn('lowDemandOffer', result['days'][0]['slots'][1])


class PromotionPublicationTest(unittest.TestCase):
    def test_candidates_are_bounded_and_skip_previously_discounted_slots(self):
        candidate = response(discounted=False)
        eligible = demand.candidate_slots(
            sample_history(), POLICY, {'technical': candidate}, TODAY)
        self.assertEqual([row['time'] for row in eligible], ['15:30'])
        self.assertEqual(eligible[0]['finalPrice'], 75.0)
        self.assertEqual(demand.candidate_slots(
            sample_history(), POLICY, {'technical': response()}, TODAY), [])

    def test_publication_requires_explicit_prod_flag(self):
        with patch.dict(os.environ, {demand.PUBLISH_ENV: ''}):
            with patch.object(demand.mercure_admin, 'plan_promotion_slot') as write:
                result = demand.run_once(POLICY)
            self.assertEqual(result['status'], 'read_only')
            write.assert_not_called()

    def test_ledger_prevents_duplicate_publication_even_after_restart(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {demand.PUBLISH_ENV: '1'}), \
             patch.object(demand.migration_write_freeze, 'status',
                          return_value={'active': False}), \
             patch.object(demand, 'snapshot', return_value=sample_history()), \
             patch.object(demand.mercure_admin, 'business_today',
                          return_value=TODAY), \
             patch.object(demand.mercure_admin, 'list_promotions',
                          return_value=[]), \
             patch.object(demand.mercure_public, 'availability',
                          return_value=response(discounted=False)), \
             patch.object(demand.mercure_public, '_provider_availability',
                          return_value={}), \
             patch.object(demand.mercure_public, '_normalize_availability',
                          return_value={'days': [{'date': MONDAY, 'slots': [
                              {'time': '15:30', 'price': 75.0}]}]}), \
             patch.object(demand.mercure_admin, 'plan_promotion_slot',
                          return_value={'promotionId': 'promo-test'}) as write, \
             patch.object(demand.analytics, 'connect',
                          side_effect=lambda: sqlite3.connect(td + '/promo.sqlite')):
            technical_policy = {
                **POLICY,
                'eligibleServices': {'technical': True, 'fitted': False},
            }
            first = demand.run_once(technical_policy)
            second = demand.run_once(technical_policy)
            self.assertEqual(first['published'], 1)
            self.assertEqual(second['published'], 0)
            write.assert_called_once()
            self.assertEqual(write.call_args.kwargs['final_price'], 75.0)
            with sqlite3.connect(td + '/promo.sqlite') as db:
                self.assertEqual(db.execute(
                    'SELECT state FROM booking_demand_promotion_attempts'
                ).fetchone()[0], 'verified')


if __name__ == '__main__':
    unittest.main()
