from __future__ import annotations

from pathlib import Path
import datetime
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import threading
import subprocess
import uuid
from urllib.parse import quote
import requests
import security_alerts as alerts

ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get('CYBERCHECK_SECURITY_DIR', '/root/CyberCheckSecurity'))
INTEGRITY_DIR = Path(os.environ.get('CYBERCHECK_INTEGRITY_DIR', '/root/CyberCheckIntegrity'))
BASELINE = INTEGRITY_DIR / 'integrity-baseline.json'
LATEST = STATE_DIR / 'integrity-latest.json'
SBOM = STATE_DIR / 'sbom.cdx.json'
VULN_AUDIT = STATE_DIR / 'vulnerability-audit.json'
ALERT_STATE = STATE_DIR / 'integrity-alert-state.json'
_STOP = threading.Event()
_THREAD = None

CRITICAL_FILES = (
    'admin_server.py','migration_write_freeze.py','security_guard.py','security_behavior.py','security_alerts.py','security_ai.py','security_integrity.py',
    'booking_bridge.py','booking_test.py','competitive_intelligence.py','review_followup.py','mercure_admin_client.py','mercure_public_client.py','geo_marketing.py','analytics_store.py','gsc_client.py',
    'index.html','app.js','style.css','admin/index.html','admin/admin.js','admin/control-center.js','admin/gsc-admin.js','admin/competitive.js','admin/review-followup.js','admin/admin.css',
    'data/geo-radius-50.01km.json','requirements.txt','.gitignore','README.md','SECURITY.md',
    'deploy/cybercheck.service','deploy/cybercheck-ollama.service','deploy/rebaseline-integrity.sh',
    'scripts/precommit_security.py',
    'assets/vehicle.png','assets/vehicle.mp4',
    'assets/premium/vehicle-peugeot208-premium.webp','assets/premium/vehicle-suv4x4-premium.webp',
    'assets/premium/vehicle-utility-premium.webp','assets/premium/vehicle-ambulance-premium.webp','assets/premium/vehicle-foodtruck-premium.webp',
    '3d/scripts/setup_reference_scene.py',
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def git_state() -> dict:
    try:
        head=subprocess.run(['git','-c',f'safe.directory={ROOT}','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True,timeout=4,check=True).stdout.strip()
        branch=subprocess.run(['git','-c',f'safe.directory={ROOT}','-C',str(ROOT),'rev-parse','--abbrev-ref','HEAD'],capture_output=True,text=True,timeout=4,check=True).stdout.strip()
        status=subprocess.run(['git','-c',f'safe.directory={ROOT}','-C',str(ROOT),'status','--porcelain','--untracked-files=no'],capture_output=True,text=True,timeout=4,check=True).stdout.splitlines()
        changed=[line[3:] if len(line)>3 else line for line in status if line.strip()]
        return {'available':True,'head':head,'branch':branch,'dirty':bool(changed),'changedTracked':changed[:80]}
    except Exception as exc:
        return {'available':False,'error':type(exc).__name__,'head':'','branch':'','dirty':None,'changedTracked':[]}


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "").strip()).lower()


def _parse_requirement_line(raw: str) -> dict | None:
    line = str(raw or "").split("#", 1)[0].strip()
    if not line:
        return None
    requirement = line.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[([^]]+)\])?", requirement)
    if not match:
        return {'name': requirement, 'extras': [], 'required': '', 'pinned': False, 'requirement': requirement}
    name = match.group(1)
    extras = sorted({x.strip() for x in (match.group(2) or '').split(',') if x.strip()})
    pinned = '==' in requirement
    version = requirement.split('==', 1)[1].strip() if pinned else ''
    return {'name': name, 'extras': extras, 'required': version, 'pinned': pinned, 'requirement': requirement}


