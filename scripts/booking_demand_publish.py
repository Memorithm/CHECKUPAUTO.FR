#!/usr/bin/env python3
"""Auditable, bounded RemoteOps entry point for Mercure promotions."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import booking_demand
import mercure_admin_client
import mercure_public_client
import site_config_store


def execute(mode: str):
    policy = (site_config_store.load().get("incentives") or {})
    if mode == "diagnose":
        today = mercure_admin_client.business_today()
        target = (today + dt.timedelta(days=1)).isoformat()
        history = booking_demand.snapshot()
        availability = {
            key: mercure_public_client.availability(key, target)
            for key in ("technical", "fitted")
            if policy.get("eligibleServices", {}).get(key, False)
        }
        choices = booking_demand.candidate_slots(
            history, policy, availability, today)
        return {
            "status": "read_only", "historyDays": history["historyDays"],
            "aggregatedAppointments": sum(history["totals"].values()),
            "candidateCount": len(choices),
            "candidateSlots": [{
                "service": item["service"], "date": item["date"],
                "time": item["time"], "finalPrice": item["finalPrice"],
            } for item in choices],
        }
    if mode not in {"canary", "routine"}:
        raise ValueError("invalid publisher mode")
    limit = 1 if mode == "canary" else booking_demand.MAX_NEW_PROMOTIONS_PER_RUN
    return booking_demand.run_once(policy, max_new_promotions=limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["diagnose", "canary", "routine"],
                        default="diagnose")
    args = parser.parse_args(argv)
    try:
        result = execute(args.mode)
    except Exception as exc:
        print(json.dumps({"status": "unavailable",
                          "errorType": type(exc).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] in {
        "read_only", "verified", "no_candidates", "no_new_offers"
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
