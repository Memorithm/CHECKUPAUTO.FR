import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import security_alerts as alerts


class SecurityAlertsRecoveryTest(unittest.TestCase):
    def _seed(self, db_path: Path):
        with sqlite3.connect(db_path) as db:
            rows = [
                ('2026-09-19T10:00:00+00:00', 'high', 'dependency_drift', 'Dependency drift'),
                ('2026-09-19T10:01:00+00:00', 'high', 'dependency_vulnerability', 'Dependency vulnerability'),
                ('2026-09-19T10:02:00+00:00', 'high', 'automatic_quarantine', 'Quarantine'),
            ]
            for created, level, kind, title in rows:
                db.execute(
                    '''INSERT INTO security_alerts(created_at,level,kind,title)
                       VALUES(?,?,?,?)''',
                    (created, level, kind, title),
                )

    def test_recovered_dependency_alerts_close_only_proven_conditions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'security.sqlite3'
            with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path):
                alerts.init_db()
                self._seed(db_path)
                result = alerts.resolve_recovered_dependencies(
                    dependencies_ok=True,
                    vulnerability_count=0,
                )
                with sqlite3.connect(db_path) as db:
                    state = dict(db.execute(
                        'SELECT kind,acknowledged FROM security_alerts'
                    ).fetchall())
        self.assertEqual(result['updated'], 2)
        self.assertEqual(state['dependency_drift'], 1)
        self.assertEqual(state['dependency_vulnerability'], 1)
        self.assertEqual(state['automatic_quarantine'], 0)

    def test_unproven_recovery_does_not_close_alerts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'security.sqlite3'
            with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path):
                alerts.init_db()
                self._seed(db_path)
                result = alerts.resolve_recovered_dependencies(
                    dependencies_ok=False,
                    vulnerability_count=None,
                )
                with sqlite3.connect(db_path) as db:
                    open_count = db.execute(
                        'SELECT COUNT(*) FROM security_alerts WHERE acknowledged=0'
                    ).fetchone()[0]
        self.assertEqual(result['updated'], 0)
        self.assertEqual(open_count, 3)

    def test_partial_recovery_closes_only_matching_alert_kind(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'security.sqlite3'
            with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path):
                alerts.init_db()
                self._seed(db_path)
                result = alerts.resolve_recovered_dependencies(
                    dependencies_ok=True,
                    vulnerability_count=2,
                )
                with sqlite3.connect(db_path) as db:
                    state = dict(db.execute(
                        'SELECT kind,acknowledged FROM security_alerts'
                    ).fetchall())
        self.assertEqual(result['updated'], 1)
        self.assertEqual(state['dependency_drift'], 1)
        self.assertEqual(state['dependency_vulnerability'], 0)
        self.assertEqual(state['automatic_quarantine'], 0)

class SecurityAlertsSummaryTest(unittest.TestCase):
    def test_summary_surfaces_old_open_high_alerts_as_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'security.sqlite3'
            with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path):
                alerts.init_db()
                with sqlite3.connect(db_path) as db:
                    db.execute(
                        '''INSERT INTO security_alerts(created_at,level,kind,title)
                           VALUES(?,?,?,?)''',
                        ('2026-09-19T00:00:00+00:00', 'high', 'automatic_quarantine', 'Old quarantine'),
                    )
                    for idx in range(30):
                        db.execute(
                            '''INSERT INTO security_alerts(created_at,level,kind,title,acknowledged)
                               VALUES(?,?,?,?,1)''',
                            (f'2026-09-19T01:{idx:02d}:00+00:00', 'info', 'noise', f'Info {idx}'),
                        )
                result = alerts.summary()
        latest_ids = {row['id'] for row in result['latest']}
        actionable_ids = {row['id'] for row in result['actionable']}
        self.assertNotIn(1, latest_ids)
        self.assertIn(1, actionable_ids)
        self.assertEqual(result['highOrCritical'], 1)
        self.assertEqual(result['undeliveredHighOrCritical'], 1)

    def test_actionable_excludes_acknowledged_and_non_high_alerts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / 'security.sqlite3'
            with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path):
                alerts.init_db()
                with sqlite3.connect(db_path) as db:
                    db.execute(
                        '''INSERT INTO security_alerts(created_at,level,kind,title)
                           VALUES(?,?,?,?)''',
                        ('2026-09-19T00:00:00+00:00', 'medium', 'medium_event', 'Medium'),
                    )
                    db.execute(
                        '''INSERT INTO security_alerts(created_at,level,kind,title,acknowledged)
                           VALUES(?,?,?,?,1)''',
                        ('2026-09-19T00:01:00+00:00', 'critical', 'reviewed', 'Reviewed',),
                    )
                result = alerts.summary()
        self.assertEqual(result['actionable'], [])


class SecurityAlertsAdminContractTest(unittest.TestCase):
    def test_console_prioritizes_actionable_alerts_without_inner_html_for_rows(self):
        source = (Path(__file__).resolve().parent / 'admin' / 'control-center.js').read_text()
        self.assertIn('alertData.actionable', source)
        self.assertIn('seen=new Set(actionable.map', source)
        self.assertIn("security-alert-actionable", source)
        self.assertIn("alertData.delivery", source)
        self.assertIn("relay.retry", source)
        self.assertIn("lastFailure.reason", source)
        self.assertIn("b.textContent='Acquitter'", source)

