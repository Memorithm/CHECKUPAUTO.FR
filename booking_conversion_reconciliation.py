from __future__ import annotations

import analytics_store as analytics
import booking_bridge as booking


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
        ).fetchone()["n"]
        without_attribution = db.execute(
            """SELECT COUNT(*) AS n FROM booking_conversions
               WHERE provider=? AND external_id LIKE ? AND attribution_token=''""",
            (booking.PROVIDER, prefix),
        ).fetchone()["n"]
    return {
        "schemaVersion": 1,
        "reconciledRows": int(matched or 0),
        "unresolvedSyntheticRows": int(unresolved or 0),
        "syntheticRowsWithoutAttribution": int(without_attribution or 0),
        "providerIdInferenceUsed": False,
    }
