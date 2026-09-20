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
        self.assertIn("b.textContent='Acquitter'", source)

if __name__ == '__main__':
    unittest.main()
