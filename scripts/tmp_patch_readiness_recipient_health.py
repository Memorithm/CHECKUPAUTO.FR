from pathlib import Path

path = Path("production_readiness.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        '''    "notification_broker": {
        "code": "restore_notification_broker",
        "summary": "Fermer les circuits défaillants et traiter les échecs permanents après correction du transport concerné.",
        "verify": "Aucun circuit ouvert et aucun échec permanent dans NotificationBroker.",
        "target": "#notifications",
        "external": False,
    },''',
        '''    "notification_broker": {
        "code": "restore_notification_broker",
        "summary": "Fermer les circuits défaillants, traiter les échecs permanents et rétablir un rapprochement Mercure récent.",
        "verify": "Aucun circuit ouvert, aucun échec permanent actif et aucun contrôle destinataire périmé ou en échec.",
        "target": "#notifications",
        "external": False,
    },''',
    ),
    (
        '''        permanent_resolved = int(resilience.get("permanentResolved") or 0)
        broker_degraded = circuits > 0 or permanent_failures > 0
''',
        '''        permanent_resolved = int(resilience.get("permanentResolved") or 0)
        recipient_checks = resilience.get("recipientChecks") or {}
        recipient_tracked = int(recipient_checks.get("tracked") or 0)
        recipient_fresh = int(recipient_checks.get("fresh") or 0)
        recipient_stale = int(recipient_checks.get("stale") or 0)
        recipient_unchecked = int(recipient_checks.get("unchecked") or 0)
        recipient_changed = int(recipient_checks.get("changed") or 0)
        recipient_lookup_failed = int(recipient_checks.get("lookupFailed") or 0)
        recipient_stale_after = int(recipient_checks.get("staleAfterSeconds") or 0)
        recipient_reconciliation_degraded = recipient_tracked > 0 and (
            recipient_stale > 0 or recipient_lookup_failed > 0
        )
        broker_degraded = circuits > 0 or permanent_failures > 0 or recipient_reconciliation_degraded
''',
    ),
    (
        '''        if circuits and permanent_failures:
            broker_detail = f"{circuits} circuit(s) ouvert(s), {permanent_failures} échec(s) permanent(s) à traiter"
        elif circuits:
            broker_detail = f"{circuits} circuit(s) ouvert(s)"
        elif permanent_failures:
            broker_detail = f"{permanent_failures} échec(s) permanent(s) à traiter"
        elif permanent_acknowledged:
            broker_detail = f"Broker opérationnel · {permanent_acknowledged} incident(s) permanent(s) acquitté(s)"
        else:
            broker_detail = "Broker et ledger opérationnels"
''',
        '''        broker_issues = []
        if circuits:
            broker_issues.append(f"{circuits} circuit(s) ouvert(s)")
        if permanent_failures:
            broker_issues.append(f"{permanent_failures} échec(s) permanent(s) à traiter")
        if recipient_stale:
            broker_issues.append(f"{recipient_stale} contrôle(s) destinataire périmé(s)")
        if recipient_lookup_failed:
            broker_issues.append(f"{recipient_lookup_failed} contrôle(s) Mercure en échec")
        if broker_issues:
            broker_detail = " · ".join(broker_issues)
        elif permanent_acknowledged:
            broker_detail = f"Broker opérationnel · {permanent_acknowledged} incident(s) permanent(s) acquitté(s)"
        else:
            broker_detail = "Broker et ledger opérationnels"
''',
    ),
    (
        '''                "permanentResolved": permanent_resolved,
            },
''',
        '''                "permanentResolved": permanent_resolved,
                "recipientChecksTracked": recipient_tracked,
                "recipientChecksFresh": recipient_fresh,
                "recipientChecksStale": recipient_stale,
                "recipientChecksUnchecked": recipient_unchecked,
                "recipientCorrectionsDetected": recipient_changed,
                "recipientLookupFailed": recipient_lookup_failed,
                "recipientChecksStaleAfterSeconds": recipient_stale_after,
            },
''',
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"guard_failed: expected one match, found {count}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
