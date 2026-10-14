"""Connexion partagée à ``security.sqlite3`` (issues #733 / #735).

Sous Passenger, plusieurs processus écrivent dans la même base Sentinel à
chaque requête (profils comportementaux, état client, événements >= 400).
En journal ``DELETE`` (mode par défaut), chaque validation exige un verrou
exclusif qui attend la fin de toutes les lectures des autres workers ; avec
le délai par défaut de 5 s de ``sqlite3.connect``, un worker froid qui
initialise le schéma pendant le trafic obtient ``SQLITE_BUSY`` et Passenger
répond 503.

Le mode WAL laisse les lectures et l'écriture avancer en parallèle ; seules
deux écritures se sérialisent, pendant quelques millisecondes. WAL exige une
mémoire partagée locale : il n'est activé que sur un système de fichiers
local reconnu, et ``CHECKUPAUTO_SQLITE_WAL=0`` le désactive. Le chemin de la
base n'est jamais journalisé.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import threading

from sqlite_closing import ClosingConnection

BUSY_TIMEOUT_SECONDS = 10.0
LOCAL_FILESYSTEMS = frozenset({
    'btrfs', 'ext2', 'ext3', 'ext4', 'f2fs', 'overlay', 'tmpfs', 'xfs', 'zfs',
    'apfs', 'hfs',
})
_WAL_LOCK = threading.Lock()
_WAL_READY: set[str] = set()


def _mount_filesystem(path: Path, mountinfo='/proc/self/mountinfo') -> str:
    """Return the filesystem type of the deepest mount containing ``path``."""
    try:
        target = str(path.resolve())
        best, kind = '', ''
        with open(mountinfo, encoding='utf-8', errors='replace') as stream:
            for line in stream:
                left, sep, right = line.partition(' - ')
                fields = left.split()
                if not sep or len(fields) < 5:
                    continue
                point = fields[4].replace('\\040', ' ')
                inside = target == point or target.startswith(point.rstrip('/') + '/')
                if inside and len(point) >= len(best):
                    best, kind = point, (right.split() or [''])[0]
        return kind
    except OSError:
        return ''


def wal_allowed(path: Path, mountinfo='/proc/self/mountinfo') -> bool:
    if os.environ.get('CHECKUPAUTO_SQLITE_WAL', '').strip() == '0':
        return False
    return _mount_filesystem(Path(path).parent, mountinfo) in LOCAL_FILESYSTEMS


def _enable_wal(connection: sqlite3.Connection, path: Path) -> None:
    key = str(path)
    if key in _WAL_READY:
        return
    with _WAL_LOCK:
        if key in _WAL_READY or not wal_allowed(path):
            return
        try:
            mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]
        except sqlite3.OperationalError:
            # Another worker holds a lock during the one-time switch: keep the
            # current journal and retry on a later connection.
            return
        if str(mode).lower() == 'wal':
            _WAL_READY.add(key)


def connect(path) -> sqlite3.Connection:
    path = Path(path)
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, factory=ClosingConnection)
    try:
        _enable_wal(connection, path)
        if str(path) in _WAL_READY:
            # WAL + NORMAL stays crash-safe for the database; at worst the
            # last Sentinel telemetry commit is lost on power failure.
            connection.execute('PRAGMA synchronous=NORMAL')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(path):
    """One transaction on a connection that is always closed (audit Q-03)."""
    connection = connect(path)
    with connection:
        yield connection
