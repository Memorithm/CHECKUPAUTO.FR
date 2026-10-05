import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import security_integrity as integrity


class _Dist:
    def __init__(self, name, version):
        self.metadata = {'Name': name}
        self.version = version


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class SecurityIntegrityTest(unittest.TestCase):
    def test_runtime_integrity_does_not_require_dockerignored_source_only_files(self):
        self.assertNotIn(".github/workflows/security-ci.yml", integrity.CRITICAL_FILES)
        self.assertNotIn("3d/blend/CyberCheckVehicle_Photo3D.blend", integrity.CRITICAL_FILES)
        self.assertIn("3d/scripts/setup_reference_scene.py", integrity.CRITICAL_FILES)

    def test_requirement_extras_resolve_to_distribution_name(self):
        parsed = integrity._parse_requirement_line('httpx[http2]==0.28.1')
        self.assertEqual(parsed['name'], 'httpx')
        self.assertEqual(parsed['extras'], ['http2'])
        self.assertEqual(parsed['required'], '0.28.1')
        self.assertTrue(parsed['pinned'])

    def test_dependency_state_accepts_installed_distribution_for_extra(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'requirements.txt').write_text('httpx[http2]==0.28.1\n')
            with mock.patch.object(integrity, 'ROOT', root), mock.patch.object(
                integrity.importlib.metadata, 'distributions', return_value=[_Dist('httpx', '0.28.1')]
            ):
                state = integrity.dependency_state()
        self.assertTrue(state['ok'])
        self.assertEqual(state['missing'], [])
        self.assertEqual(state['requirements'][0]['requirement'], 'httpx[http2]==0.28.1')

    def test_vulnerability_cache_is_reused_only_for_same_components(self):
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / 'audit.json'
            components = [{'name': 'cryptography', 'version': '50.0.1'}]
            fingerprint = integrity._component_fingerprint(components)
            audit.write_text(json.dumps({'componentFingerprint': fingerprint, 'vulnerabilityCount': 0, 'findings': []}))
            with mock.patch.object(integrity, 'STATE_DIR', Path(td)), mock.patch.object(
                integrity, 'VULN_AUDIT', audit
            ), mock.patch.object(
                integrity, 'generate_sbom', return_value={'components': components}
            ), mock.patch.object(integrity.requests, 'post') as post:
                result = integrity.audit_vulnerabilities(False)
        self.assertEqual(result['vulnerabilityCount'], 0)
        post.assert_not_called()

    def test_vulnerability_cache_refreshes_after_dependency_change(self):
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / 'audit.json'
            old = [{'name': 'cryptography', 'version': '48.0.0'}]
            new = [{'name': 'cryptography', 'version': '50.0.1'}]
            audit.write_text(json.dumps({'componentFingerprint': integrity._component_fingerprint(old), 'vulnerabilityCount': 7}))
            response = _Response({'results': [{}]})
            with mock.patch.object(integrity, 'STATE_DIR', Path(td)), mock.patch.object(
                integrity, 'VULN_AUDIT', audit
            ), mock.patch.object(
                integrity, 'generate_sbom', return_value={'components': new}
            ), mock.patch.object(integrity.requests, 'post', return_value=response) as post:
                result = integrity.audit_vulnerabilities(False)
        post.assert_called_once()
        self.assertEqual(result['vulnerabilityCount'], 0)
        self.assertEqual(result['componentFingerprint'], integrity._component_fingerprint(new))

    def test_posture_reconciles_recovered_dependency_alerts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(integrity, 'ROOT', root), mock.patch.object(
                integrity, 'STATE_DIR', root / 'state'
            ), mock.patch.object(
                integrity, 'BASELINE', root / 'baseline.json'
            ), mock.patch.object(
                integrity, 'scan', return_value={'ok': True, 'git': {}}
            ), mock.patch.object(
                integrity, 'generate_sbom', return_value={
                    'componentCount': 0,
                    'generatedAt': '2026-09-20T00:00:00+00:00',
                    'components': [],
                }
            ), mock.patch.object(
                integrity, 'audit_vulnerabilities', return_value={
                    'vulnerabilityCount': 0,
                    'affectedComponents': 0,
                    'generatedAt': '2026-09-20T00:00:00+00:00',
                    'source': 'OSV.dev',
                    'findings': [],
                }
            ), mock.patch.object(
                integrity, 'dependency_state', return_value={'ok': True}
            ), mock.patch.object(
                integrity.alerts,
                'resolve_recovered_dependencies',
                return_value={'ok': True, 'updated': 2, 'kinds': ['dependency_drift', 'dependency_vulnerability']},
            ) as resolve, mock.patch.dict(
                'os.environ',
                {'CYBERCHECK_PRIVATE_DIR': str(root / 'private')},
                clear=False,
            ):
                result = integrity.posture()
        resolve.assert_called_once_with(
            dependencies_ok=True,
            vulnerability_count=0,
        )
        self.assertEqual(result['recoveredAlerts']['updated'], 2)
        self.assertTrue(result['ok'])

    def test_failed_refresh_does_not_reuse_cache_for_old_components(self):
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td) / 'audit.json'
            old = [{'name': 'cryptography', 'version': '48.0.0'}]
            new = [{'name': 'cryptography', 'version': '50.0.1'}]
            audit.write_text(json.dumps({
                'componentFingerprint': integrity._component_fingerprint(old),
                'vulnerabilityCount': 7,
                'findings': [{'component': 'cryptography'}],
            }))
            with mock.patch.object(integrity, 'STATE_DIR', Path(td)), mock.patch.object(
                integrity, 'VULN_AUDIT', audit
            ), mock.patch.object(
                integrity, 'generate_sbom', return_value={'components': new}
            ), mock.patch.object(integrity.requests, 'post', side_effect=RuntimeError('offline')):
                result = integrity.audit_vulnerabilities(False)
        self.assertIsNone(result['vulnerabilityCount'])
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['componentFingerprint'], integrity._component_fingerprint(new))


if __name__ == '__main__':
    unittest.main()
