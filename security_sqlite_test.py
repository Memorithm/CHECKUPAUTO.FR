"""#733/#735: Sentinel SQLite stays writable while other workers read."""
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

import security_behavior
import security_sqlite


class SecuritySqliteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'security.sqlite3'
        security_sqlite._WAL_READY.discard(str(self.db))

    def tearDown(self):
        security_sqlite._WAL_READY.discard(str(self.db))
        self.tmp.cleanup()

    def _mountinfo(self, kind):
        path = Path(self.tmp.name) / f'mountinfo-{kind}'
        path.write_text(
            '22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n'
            f'40 22 0:41 / {self.tmp.name} rw,relatime shared:9 - {kind} srv:/x rw\n'
        )
        return str(path)

    def test_filesystem_detection_uses_deepest_mount(self):
        self.assertTrue(security_sqlite.wal_allowed(self.db, self._mountinfo('xfs')))
        self.assertFalse(security_sqlite.wal_allowed(self.db, self._mountinfo('nfs4')))
        self.assertFalse(security_sqlite.wal_allowed(self.db, self._mountinfo('fuse.sshfs')))

    def test_env_switch_disables_wal(self):
        with mock.patch.dict(os.environ, {'CHECKUPAUTO_SQLITE_WAL': '0'}):
            self.assertFalse(security_sqlite.wal_allowed(self.db, self._mountinfo('ext4')))

    def test_network_filesystem_keeps_rollback_journal(self):
        with mock.patch.object(security_sqlite, 'wal_allowed', return_value=False):
            with security_sqlite.transaction(self.db) as db:
                mode = db.execute('PRAGMA journal_mode').fetchone()[0]
        self.assertEqual(mode.lower(), 'delete')

    def test_reader_in_other_connection_does_not_block_commit(self):
        with mock.patch.object(security_sqlite, 'wal_allowed', return_value=True):
            with security_sqlite.transaction(self.db) as db:
                db.execute('CREATE TABLE t(v)')
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')
            reader = sqlite3.connect(self.db, isolation_level=None)
            try:
                reader.execute('BEGIN')
                reader.execute('SELECT COUNT(*) FROM t').fetchone()
                started = time.monotonic()
                with security_sqlite.transaction(self.db) as db:
                    db.execute('INSERT INTO t VALUES(1)')
                self.assertLess(time.monotonic() - started, 1.0)
            finally:
                reader.close()

    def test_transaction_closes_connection(self):
        with security_sqlite.transaction(self.db) as db:
            handle = db
        with self.assertRaises(sqlite3.ProgrammingError):
            handle.execute('SELECT 1')


class BehaviorSchemaOnceTest(unittest.TestCase):
    def test_persist_initializes_schema_once_per_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'security.sqlite3'
            state = {'requests': [], 'responses': [], 'paths': [], 'last_persist': 0.0}
            with mock.patch.object(security_behavior, 'STATE_DIR', Path(tmp)), \
                    mock.patch.object(security_behavior, 'DB', db), \
                    mock.patch.object(security_behavior, '_SCHEMA_READY', set()), \
                    mock.patch.object(security_behavior, 'init_db', wraps=security_behavior.init_db) as init:
                for _ in range(3):
                    security_behavior._persist('fp', 'client', state, 0.0, force=True)
            self.assertEqual(init.call_count, 1)
            with sqlite3.connect(db) as check:
                self.assertEqual(check.execute('SELECT COUNT(*) FROM behavior_profiles').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
