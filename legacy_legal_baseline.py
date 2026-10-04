from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "legal" / "legacy-rdv"
MANIFEST = BASE / "manifest.json"

META = {
    "legal_notice": {
        "title": "Mentions Légales",
        "slug": "/mentions-legales",
        "version": "legacy-rdv-2026-10-04",
    },
    "privacy": {
        "title": "Politiques de Confidentialités",
        "slug": "/confidentialite",
        "version": "legacy-rdv-2026-10-04",
    },
    "cookies": {
        "title": "Cookies et technologies similaires",
        "slug": "/cookies",
        "version": "legacy-rdv-2026-10-04",
    },
    "terms": {
        "title": "Conditions Générales de Vente",
        "slug": "/cgv",
        "version": "mercureweb-2022-legacy",
    },
    "withdrawal": {
        "title": "Rétractation",
        "slug": "/retractation",
        "version": "mercureweb-2022-legacy",
    },
}


def _manifest() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema") != "checkupauto.legacy-legal-baseline/v1":
        raise RuntimeError("legacy legal manifest schema invalid")
    return data


def _plain(text: str) -> str:
    rows = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = line.replace("**", "").replace("\\*", "*")
        if line.strip() == "---":
            rows.append("")
            continue
        rows.append(line)
    out = "\n".join(rows)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def document(doc_type: str) -> dict | None:
    if doc_type not in META:
        return None
    manifest = _manifest()
    entry = (manifest.get("documents") or {}).get(doc_type) or {}
    rel = str(entry.get("file") or "")
    sources = [str(x) for x in entry.get("sources") or []]
    if not rel or not sources:
        raise RuntimeError("legacy legal provenance incomplete")
    target = (ROOT / rel).resolve()
    base = BASE.resolve()
    if target.parent != base or not target.is_file() or target.is_symlink():
        raise RuntimeError("legacy legal source invalid")
    body = _plain(target.read_text(encoding="utf-8"))
    if len(body) < 80:
        raise RuntimeError("legacy legal body invalid")
    meta = META[doc_type]
    return {
        "type": doc_type,
        "label": meta["title"],
        "slug": meta["slug"],
        "version": meta["version"],
        "title": meta["title"],
        "body": body,
        "contentHash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "status": "legacy_baseline",
        "createdAt": "",
        "publishedAt": "",
        "legacyBaseline": True,
        "legacyCapturedAt": str(manifest.get("capturedAt") or ""),
        "legacySources": sources,
    }


def all_documents() -> dict[str, dict]:
    return {kind: document(kind) for kind in META}