def dependency_state() -> dict:
    required = []
    req = ROOT / 'requirements.txt'
    for raw in req.read_text().splitlines() if req.exists() else []:
        parsed = _parse_requirement_line(raw)
        if parsed:
            required.append(parsed)
    installed = {
        _canonical_distribution_name(d.metadata.get('Name', '')): d.version
        for d in importlib.metadata.distributions()
        if d.metadata.get('Name')
    }
    rows = []
    missing = []
    mismatched = []
    unpinned = []
    for item in required:
        name = item['name']
        version = item['required']
        pinned = item['pinned']
        actual = installed.get(_canonical_distribution_name(name))
        row = {**item, 'installed': actual, 'ok': bool(actual) and (not pinned or actual == version)}
        rows.append(row)
        if not actual:
            missing.append(item['requirement'])
        elif pinned and actual != version:
            mismatched.append({'name': name, 'requirement': item['requirement'], 'required': version, 'installed': actual})
        if not pinned:
            unpinned.append(item['requirement'])
    return {'ok': not missing and not mismatched and not unpinned,
            'requirements': rows, 'missing': missing, 'mismatched': mismatched, 'unpinned': unpinned}


def _component_fingerprint(components: list[dict]) -> str:
    rows = sorted(
        f"{_canonical_distribution_name(c.get('name', ''))}=={c.get('version', '')}"
        for c in components
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _snapshot() -> dict:
    files = {}
    for rel in CRITICAL_FILES:
        p = ROOT / rel
        if p.is_file():
            st = p.stat()
            files[rel] = {'sha256': _sha256(p), 'size': st.st_size}
        else:
            files[rel] = {'missing': True}
    return {'generatedAt':_now(),'files':files,'git':git_state()}


def create_baseline(force=False):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try: STATE_DIR.chmod(0o700)
    except PermissionError: pass
    if BASELINE.exists() and not force:
        return json.loads(BASELINE.read_text())
    if not force:
        raise RuntimeError('Baseline d’intégrité absente : provisionnement root requis')
    INTEGRITY_DIR.mkdir(parents=True, exist_ok=True)
    data = _snapshot()
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    BASELINE.chmod(0o640)
    return data


def _integrity_alert(result: dict):
    material=json.dumps({
      'changed':result.get('changed',[]),'missing':result.get('missing',[]),'added':result.get('added',[]),
      'gitDirty':result.get('gitDirty',False),'gitHeadChanged':result.get('gitHeadChanged',False),
      'gitHead':(result.get('git') or {}).get('head','')},sort_keys=True)
    fingerprint=hashlib.sha256(material.encode()).hexdigest() if not result.get('ok') else ''
    previous={}
    if ALERT_STATE.exists():
        try: previous=json.loads(ALERT_STATE.read_text())
        except Exception: previous={}
    old=previous.get('fingerprint','')
    if fingerprint!=old:
        paths=[x.get('path') for x in result.get('changed',[])] + result.get('missing',[]) + result.get('added',[])
        try:
            import security_guard
            if fingerprint: security_guard.system_event('integrity_mismatch',100,'alert',','.join(str(x) for x in paths[:5]) or 'git-state')
            elif old: security_guard.system_event('integrity_restored',0,'info','-')
        except Exception: pass
        try:
            if fingerprint:
                alerts.emit('critical','integrity','Intégrité du déploiement modifiée',
                            ', '.join(str(x) for x in paths[:8]) or 'État Git différent de la baseline',
                            metadata={'git':result.get('git',{}),'gitHeadChanged':result.get('gitHeadChanged'),'gitDirty':result.get('gitDirty')},
                            dedup_key='integrity:'+fingerprint,cooldown=0)
            elif old:
                alerts.emit('info','integrity_restored','Intégrité du déploiement restaurée','Baseline conforme',dedup_key='integrity-restored:'+old,cooldown=0)
        except Exception: pass
        ALERT_STATE.write_text(json.dumps({'fingerprint':fingerprint,'updatedAt':_now()},indent=2)+'\n'); ALERT_STATE.chmod(0o600)


def scan() -> dict:
    baseline=create_baseline(False); current=_snapshot()
    changed=[]; missing=[]; added=[]
    before=baseline.get('files',{}); now=current.get('files',{})
    for rel,meta in before.items():
        cur=now.get(rel,{'missing':True})
        if cur.get('missing'): missing.append(rel)
        elif meta.get('sha256')!=cur.get('sha256'):
            changed.append({'path':rel,'before':meta.get('sha256','')[:12],'after':cur.get('sha256','')[:12]})
    for rel in now:
        if rel not in before: added.append(rel)
    git=current.get('git') or {}; base_git=baseline.get('git') or {}
    git_head_changed=bool(git.get('available') and base_git.get('head') and git.get('head')!=base_git.get('head'))
    git_dirty=bool(git.get('dirty'))
    result={'generatedAt':_now(),'baselineAt':baseline.get('generatedAt'),'baselineGitHead':base_git.get('head',''),
            'git':git,'gitHeadChanged':git_head_changed,'gitDirty':git_dirty,
            'ok':not changed and not missing and not added and not git_head_changed and not git_dirty,
            'protectedFiles':len(before),'changed':changed,'missing':missing,'added':added}
    LATEST.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); LATEST.chmod(0o600)
    _integrity_alert(result); return result


