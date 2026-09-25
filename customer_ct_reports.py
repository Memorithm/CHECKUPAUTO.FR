"""Private CT report ingestion for authenticated customer accounts.

Raw uploads are processed in a temporary directory and discarded. Only an
encrypted structured payload + Markdown representation is retained.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import unicodedata
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import ct_advisor

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_EXTRACTED_CHARS = 120_000
MAX_PDF_PAGES = 8
ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
AAD_PREFIX = b"checkupauto-ct-report-v1\x00"


class CTReportError(ValueError):
    pass


def db_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "customer-ct-reports.sqlite3"


def _key_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / "customer" / "reports.key"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _account_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise CTReportError("ct_account_invalid") from exc
    if str(parsed) != raw:
        raise CTReportError("ct_account_invalid")
    return raw


def _report_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise CTReportError("ct_report_id_invalid") from exc
    if str(parsed) != raw:
        raise CTReportError("ct_report_id_invalid")
    return raw


def _ensure_key() -> bytes:
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    if path.is_symlink():
        raise RuntimeError("ct_report_key_invalid")
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(secrets.token_bytes(32))
            handle.flush()
            os.fsync(handle.fileno())
    try:
        path.chmod(0o600)
    except PermissionError:
        pass
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        key = handle.read(33)
    if len(key) != 32:
        raise RuntimeError("ct_report_key_invalid")
    return key


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS customer_ct_report(
              report_id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL,
              document_hash TEXT NOT NULL,
              content_type TEXT NOT NULL,
              payload_blob BLOB NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(account_id,document_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_customer_ct_report_account
              ON customer_ct_report(account_id,created_at);
            """
        )
    try:
        db_path().chmod(0o600)
    except PermissionError:
        pass


def _encrypt(account_id: str, report_id: str, payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > 512_000:
        raise CTReportError("ct_report_payload_too_large")
    nonce = secrets.token_bytes(12)
    aad = AAD_PREFIX + account_id.encode("ascii") + b"\x00" + report_id.encode("ascii")
    return nonce + AESGCM(_ensure_key()).encrypt(nonce, raw, aad)


def _decrypt(row) -> dict:
    account_id = str(row["account_id"])
    report_id = str(row["report_id"])
    raw = bytes(row["payload_blob"])
    aad = AAD_PREFIX + account_id.encode("ascii") + b"\x00" + report_id.encode("ascii")
    try:
        clear = AESGCM(_ensure_key()).decrypt(raw[:12], raw[12:], aad)
        payload = json.loads(clear.decode("utf-8"))
    except Exception:
        raise RuntimeError("ct_report_unreadable") from None
    if not isinstance(payload, dict):
        raise RuntimeError("ct_report_unreadable")
    return payload


def _run(args: list[str], *, timeout: int) -> bytes:
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CTReportError("ct_extraction_unavailable") from None
    if result.returncode != 0:
        raise CTReportError("ct_extraction_failed")
    return result.stdout


def _magic_valid(content_type: str, raw: bytes) -> bool:
    if content_type == "application/pdf":
        return raw.startswith(b"%PDF-")
    if content_type == "image/jpeg":
        return len(raw) >= 3 and raw[:3] == bytes((0xFF, 0xD8, 0xFF))
    if content_type == "image/png":
        return raw.startswith(bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)))
    return False


def _pdf_pages(path: Path) -> int:
    info = _run(["pdfinfo", str(path)], timeout=12).decode("utf-8", errors="replace")
    match = re.search(r"^Pages:\s+(\d+)\s*$", info, flags=re.MULTILINE)
    if not match:
        raise CTReportError("ct_report_pdf_invalid")
    pages = int(match.group(1))
    if not 1 <= pages <= MAX_PDF_PAGES:
        raise CTReportError("ct_report_pages_invalid")
    return pages


def _ocr_image(path: Path) -> str:
    raw = _run(
        ["tesseract", str(path), "stdout", "-l", "fra+eng", "--psm", "6"],
        timeout=35,
    )
    return raw.decode("utf-8", errors="replace")


def extract_text(raw: bytes, content_type: object) -> tuple[str, str]:
    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    suffix = ALLOWED_TYPES.get(content_type)
    if not suffix:
        raise CTReportError("ct_report_type_invalid")
    if not isinstance(raw, (bytes, bytearray)) or not 1 <= len(raw) <= MAX_UPLOAD_BYTES:
        raise CTReportError("ct_report_size_invalid")
    raw = bytes(raw)
    if not _magic_valid(content_type, raw):
        raise CTReportError("ct_report_signature_invalid")

    with tempfile.TemporaryDirectory(prefix="checkupauto-ct-") as tmp:
        source = Path(tmp) / ("report" + suffix)
        source.write_bytes(raw)
        if content_type != "application/pdf":
            text = _ocr_image(source)
            method = "tesseract-fra-eng"
        else:
            pages = _pdf_pages(source)
            text = _run(["pdftotext", "-layout", str(source), "-"], timeout=25).decode(
                "utf-8", errors="replace"
            )
            if len(re.sub(r"\s+", "", text)) >= 180:
                method = "pdf-text"
            else:
                prefix = Path(tmp) / "page"
                _run(
                    [
                        "pdftoppm", "-jpeg", "-r", "220", "-f", "1", "-l", str(pages),
                        str(source), str(prefix),
                    ],
                    timeout=45,
                )
                pages = sorted(Path(tmp).glob("page-*.jpg"))
                if not pages:
                    raise CTReportError("ct_extraction_failed")
                text = "\n\n".join(_ocr_image(page) for page in pages)
                method = "pdf-ocr-tesseract-fra-eng"
    text = unicodedata.normalize("NFC", text).replace("\x00", "")
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS]
    if len(re.sub(r"\s+", "", text)) < 40:
        raise CTReportError("ct_extraction_empty")
    return text, method


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).upper()


