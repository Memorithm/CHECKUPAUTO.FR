#!/usr/bin/env python3
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATHS = (
    re.compile(r'(^|/)private/'),
    re.compile(r'(^|/)\.admin-password$'),
    re.compile(r'(^|/)\.env(?:\.|$)'),
    re.compile(r'\.(?:sqlite3?|db|log|p8)$', re.I),
    re.compile(r'mercure-admin-session\.json$', re.I),
    re.compile(r'mercure-webhook-secret$', re.I),
)
SECRET_PATTERNS = (
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('service-account-key', re.compile(r'"private_key"\s*:\s*"-----BEGIN')),
    ('github-token', re.compile(r'\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b')),
    ('openai-key', re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b')),
    ('php-session', re.compile(r'PHPSESSID\s*[=:]\s*[A-Za-z0-9_-]{12,}', re.I)),
)
def tracked_files():
    out = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files'], text=True)
    return [x.strip() for x in out.splitlines() if x.strip()]


def scan():
    findings = []
    for rel in tracked_files():
        if any(p.search(rel) for p in FORBIDDEN_PATHS):
            findings.append(f'forbidden-path: {rel}')
            continue
        path = ROOT / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b'\x00' in raw[:8192] or len(raw) > 2_000_000:
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f'{name}: {rel}')
    return findings
def main():
    findings = scan()
    if findings:
        print('Security pre-commit check failed:', file=sys.stderr)
        for item in findings:
            print(' - ' + item, file=sys.stderr)
        return 1
    print('Security pre-commit check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
