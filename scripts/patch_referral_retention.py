from pathlib import Path

path = Path("retention_enforcement.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "import privacy_suppression\nimport reminder_dispatch\n",
        "import privacy_suppression\nimport referral_engine\nimport reminder_dispatch\n",
    ),
    (
        '        "legalReviewRequired": True,\n        "implementationRequired": True,\n    },\n}\n',
        '        "legalReviewRequired": True,\n    },\n}\n',
    ),
    (
        "\ndef _run_configurable_rule(\n",
        "\ndef _compact_referral_ledger(days: int, *, dry_run: bool) -> int:\n"
        "    result = referral_engine.compact_ledger(days, dry_run=dry_run)\n"
        "    if not bool(result.get(\"ok\")):\n"
        "        raise RuntimeError(\"Compaction parrainage non confirmée\")\n"
        "    skipped = int(result.get(\"skippedEntries\") or 0)\n"
        "    if skipped:\n"
        "        raise RuntimeError(\"Compaction parrainage incomplète\")\n"
        "    compacted = int(result.get(\"compactedEntries\") or 0)\n"
        "    if compacted < 0:\n"
        "        raise RuntimeError(\"Compaction parrainage incohérente\")\n"
        "    return compacted\n\n\n"
        "def _run_configurable_rule(\n",
    ),
    (
        '    if rule_id == "rights_requests_and_audit":\n'
        '        return _purge_rights_evidence(days, dry_run=dry_run, db_path=db_path)\n'
        '    raise NotImplementedError(rule_id)\n',
        '    if rule_id == "rights_requests_and_audit":\n'
        '        return _purge_rights_evidence(days, dry_run=dry_run, db_path=db_path)\n'
        '    if rule_id == "referral_ledger":\n'
        '        return _compact_referral_ledger(days, dry_run=dry_run)\n'
        '    raise NotImplementedError(rule_id)\n',
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one replacement, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
