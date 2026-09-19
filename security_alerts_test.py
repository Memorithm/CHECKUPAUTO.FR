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


if __name__ == '__main__':
    unittest.main()
