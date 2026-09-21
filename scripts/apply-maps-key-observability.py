from pathlib import Path

PATH = Path("integration_hub.py")
text = PATH.read_text()

old = '''        elif meta["mode"] == "api_key":
            connected = extra_ok
            state = "connected" if connected else "available"
            detail = "Clé API configurée" if connected else "Clé API requise"
'''
new = '''        elif meta["mode"] == "api_key":
            connected = False
            if extra_ok:
                state = "attention"
                detail = "Clé API configurée · vérification distante non exécutée"
            else:
                state = "available"
                detail = "Clé API requise"
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one api_key status anchor, found {text.count(old)}")
text = text.replace(old, new, 1)

old_row = '''        row = {
            "id": key,
            "label": meta["label"],
            "category": meta["category"],
            "description": meta["description"],
            "mode": meta["mode"],
            "connected": connected,
            "state": state,
            "detail": detail,
            "requiredScopes": list(meta.get("scopes") or []),
        }
'''
new_row = old_row + '''        if meta["mode"] == "api_key" and extra_ok:
            row["verification"] = "unverified"
'''
if text.count(old_row) != 1:
    raise SystemExit(f"expected one connector row anchor, found {text.count(old_row)}")
text = text.replace(old_row, new_row, 1)

PATH.write_text(text)