def _field(patterns: tuple[str, ...], text: str, value_pattern: str) -> str:
    for label in patterns:
        match = re.search(
            rf"{label}\s*[:\-]?\s*({value_pattern})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return " ".join(match.group(1).strip().split())
    return ""


def parse_report(text: str) -> dict:
    normalized = unicodedata.normalize("NFC", str(text or ""))
    lines = [" ".join(line.strip().split()) for line in normalized.splitlines()]
    lines = [line for line in lines if line]

    severity = "non classée"
    defects: list[dict] = []
    code_re = re.compile(r"\b(\d+(?:\.\d+){2}\.[A-Za-z]\.\d+)\b")
    stop_labels = (
        "IDENTIFICATION", "IMMATRICULATION", "KILOMETRAGE", "DATE DU CONTROLE",
        "RESULTAT", "CONTRE-VISITE", "NUMERO DU PROCES", "PROCES-VERBAL",
    )
    for line in lines:
        folded = _fold(line)
        if "DEFAILLANCES CRITIQUES" in folded:
            severity = "critique"
            continue
        if "DEFAILLANCES MAJEURES" in folded:
            severity = "majeure"
            continue
        if "DEFAILLANCES MINEURES" in folded:
            severity = "mineure"
            continue
        match = code_re.search(line)
        if match:
            description = line[match.end():].strip(" :-–—")
            defects.append({
                "code": match.group(1).lower(),
                "severity": severity,
                "description": description[:600],
            })
            continue
        if defects and not any(label in folded for label in stop_labels):
            # OCR often wraps one finding across two lines.
            if len(line) <= 300 and not re.search(r"\b\d{2}/\d{2}/\d{4}\b", line):
                previous = defects[-1]["description"]
                if previous and len(previous) + len(line) < 600:
                    defects[-1]["description"] = (previous + " " + line).strip()

    folded_all = _fold(normalized)
    if "DEFAVORABLE" in folded_all:
        result = "défavorable"
    elif re.search(r"\bFAVORABLE\b", folded_all):
        result = "favorable"
    else:
        result = "non détecté"

    registration = _field(
        (r"IMMATRICULATION", r"NUM[ÉE]RO D[' ]IMMATRICULATION"),
        normalized,
        r"[A-Z0-9][A-Z0-9 -]{4,18}",
    ).replace(" ", "")
    vin = _field(
        (r"VIN", r"NUM[ÉE]RO DANS LA S[ÉE]RIE DU TYPE"),
        normalized,
        r"[A-HJ-NPR-Z0-9]{17}",
    ).replace(" ", "")
    control_date = _field(
        (r"DATE DU CONTR[ÔO]LE", r"DATE DE CONTR[ÔO]LE"),
        normalized,
        r"\d{2}[/-]\d{2}[/-]\d{4}",
    )
    mileage_raw = _field(
        (r"KILOM[ÉE]TRAGE RELEV[ÉE]", r"KILOM[ÉE]TRAGE"),
        normalized,
        r"[0-9][0-9 .]{0,12}",
    )
    mileage_digits = re.sub(r"\D", "", mileage_raw)
    mileage = int(mileage_digits) if mileage_digits else None

    return {
        "result": result,
        "registration": registration[:20],
        "vin": vin[:17],
        "controlDate": control_date,
        "mileageKm": mileage,
        "defects": defects[:200],
    }


def render_markdown(structured: dict, advice: list[dict], *, extraction_method: str) -> str:
    defects = structured["defects"]
    out = [
        "# Rapport de contrôle technique — Checkup Auto",
        "",
        "> Document structuré automatiquement à partir du rapport fourni par le client.",
        "> La gravité réglementaire reste celle du procès-verbal original.",
        "",
        "## Synthèse",
        "",
        f"- Résultat détecté : **{structured['result']}**",
        f"- Date du contrôle : {structured['controlDate'] or 'non détectée'}",
        f"- Immatriculation : {structured['registration'] or 'non détectée'}",
        f"- VIN : {structured['vin'] or 'non détecté'}",
        f"- Kilométrage : {str(structured['mileageKm']) + ' km' if structured['mileageKm'] is not None else 'non détecté'}",
        f"- Extraction : {extraction_method}",
        f"- Agent conseil : {ct_advisor.ADVISOR_VERSION}",
        "",
        "## Défaillances structurées",
        "",
    ]
    if defects:
        out.extend([
            "| Code | Gravité du rapport | Description |",
            "| --- | --- | --- |",
        ])
        for item in defects:
            desc = str(item["description"]).replace("|", "\\|")
            out.append(f"| {item['code']} | {item['severity']} | {desc} |")
    else:
        out.append("Aucune défaillance codifiée n’a pu être structurée automatiquement.")

    out.extend(["", "## Lecture préventive", "", ct_advisor.summary(defects), ""])
    for index, item in enumerate(advice, start=1):
        out.extend([
            f"### {index}. {item['title']}",
            "",
            f"- Code CT associé : {item['code'] or 'non identifié'}",
            f"- Gravité lue sur le rapport : {item['severity']}",
            f"- Explication : {item['explanation']}",
            f"- Contexte de gravité : {item['severityContext']}",
            f"- Prévention : {item['prevention']}",
            "",
        ])
    out.extend([
        "## Limites",
        "",
        "Cette analyse aide à préparer l’entretien. Elle ne remplace ni le procès-verbal réglementaire, "
        "ni un diagnostic mécanique, ni les consignes d’un réparateur qualifié.",
        "",
    ])
    return "\n".join(out)


def _public(row, payload: dict, *, include_markdown: bool) -> dict:
    structured = payload["structured"]
    result = {
        "reportId": str(row["report_id"]),
        "contentType": str(row["content_type"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
        "result": structured.get("result", ""),
        "controlDate": structured.get("controlDate", ""),
        "registration": structured.get("registration", ""),
        "mileageKm": structured.get("mileageKm"),
        "defectCount": len(structured.get("defects") or []),
        "structured": structured if include_markdown else None,
        "advice": payload.get("advice") if include_markdown else None,
        "advisorVersion": payload.get("advisorVersion"),
        "rawDocumentRetained": False,
    }
    if include_markdown:
        result["markdown"] = str(payload.get("markdown") or "")
    return result


def ingest(account_id: object, filename: object, content_type: object, raw: bytes) -> dict:
    account_id = _account_id(account_id)
    content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise CTReportError("ct_report_type_invalid")
    name = Path(str(filename or "rapport")).name[:160]
    if not name or name in {".", ".."}:
        name = "rapport"
    if not isinstance(raw, (bytes, bytearray)) or not 1 <= len(raw) <= MAX_UPLOAD_BYTES:
        raise CTReportError("ct_report_size_invalid")
    raw = bytes(raw)
    if not _magic_valid(content_type, raw):
        raise CTReportError("ct_report_signature_invalid")
    document_hash = hashlib.sha256(raw).hexdigest()
    init_db()
    with _connect() as db:
        existing = db.execute(
            "SELECT * FROM customer_ct_report WHERE account_id=? AND document_hash=?",
            (account_id, document_hash),
        ).fetchone()
        if existing:
            return _public(existing, _decrypt(existing), include_markdown=True)

    text, method = extract_text(raw, content_type)
    structured = parse_report(text)
    advice = ct_advisor.advise(structured["defects"])
    markdown = render_markdown(structured, advice, extraction_method=method)
    report_id = str(uuid.uuid4())
    now = _now_iso()
    payload = {
        "schemaVersion": 1,
        "sourceName": name,
        "extractionMethod": method,
        "structured": structured,
        "advice": advice,
        "advisorVersion": ct_advisor.ADVISOR_VERSION,
        "markdown": markdown,
        "extractedText": text,
    }
    encrypted = _encrypt(account_id, report_id, payload)
    with _connect() as db:
        db.execute(
            """INSERT INTO customer_ct_report(
                 report_id,account_id,document_hash,content_type,payload_blob,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (report_id, account_id, document_hash, content_type, encrypted, now, now),
        )
        row = db.execute(
            "SELECT * FROM customer_ct_report WHERE report_id=?",
            (report_id,),
        ).fetchone()
    return _public(row, payload, include_markdown=True)


def list_reports(account_id: object) -> list[dict]:
    account_id = _account_id(account_id)
    init_db()
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM customer_ct_report WHERE account_id=? ORDER BY created_at DESC LIMIT 50",
            (account_id,),
        ).fetchall()
    return [_public(row, _decrypt(row), include_markdown=False) for row in rows]


def get_report(account_id: object, report_id: object) -> dict:
    account_id = _account_id(account_id)
    report_id = _report_id(report_id)
    init_db()
    with _connect() as db:
        row = db.execute(
            "SELECT * FROM customer_ct_report WHERE account_id=? AND report_id=?",
            (account_id, report_id),
        ).fetchone()
    if not row:
        raise CTReportError("ct_report_not_found")
    return _public(row, _decrypt(row), include_markdown=True)


def delete_report(account_id: object, report_id: object) -> bool:
    account_id = _account_id(account_id)
    report_id = _report_id(report_id)
    init_db()
    with _connect() as db:
        cursor = db.execute(
            "DELETE FROM customer_ct_report WHERE account_id=? AND report_id=?",
            (account_id, report_id),
        )
    return bool(cursor.rowcount)
