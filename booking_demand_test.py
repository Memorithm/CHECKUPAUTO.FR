"""Synthetic tests: no Mercure writes and no real customer identifiers."""
import copy
import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
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

    def test_standard_control_wins_equal_low_demand_service_ties(self):
        # Both services share centre capacity; matching physical slots must
        # not preferentially consume the VASP offering by alphabetic order.
        common = response(discounted=False)
        fitted = {**common, 'service': {'key': 'fitted'},
                  'days': [{**common['days'][0], 'slots': [{
                      **slot, 'basePrice': 90.0, 'price': 90.0
                  } for slot in common['days'][0]['slots']]}]}
        candidates = demand.candidate_slots(
            sample_history(), POLICY,
            {'fitted': fitted, 'technical': common}, TODAY)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['service'], 'technical')
        self.assertEqual(candidates[0]['finalPrice'], 75.0)

    def test_publication_requires_explicit_prod_flag(self):
        with patch.dict(os.environ, {demand.PUBLISH_ENV: ''}):
            with patch.object(demand.mercure_admin, 'plan_promotion_slot') as write:
                result = demand.run_once(POLICY)
            self.assertEqual(result['status'], 'read_only')
            write.assert_not_called()

    def test_publisher_requires_both_opt_in_and_controller(self):
        for enabled, controller in (
            ('1', ''), ('', demand.AUTHORIZED_CONTROLLER),
            ('1', 'hostinger-staging'),
        ):
            with self.subTest(enabled=enabled, controller=controller), patch.dict(
                os.environ, {demand.PUBLISH_ENV: enabled,
                             demand.CONTROLLER_ENV: controller}
            ):
                self.assertFalse(demand._publisher_enabled())
                self.assertEqual(demand.run_once(POLICY)['status'], 'read_only')

    def test_reduced_price_respects_policy_discount_cap(self):
        capped = {**POLICY, 'maxDiscountPercent': 6}
        self.assertEqual(demand.candidate_slots(
            sample_history(), capped,
            {'technical': response(discounted=False)}, TODAY), [])
        uncapped = {**POLICY, 'maxDiscountPercent': 7}
        self.assertEqual(len(demand.candidate_slots(
            sample_history(), uncapped,
            {'technical': response(discounted=False)}, TODAY)), 1)

    def test_claim_prevents_cross_service_collision_and_daily_overuse(self):
        with tempfile.TemporaryDirectory() as td, patch.object(
            demand.analytics, 'connect',
            side_effect=lambda: sqlite3.connect(td + '/promotions.sqlite')
        ):
            demand.init_db()
            self.assertTrue(demand._claim_promotion('technical|2026-10-12|15:30', 75))
            self.assertFalse(demand._claim_promotion('fitted|2026-10-12|15:30', 85))
            self.assertTrue(demand._claim_promotion('technical|2026-10-12|16:10', 75))
            self.assertFalse(demand._claim_promotion('technical|2026-10-12|16:50', 75))
            self.assertTrue(demand._claim_promotion('technical|2026-10-13|16:50', 75))

    def test_invalid_batch_limit_is_always_refused(self):
        for limit in (0, 5, -1, True, '1'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                demand.run_once(POLICY, max_new_promotions=limit)

    def test_private_ledger_isolated_from_app_database_and_requires_identity(self):
        with tempfile.TemporaryDirectory() as td:
            secure = Path(td) / 'secure'
            secure.mkdir(mode=0o700)
            ledger = secure / 'promotions.sqlite3'
            env = {demand.PUBLISH_ENV: '1',
                   demand.CONTROLLER_ENV: demand.AUTHORIZED_CONTROLLER,
                   'CYBERCHECK_LOW_DEMAND_PROMO_LEDGER_DB': str(ledger)}
            with patch.dict(os.environ, env):
                demand.init_db()
                self.assertEqual(ledger.stat().st_mode & 0o777, 0o600)
                with sqlite3.connect(ledger) as connection:
                    names = [row[0] for row in connection.execute(
                        'SELECT name FROM sqlite_master WHERE type="table"')]
                self.assertIn('booking_demand_promotion_attempts', names)
                secure.chmod(0o755)
                with self.assertRaises(PermissionError):
                    demand.init_db()
                secure.chmod(0o700)
            env[demand.CONTROLLER_ENV] = 'hostinger-staging'
            with patch.dict(os.environ, env), self.assertRaises(PermissionError):
                demand.init_db()

    def test_migration_freeze_uses_primary_dir_not_promotion_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            main = Path(td) / 'primary'
            main.mkdir()
            (main / '.migration-write-freeze.json').write_text('{}')
            secure = Path(td) / 'secure'
            secure.mkdir(mode=0o700)
            env = {demand.PUBLISH_ENV: '1',
                   demand.CONTROLLER_ENV: demand.AUTHORIZED_CONTROLLER,
                   'CYBERCHECK_DATA_DIR': str(main),
                   'CYBERCHECK_LOW_DEMAND_PROMO_LEDGER_DB':
                       str(secure / 'promotions.sqlite3')}
            with patch.dict(os.environ, env), patch.object(
                demand, 'snapshot',
                side_effect=AssertionError('no provider access during freeze')
            ):
                self.assertTrue(demand.migration_write_freeze.status()['active'])
                self.assertEqual(
                    demand.run_once(POLICY, max_new_promotions=1)['status'],
                    'blocked')

    def test_ledger_prevents_duplicate_publication_even_after_restart(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {demand.PUBLISH_ENV: '1',
                                     demand.CONTROLLER_ENV: demand.AUTHORIZED_CONTROLLER}), \
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
