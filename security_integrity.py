from __future__ import annotations

from pathlib import Path
import datetime
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import threading

ROOT = Path(__file__).resolve().parent
STATE_DIR = Path('/root/CyberCheckSecurity')
BASELINE = STATE_DIR / 'integrity-baseline.json'
LATEST = STATE_DIR / 'integrity-latest.json'
SBOM = STATE_DIR / 'sbom-python.json'
_STOP = threading.Event()
_THREAD = None

CRITICAL_FILES = (
    'admin_server.py', 'security_guard.py', 'security_ai.py', 'security_integrity.py',
    'booking_bridge.py', 'mercure_admin_client.py', 'mercure_public_client.py',
    'geo_marketing.py', 'analytics_store.py', 'gsc_client.py', 'index.html',
    'app.js', 'style.css', 'admin/index.html', 'admin/admin.js',
    'admin/control-center.js', 'admin/gsc-admin.js', 'admin/admin.css',
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _snapshot() -> dict:
    files = {}
    for rel in CRITICAL_FILES:
        p = ROOT / rel
        if p.is_file():
            st = p.stat()
            files[rel] = {'sha256': _sha256(p), 'size': st.st_size}
        else:
            files[rel] = {'missing': True}
    return {'generatedAt': _now(), 'files': files}


def create_baseline(force=False):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    if BASELINE.exists() and not force:
        return json.loads(BASELINE.read_text())
    data = _snapshot()
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    BASELINE.chmod(0o600)
    return data


def scan() -> dict:
    baseline = create_baseline(False)
    current = _snapshot()
    changed, missing, added = [], [], []
    before = baseline.get('files', {})
    now = current.get('files', {})
    for rel, meta in before.items():
        cur = now.get(rel, {'missing': True})
        if cur.get('missing'):
            missing.append(rel)
        elif meta.get('sha256') != cur.get('sha256'):
            changed.append({'path': rel, 'before': meta.get('sha256', '')[:12], 'after': cur.get('sha256', '')[:12]})
    for rel in now:
        if rel not in before:
            added.append(rel)
    result = {
        'generatedAt': _now(), 'baselineAt': baseline.get('generatedAt'),
        'ok': not changed and not missing and not added,
        'protectedFiles': len(before), 'changed': changed, 'missing': missing, 'added': added,
    }
    LATEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    LATEST.chmod(0o600)
    return result


def generate_sbom() -> dict:
    components = []
    for dist in importlib.metadata.distributions():
        name = (dist.metadata.get('Name') or '').strip()
        if name:
            components.append({'type': 'library', 'name': name, 'version': dist.version})
    components.sort(key=lambda x: x['name'].lower())
    result = {
        'bomFormat': 'CycloneDX-like', 'specVersion': '1.6-minimal',
        'generatedAt': _now(), 'runtime': {'python': platform.python_version(), 'executable': sys.executable},
        'componentCount': len(components), 'components': components,
    }
    SBOM.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    SBOM.chmod(0o600)
    return result


def posture() -> dict:
    integrity = scan()
    sbom = generate_sbom()
    private = ROOT / 'private'
    exposed_backups = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('.bak-' in p.name or p.suffix in {'.old', '.orig'})]
    permission_issues = []
    for p in [STATE_DIR, private]:
        if p.exists() and (p.stat().st_mode & 0o077):
            permission_issues.append(str(p))
    for p in private.glob('*') if private.exists() else []:
        if p.is_file() and (p.stat().st_mode & 0o077):
            permission_issues.append(str(p))
    return {
        'integrity': integrity,
        'sbom': {'componentCount': sbom['componentCount'], 'generatedAt': sbom['generatedAt']},
        'webrootBackupFiles': len(exposed_backups), 'backupSamples': exposed_backups[:10],
        'permissionIssues': permission_issues,
        'ok': integrity['ok'] and not permission_issues,
    }


def _loop(interval):
    while not _STOP.wait(interval):
        try:
            scan()
        except Exception:
            pass


def start(interval=120):
    global _THREAD
    create_baseline(False)
    generate_sbom()
    scan()
    if _THREAD and _THREAD.is_alive():
        return
    _THREAD = threading.Thread(target=_loop, args=(max(60, int(interval)),), daemon=True, name='CyberCheckIntegrity')
    _THREAD.start()


def stop():
    _STOP.set()
