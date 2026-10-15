"""Per-process, per-database SQLite schema initialization gate.

Explicit schema migrations stay in the original init_db() methods. Ordinary
account and OAuth traffic must not issue CREATE TABLE / BEGIN IMMEDIATE on
every hit: this previously serialized session reads and OAuth starts on
PlanetHoster. This gate is an in-memory hint, NOT an authorization decision.

On a replacement/deleted database, or a worker fork, initialization reruns;
a stale/missing table fails closed through the normal SQL error path.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import threading


class SchemaOnce:
    def __init__(self):
        self._lock = threading.RLock()
        self._identity = None

    @staticmethod
    def _key(path):
        path = Path(path)
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                return None
            return (os.getpid(), str(path.absolute()), info.st_dev, info.st_ino)
        except OSError:
            return None

    def ensure(self, path, initializer):
        key = self._key(path)
        if key is not None and self._identity == key:
            return
        with self._lock:
            key = self._key(path)
            if key is not None and self._identity == key:
                return
            self._identity = None
            initializer()
            key = self._key(path)
            if key is None:
                raise RuntimeError("customer_schema_unavailable")
            self._identity = key