class SecurityAlertDeliveryResilienceTest(unittest.TestCase):
    def _paths(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        return temp, root, root / 'security.sqlite3'

    def test_init_db_migrates_legacy_delivery_columns(self):
        temp, root, db_path = self._paths()
        self.addCleanup(temp.cleanup)
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TABLE security_alerts(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              level TEXT NOT NULL,
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT '',
              fingerprint TEXT NOT NULL DEFAULT '',
              dedup_key TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              acknowledged INTEGER NOT NULL DEFAULT 0,
              delivered INTEGER NOT NULL DEFAULT 0
            )""")
        with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path):
            alerts.init_db()
            with sqlite3.connect(db_path) as db:
                columns = {row[1] for row in db.execute('PRAGMA table_info(security_alerts)')}
        self.assertTrue(set(alerts._DELIVERY_COLUMNS).issubset(columns))

    def test_failed_delivery_persists_sanitized_error_and_backoff(self):
        temp, root, db_path = self._paths()
        self.addCleanup(temp.cleanup)
        now = datetime.datetime(2026, 9, 20, 4, 0, tzinfo=datetime.timezone.utc)
        ready = {'configured': True, 'ready': True, 'state': 'ready', 'signed': True}
        with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path), \
             mock.patch.object(alerts, '_utcnow', return_value=now), \
             mock.patch.object(alerts, 'delivery_status', return_value=ready), \
             mock.patch.object(alerts, '_deliver', side_effect=alerts.requests.Timeout('credential=secret-value')):
            result = alerts.emit('high', 'probe', 'Delivery probe', cooldown=0)
            report = alerts.summary()
        self.assertTrue(result['deliveryAttempted'])
        self.assertFalse(result['delivered'])
        failure = report['delivery']['retry']['lastFailure']
        self.assertEqual(failure['reason'], 'timeout')
        self.assertEqual(failure['attempts'], 1)
        self.assertEqual(failure['nextAttemptAt'], '2026-09-20T04:01:00+00:00')
        self.assertEqual(report['delivery']['retry']['deferred'], 1)
        with sqlite3.connect(db_path) as db:
            stored = db.execute(
                'SELECT last_delivery_error FROM security_alerts WHERE id=?',
                (result['id'],),
            ).fetchone()[0]
        self.assertNotIn('secret-value', stored)

    def test_retry_pending_respects_backoff_then_delivers(self):
        temp, root, db_path = self._paths()
        self.addCleanup(temp.cleanup)
        start = datetime.datetime(2026, 9, 20, 4, 0, tzinfo=datetime.timezone.utc)
        ready = {'configured': True, 'ready': True, 'state': 'ready', 'signed': True}
        with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path), \
             mock.patch.object(alerts, 'delivery_status', return_value=ready), \
             mock.patch.object(alerts, '_utcnow', return_value=start), \
             mock.patch.object(alerts, '_deliver', side_effect=alerts.requests.ConnectionError('private detail')):
            alert_id = alerts.emit('critical', 'probe', 'Retry probe', cooldown=0)['id']
        before_due = start + datetime.timedelta(seconds=30)
        with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path), \
             mock.patch.object(alerts, 'delivery_status', return_value=ready), \
             mock.patch.object(alerts, '_utcnow', return_value=before_due), \
             mock.patch.object(alerts, '_deliver', return_value=True) as deliver:
            deferred = alerts.retry_pending()
            deliver.assert_not_called()
        self.assertEqual(deferred['attempted'], 0)
        self.assertEqual(deferred['deferred'], 1)
        after_due = start + datetime.timedelta(seconds=61)
        with mock.patch.object(alerts, 'STATE_DIR', root), mock.patch.object(alerts, 'DB', db_path), \
             mock.patch.object(alerts, 'delivery_status', return_value=ready), \
             mock.patch.object(alerts, '_utcnow', return_value=after_due), \
             mock.patch.object(alerts, '_deliver', return_value=True):
            retried = alerts.retry_pending()
        self.assertEqual(retried['attempted'], 1)
        self.assertEqual(retried['delivered'], 1)
        with sqlite3.connect(db_path) as db:
            row = db.execute(
                'SELECT delivered,delivery_attempts,last_delivery_error,next_delivery_attempt_at '
                'FROM security_alerts WHERE id=?',
                (alert_id,),
            ).fetchone()
        self.assertEqual(row, (1, 2, '', ''))

    def test_delivery_backoff_is_exponential_and_capped(self):
        self.assertEqual(alerts._delivery_backoff_seconds(1), 60)
        self.assertEqual(alerts._delivery_backoff_seconds(2), 120)
        self.assertEqual(alerts._delivery_backoff_seconds(7), 3600)
        self.assertEqual(alerts._delivery_backoff_seconds(20), 3600)


if __name__ == '__main__':
    unittest.main()
