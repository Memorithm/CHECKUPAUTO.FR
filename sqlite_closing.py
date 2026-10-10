"""Connexion SQLite fermée à la sortie du bloc ``with`` (audit Q-03).

``with sqlite3.connect(...) as db`` valide ou annule la transaction mais ne
ferme pas la connexion : le descripteur reste ouvert jusqu'au ramasse-miettes,
ce qui fuit des descripteurs dans le serveur longue durée. Passer
``factory=ClosingConnection`` à ``sqlite3.connect`` conserve la sémantique
transactionnelle et ferme ensuite la connexion.
"""

from __future__ import annotations

import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()
