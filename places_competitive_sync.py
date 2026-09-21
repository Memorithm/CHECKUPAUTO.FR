from __future__ import annotations

from pathlib import Path
import datetime
import hashlib
import json
import math
import os
import unicodedata

import requests

import competitive_intelligence as competitive
import geo_marketing
import integration_hub

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.rating,places.userRatingCount,places.businessStatus,places.googleMapsUri"
)
SUCCESS_CADENCE_HOURS = 24
RETRY_CADENCE_HOURS = 6
PAGE_SIZE = 20
TIMEOUT_SECONDS = 20


def _state_file() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "places-competitive-sync.json"


def _now(now=None) -> datetime.datetime:
    value = now or datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _iso(value: datetime.datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_iso(value) -> datetime.datetime | None:
    try:
        parsed = datetime.datetime.fromisoformat(str(value or ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def _read_state() -> dict:
    path = _state_file()
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    temp.chmod(0o600)
    temp.replace(path)


def _api_key() -> str:
    try:
        configured = str((integration_hub.settings() or {}).get("mapsApiKey") or "").strip()
    except Exception:
        configured = ""
    return configured or str(os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()


def _fold(value) -> str:
    return " ".join(
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .split()
    )


def _existing_competitor_id(name: str, address: str) -> str | None:
    folded_name = _fold(name)
    folded_address = _fold(address)
    with competitive.connect() as db:
        rows = db.execute("SELECT id,name,address FROM competitors WHERE active=1").fetchall()
    for row in rows:
        if folded_name and _fold(row["name"]) == folded_name:
            return str(row["id"])
        if folded_address and _fold(row["address"]) == folded_address:
            return str(row["id"])
    return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a))))


def _due(state: dict, now: datetime.datetime) -> bool:
    attempted = _parse_iso(state.get("lastAttemptAt"))
    if attempted is None:
        return True
    cadence = SUCCESS_CADENCE_HOURS if state.get("verification") == "verified" else RETRY_CADENCE_HOURS
    return now - attempted >= datetime.timedelta(hours=cadence)


def _persist_attempt(now: datetime.datetime, verification: str, imported: int = 0) -> None:
    state = {
        "schemaVersion": 1,
        "lastAttemptAt": _iso(now),
        "verification": verification,
        "imported": max(0, int(imported)),
    }
    previous = _read_state()
    if verification == "verified":
        state["lastSuccessAt"] = _iso(now)
    elif previous.get("lastSuccessAt"):
        state["lastSuccessAt"] = previous["lastSuccessAt"]
    _write_state(state)


def _record_place(place: dict, rank: int, center: dict, radius_km: float, captured_at: str) -> bool:
    place_id = str(place.get("id") or "").strip()
    display = place.get("displayName") if isinstance(place.get("displayName"), dict) else {}
    name = str(display.get("text") or "").strip()
    address = str(place.get("formattedAddress") or "").strip()
    location = place.get("location") if isinstance(place.get("location"), dict) else {}
    try:
        lat = float(location["latitude"])
        lon = float(location["longitude"])
        distance = _distance_km(float(center["latitude"]), float(center["longitude"]), lat, lon)
    except (KeyError, TypeError, ValueError):
        return False
    if not place_id or not name or distance > radius_km + 1e-9:
        return False

    cid = _existing_competitor_id(name, address)
    if cid is None:
        cid = "places-" + hashlib.sha256(place_id.encode()).hexdigest()[:16]
    competitive.upsert_competitor(cid, name, address, distance_km=round(distance, 3), is_self=(cid == "checkup-auto"))

    source_url = str(place.get("googleMapsUri") or "").strip()
    snapshot = {
        "placeId": place_id,
        "searchRank": int(rank),
        "businessStatus": str(place.get("businessStatus") or ""),
        "distanceKm": round(distance, 3),
    }
    rating = place.get("rating")
    rating_count = place.get("userRatingCount")
    if isinstance(rating, (int, float)):
        snapshot["rating"] = float(rating)
    if isinstance(rating_count, int) and rating_count >= 0:
        snapshot["userRatingCount"] = rating_count
    competitive.add_observation(cid, "google-places", "google_places_snapshot", snapshot, source_url, captured_at)
    if "rating" in snapshot:
        competitive.add_observation(
            cid,
            "google-places",
            "reviews_summary",
            {"rating": snapshot["rating"], "reviewCount": snapshot.get("userRatingCount", 0)},
            source_url,
            captured_at,
        )
    return True


def sync_once(force: bool = False, now=None) -> dict:
    current = _now(now)
    key = _api_key()
    if not key:
        return {"ok": True, "state": "not_configured", "configured": False, "queried": False, "imported": 0}

    state = _read_state()
    if not force and not _due(state, current):
        return {
            "ok": True,
            "state": "not_due",
            "configured": True,
            "queried": False,
            "imported": 0,
            "verification": str(state.get("verification") or "unverified"),
        }

    catalog = geo_marketing.catalog()
    center = catalog.get("center") if isinstance(catalog.get("center"), dict) else {}
    radius_km = min(50.0, max(0.1, float(catalog.get("radiusKm") or 50.0)))
    body = {
        "textQuery": "contrôle technique automobile",
        "pageSize": PAGE_SIZE,
        "languageCode": "fr",
        "regionCode": "FR",
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": float(center["latitude"]),
                    "longitude": float(center["longitude"]),
                },
                "radius": radius_km * 1000.0,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    try:
        response = requests.post(PLACES_SEARCH_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException:
        _persist_attempt(current, "unavailable")
        return {"ok": False, "state": "unavailable", "configured": True, "queried": True, "imported": 0}

    if response.status_code != 200:
        verification = "unavailable" if response.status_code == 429 or response.status_code >= 500 else "failed"
        _persist_attempt(current, verification)
        return {
            "ok": False,
            "state": verification,
            "configured": True,
            "queried": True,
            "imported": 0,
            "httpStatus": int(response.status_code),
        }

    try:
        payload = response.json()
    except ValueError:
        _persist_attempt(current, "failed")
        return {"ok": False, "state": "failed", "configured": True, "queried": True, "imported": 0}
    places = payload.get("places") if isinstance(payload, dict) else None
    if not isinstance(places, list):
        _persist_attempt(current, "failed")
        return {"ok": False, "state": "failed", "configured": True, "queried": True, "imported": 0}

    captured_at = _iso(current)
    imported = 0
    for rank, place in enumerate(places[:PAGE_SIZE], start=1):
        if isinstance(place, dict) and _record_place(place, rank, center, radius_km, captured_at):
            imported += 1
    _persist_attempt(current, "verified", imported)
    return {
        "ok": True,
        "state": "verified",
        "configured": True,
        "queried": True,
        "imported": imported,
        "returned": min(len(places), PAGE_SIZE),
    }