def rebaseline():
    git=git_state()
    if not git.get('available'):
        raise RuntimeError('Git indisponible : recalage de baseline refusé')
    if git.get('dirty'):
        raise RuntimeError('Dépôt Git modifié : commit/push requis avant recalage de baseline')
    data=create_baseline(True)
    try:
        alerts.resolve_after_rebaseline()
        alerts.emit('info','integrity_baseline','Baseline d’intégrité mise à jour',data.get('git',{}).get('head',''),cooldown=0)
    except Exception: pass
    return scan()


def generate_sbom() -> dict:
    components=[]
    for dist in importlib.metadata.distributions():
        name=(dist.metadata.get('Name') or '').strip()
        if not name: continue
        version=str(dist.version); purl=f"pkg:pypi/{quote(name.lower())}@{quote(version)}"
        components.append({'type':'library','bom-ref':purl,'name':name,'version':version,'purl':purl})
    components.sort(key=lambda x:x['name'].lower())
    git=git_state(); app_version=(git.get('head') or 'working-tree')[:12]
    serial=uuid.uuid5(uuid.NAMESPACE_URL,'https://github.com/Memorithm/CHECKUPAUTO.FR').urn
    result={
      'bomFormat':'CycloneDX','specVersion':'1.6','serialNumber':serial,'version':1,
      'metadata':{
        'timestamp':_now(),
        'tools':{'components':[{'type':'application','name':'CyberCheck Sentinel SBOM generator','version':'1.0'}]},
        'component':{'type':'application','bom-ref':'pkg:generic/checkupauto.fr@'+app_version,
                     'name':'CHECKUPAUTO.FR','version':app_version},
        'properties':[{'name':'cybercheck.python.version','value':platform.python_version()},
                      {'name':'cybercheck.git.branch','value':str(git.get('branch') or '')}]},
      'components':components
    }
    SBOM.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); SBOM.chmod(0o600)
    result['componentCount']=len(components); result['generatedAt']=result['metadata']['timestamp']
    return result


