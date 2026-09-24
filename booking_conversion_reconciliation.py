from __future__ import annotations

from pathlib import Path
import sqlite3

import analytics_store as analytics
import booking_bridge as booking


def _counts(db: sqlite3.Connection, prefix: str) -> tuple[int, int]:
    unresolved = db.execute(
        """SELECT COUNT(*) AS n
           FROM booking_conversions AS synthetic
           WHERE synthetic.provider=?
             AND synthetic.external_id LIKE ?
             AND synthetic.attribution_token<>''
             AND NOT EXISTS(
               SELECT 1 FROM booking_conversions AS authoritative
               WHERE authoritative.provider=synthetic.provider
                 AND authoritative.attribution_token=synthetic.attribution_token
                 AND authoritative.external_id NOT LIKE ?
             )""",
        (booking.PROVIDER, prefix, prefix),
    ).fetchone()[0]
    without_attribution = db.execute(
        """SELECT COUNT(*) AS n FROM booking_conversions
           WHERE provider=? AND external_id LIKE ? AND attribution_token=''""",
        (booking.PROVIDER, prefix),
    ).fetchone()[0]
    return int(unresolved or 0), int(without_attribution or 0)


def status(db_path: Path | str | None = None) -> dict:
    """Return non-mutating observability for residual browser placeholders.

    A clean local residual count is not proof that Mercure has exposed every
    provider appointment. This status only describes rows currently persisted
    in CheckupAuto's analytics store and never infers a provider identifier.
    """
    path = Path(db_path) if db_path is not None else Path(analytics.DB)
    unavailable = {
        "schemaVersion": 1,
        "available": False,
        "state": "unavailable",
        "unresolvedSyntheticRows": 0,
        "syntheticRowsWithoutAttribution": 0,
        "localResidualRows": 0,
        "providerIdInferenceUsed": False,
        "providerCoverageProven": False,
    }
    try:
        if not path.is_file():
            return unavailable
        uri = path.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='booking_conversions'"
            ).fetchone()
            if table is None:
                return unavailable
            unresolved, without_attribution = _counts(
                db, booking._BROWSER_SYNTHETIC_PREFIX + "%"
            )
        finally:
            db.close()
    except (OSError, sqlite3.Error):
        return unavailable

    residual = unresolved + without_attribution
    return {
        "schemaVersion": 1,
        "available": True,
        "state": "clear" if residual == 0 else "residual",
        "unresolvedSyntheticRows": unresolved,
        "syntheticRowsWithoutAttribution": without_attribution,
        "localResidualRows": residual,
        "providerIdInferenceUsed": False,
        "providerCoverageProven": False,
    }


def process_once() -> dict:
    """Remove legacy browser placeholders only when an authoritative row is proven locally.

    The only linkage used here is the already-derived attribution key persisted by the
    booking bridge. No Mercure appointment id is inferred from a browser route, and
    browser-only rows are intentionally retained.
    """
    prefix = booking._BROWSER_SYNTHETIC_PREFIX + "%"
    with analytics.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        matched = db.execute(
            """SELECT COUNT(*) AS n
               FROM booking_conversions AS synthetic
               WHERE synthetic.provider=?
                 AND synthetic.external_id LIKE ?
                 AND synthetic.attribution_token<>''
                 AND EXISTS(
                   SELECT 1 FROM booking_conversions AS authoritative
                   WHERE authoritative.provider=synthetic.provider
                     AND authoritative.attribution_token=synthetic.attribution_token
                     AND authoritative.external_id NOT LIKE ?
                 )""",
            (booking.PROVIDER, prefix, prefix),
        ).fetchone()["n"]
        if matched:
            db.execute(
                """DELETE FROM booking_conversions AS synthetic
                   WHERE synthetic.provider=?
                     AND synthetic.external_id LIKE ?
                     AND synthetic.attribution_token<>''
                     AND EXISTS(
                       SELECT 1 FROM booking_conversions AS authoritative
                       WHERE authoritative.provider=synthetic.provider
                         AND authoritative.attribution_token=synthetic.attribution_token
                         AND authoritative.external_id NOT LIKE ?
                     )""",
                (booking.PROVIDER, prefix, prefix),
            )
        unresolved, without_attribution = _counts(db, prefix)
    return {
        "schemaVersion": 1,
        "reconciledRows": int(matched or 0),
        "unresolvedSyntheticRows": unresolved,
        "syntheticRowsWithoutAttribution": without_attribution,
        "providerIdInferenceUsed": False,
    }
