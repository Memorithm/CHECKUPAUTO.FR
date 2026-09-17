from pathlib import Path
import datetime
import json
import os
import threading
import time

import requests
import security_guard as security
import security_integrity as integrity

STATE_DIR = Path('/root/CyberCheckSecurity')
LATEST = STATE_DIR / 'ai-latest.json'
_STOP = threading.Event()
_THREAD = None


def _baseline(snapshot, posture):
    blocked = int(snapshot.get('blocked', 0))
    active = int(snapshot.get('activeQuarantines', 0))
    top = snapshot.get('topReasons', [])[:5]
    integrity_ok = bool((posture.get('integrity') or {}).get('ok', True))
    severity = 'critical' if not integrity_ok or active >= 5 else ('high' if active or blocked >= 25 else ('elevated' if blocked >= 5 else 'normal'))
    actions = []
    if not integrity_ok:
        actions.append('Vérifier immédiatement les fichiers critiques modifiés avant tout rebaselining.')
    if posture.get('permissionIssues'):
        actions.append('Corriger les permissions des fichiers privés signalés.')
    return {
        'severity': severity,
        'summary': f"{blocked} blocage(s), {active} quarantaine(s) active(s), intégrité {'OK' if integrity_ok else 'ALERTE'}",
        'signals': top,
        'recommendedActions': actions,
        'integrityOk': integrity_ok,
        'modelUsed': False,
    }
def _ollama(snapshot):
    model = os.environ.get('CYBERCHECK_SECURITY_AI_MODEL', '').strip()
    if not model:
        return None
    payload = {
        'model': model,
        'stream': False,
        'format': 'json',
        'prompt': 'Analyse ces métriques de sécurité web. Réponds en JSON avec severity, summary, recommendedActions. Ne propose jamais de commande shell, de contre-attaque ni d’action irréversible. Données: ' + json.dumps({
            'events': snapshot.get('events'),
            'blocked': snapshot.get('blocked'),
            'activeQuarantines': snapshot.get('activeQuarantines'),
            'topReasons': snapshot.get('topReasons', [])[:8],
            'riskClients': snapshot.get('riskClients', [])[:8],
            'integrity': snapshot.get('integrity'),
            'sbom': snapshot.get('sbom'),
        }, ensure_ascii=False),
        'options': {'temperature': 0.1},
    }
    r = requests.post('http://127.0.0.1:11434/api/generate', json=payload, timeout=20)
    r.raise_for_status()
    content = r.json().get('response') or '{}'
    data = json.loads(content)
    data['modelUsed'] = True
    data['model'] = model
    return data


def assess():
    snapshot = security.status(1)
    posture = integrity.posture()
    result = _baseline(snapshot, posture)
    result['posture'] = {
        'protectedFiles': (posture.get('integrity') or {}).get('protectedFiles', 0),
        'changedFiles': len((posture.get('integrity') or {}).get('changed', [])),
        'missingFiles': len((posture.get('integrity') or {}).get('missing', [])),
        'sbomComponents': (posture.get('sbom') or {}).get('componentCount', 0),
    }
    try:
        ai = _ollama({**snapshot, 'integrity': posture.get('integrity'), 'sbom': posture.get('sbom')})
        if isinstance(ai, dict): result.update(ai)
    except Exception as exc:
        result['modelError'] = type(exc).__name__
    result['generatedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    LATEST.chmod(0o600)
    return result
def latest():
    if LATEST.exists():
        try: return json.loads(LATEST.read_text())
        except Exception: pass
    return assess()


def _loop(interval):
    while not _STOP.wait(interval):
        try: assess()
        except Exception: pass


def start(interval=60):
    global _THREAD
    if _THREAD and _THREAD.is_alive(): return
    assess()
    _THREAD = threading.Thread(target=_loop, args=(max(30, int(interval)),), daemon=True, name='CyberCheckSecurityAI')
    _THREAD.start()


def stop():
    _STOP.set()