def audit_vulnerabilities(force=False) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    sbom = generate_sbom()
    component_fingerprint = _component_fingerprint(sbom['components'])
    if VULN_AUDIT.exists() and not force:
        age = datetime.datetime.now(datetime.timezone.utc).timestamp() - VULN_AUDIT.stat().st_mtime
        if age < 86400:
            try:
                cached = json.loads(VULN_AUDIT.read_text())
                if cached.get('componentFingerprint') == component_fingerprint:
                    return cached
            except Exception:
                pass
    queries = [{'package': {'name': c['name'], 'ecosystem': 'PyPI'}, 'version': c['version']} for c in sbom['components']]
    try:
        r = requests.post('https://api.osv.dev/v1/querybatch', json={'queries': queries}, timeout=25)
        r.raise_for_status()
        raw = r.json().get('results', [])
        findings = []
        for comp, result in zip(sbom['components'], raw):
            for vuln in (result or {}).get('vulns', []) or []:
                findings.append({
                    'component': comp['name'], 'version': comp['version'],
                    'id': vuln.get('id'), 'aliases': (vuln.get('aliases') or [])[:8],
                    'modified': vuln.get('modified'), 'summary': (vuln.get('summary') or '')[:240],
                })
        data = {'generatedAt': _now(), 'source': 'OSV.dev', 'componentCount': len(queries),
                'vulnerabilityCount': len(findings), 'affectedComponents': len({x['component'] for x in findings}),
                'findings': findings[:100], 'ok': not findings, 'componentFingerprint': component_fingerprint}
    except Exception as exc:
        if VULN_AUDIT.exists():
            try:
                cached = json.loads(VULN_AUDIT.read_text())
                if cached.get('componentFingerprint') == component_fingerprint:
                    cached['stale'] = True
                    cached['refreshError'] = type(exc).__name__
                    return cached
            except Exception:
                pass
        data = {'generatedAt': _now(), 'source': 'OSV.dev', 'componentCount': len(queries),
                'vulnerabilityCount': None, 'affectedComponents': None, 'findings': [], 'ok': None, 'error': type(exc).__name__, 'componentFingerprint': component_fingerprint}
    VULN_AUDIT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    VULN_AUDIT.chmod(0o600)
    if isinstance(data.get('vulnerabilityCount'),int) and data['vulnerabilityCount']>0:
        ids=','.join(str(x.get('id')) for x in data.get('findings',[])[:8])
        try: alerts.emit('high','dependency_vulnerability','Vulnérabilités connues dans les dépendances',
                         f"{data['vulnerabilityCount']} vulnérabilité(s) / {data.get('affectedComponents',0)} composant(s): {ids}",
                         metadata={'source':'OSV.dev','affectedComponents':data.get('affectedComponents')},
                         dedup_key='osv:'+hashlib.sha256(ids.encode()).hexdigest()[:16],cooldown=86400)
        except Exception: pass
    return data


def posture() -> dict:
    integrity=scan(); sbom=generate_sbom(); vuln=audit_vulnerabilities(False); deps=dependency_state()
    recovered_alerts = alerts.resolve_recovered_dependencies(
        dependencies_ok=bool(deps.get('ok')),
        vulnerability_count=vuln.get('vulnerabilityCount'),
    )
    private=Path(os.environ.get('CYBERCHECK_PRIVATE_DIR','/root/CyberCheckPrivate'))
    exposed_backups=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('.bak-' in p.name or p.suffix in {'.old','.orig'})]
    permission_issues=[]
    if STATE_DIR.exists() and (STATE_DIR.stat().st_mode & 0o077):
        permission_issues.append(str(STATE_DIR))
    if private.exists():
        mode=private.stat().st_mode & 0o777
        if (mode & 0o007) or (mode & 0o020):
            permission_issues.append(str(private))
    for p in private.glob('*') if private.exists() else []:
        if p.is_file():
            mode=p.stat().st_mode & 0o777
            if (mode & 0o007) or (mode & 0o020):
                permission_issues.append(str(p))
    if BASELINE.exists():
        mode=BASELINE.stat().st_mode & 0o777
        if (mode & 0o007) or (mode & 0o020) or not (mode & 0o040):
            permission_issues.append(str(BASELINE))
    if not deps.get('ok'):
        try: alerts.emit('high','dependency_drift','Dérive des dépendances Python',json.dumps({k:deps.get(k) for k in ('missing','mismatched','unpinned')},ensure_ascii=False),
                         dedup_key='dependency-drift',cooldown=3600)
        except Exception: pass
    return {
      'integrity':integrity,
      'git':integrity.get('git',{}),
      'dependencies':deps,
      'sbom':{'format':'CycloneDX','specVersion':'1.6','componentCount':sbom['componentCount'],'generatedAt':sbom['generatedAt'],'path':str(SBOM)},
      'vulnerabilities':{'count':vuln.get('vulnerabilityCount'),'affectedComponents':vuln.get('affectedComponents'),'generatedAt':vuln.get('generatedAt'),'source':vuln.get('source'),'stale':bool(vuln.get('stale')),'findings':vuln.get('findings',[])[:20]},
      'webrootBackupFiles':len(exposed_backups),'backupSamples':exposed_backups[:10],
      'permissionIssues':permission_issues,
      'recoveredAlerts':recovered_alerts,
      'ok':integrity['ok'] and deps.get('ok',False) and not permission_issues
    }


def _loop(interval):
    while not _STOP.wait(interval):
        try:
            scan()
        except Exception:
            pass


def start(interval=60):
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
