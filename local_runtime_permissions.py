#!/usr/bin/env python3
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import stat
import subprocess


def _checkout_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir() or root.is_symlink() or root == Path('/'):
        raise ValueError('runtime checkout invalide')
    proc = subprocess.run(
        ['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError('runtime checkout non Git')
    try:
        top = Path(proc.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise ValueError('runtime checkout Git invalide') from exc
    if top != root:
        raise ValueError('la racine demandée n’est pas la racine Git')
    return root


def _tracked_entries(root: Path) -> list[tuple[str, Path]]:
    payload = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-s', '-z'],
    )
    entries: list[tuple[str, Path]] = []
    for raw in payload.split(b'\0'):
        if not raw:
            continue
        try:
            meta, encoded = raw.split(b'\t', 1)
            mode = meta.split(b' ', 1)[0].decode('ascii')
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError('entrée Git index invalide') from exc
        relative = Path(encoded.decode('utf-8', 'surrogateescape'))
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('entrée Git hors racine refusée')
        entries.append((mode, root / relative))
    return entries


def _tracked_parents(root: Path, entries: list[tuple[str, Path]]) -> set[Path]:
    parents = {root}
    for _mode, path in entries:
        parent = path.parent
        while True:
            parents.add(parent)
            if parent == root:
                break
            if root not in parent.parents:
                raise RuntimeError('répertoire parent hors racine refusé')
            parent = parent.parent
    return parents


def normalize_checkout_permissions(
    checkout_root: str | Path,
    service_group: str,
) -> dict:
    """Grant the service group only the read/traverse bits required by Git-tracked code.

    Git records the executable bit, but not group-read permissions. A checkout recreated
    under a restrictive umask can therefore become unreadable by a non-root systemd
    service even though the Git tree itself is unchanged. This function repairs only
    Git-tracked files and their working-tree parent directories; it never traverses
    .git, private runtime state, untracked files, or symlink targets.
    """
    root = _checkout_root(checkout_root)
    group = str(service_group or '').strip()
    if not group:
        raise ValueError('groupe service manquant')
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError as exc:
        raise ValueError('groupe service inconnu') from exc

    entries = _tracked_entries(root)
    parents = _tracked_parents(root, entries)

    directory_count = 0
    for directory in sorted(parents, key=lambda path: len(path.parts)):
        if not directory.exists() or directory.is_symlink():
            continue
        info = directory.stat()
        os.chown(directory, -1, gid)
        os.chmod(directory, stat.S_IMODE(info.st_mode) | stat.S_IRGRP | stat.S_IXGRP)
        directory_count += 1

    file_count = 0
    symlink_count = 0
    for mode, path in entries:
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or mode == '120000':
            symlink_count += 1
            continue
        if not path.is_file():
            raise RuntimeError('objet Git suivi inattendu')
        info = path.stat()
        required = stat.S_IRGRP
        if mode == '100755':
            required |= stat.S_IXGRP
        os.chown(path, -1, gid)
        os.chmod(path, stat.S_IMODE(info.st_mode) | required)
        file_count += 1

    result = verify_checkout_permissions(root, group)
    if not result['ok']:
        raise RuntimeError('normalisation permissions incomplète')
    return {
        'ok': True,
        'group': group,
        'trackedFiles': file_count,
        'trackedDirectories': directory_count,
        'trackedSymlinks': symlink_count,
    }


def verify_checkout_permissions(
    checkout_root: str | Path,
    service_group: str,
) -> dict:
    root = _checkout_root(checkout_root)
    group = str(service_group or '').strip()
    if not group:
        raise ValueError('groupe service manquant')
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError as exc:
        raise ValueError('groupe service inconnu') from exc

    entries = _tracked_entries(root)
    parents = _tracked_parents(root, entries)
    failures: list[str] = []

    for directory in parents:
        if not directory.exists() or directory.is_symlink():
            continue
        info = directory.stat()
        mode = stat.S_IMODE(info.st_mode)
        if info.st_gid != gid or not (mode & stat.S_IXGRP):
            failures.append(str(directory.relative_to(root) or '.'))

    for git_mode, path in entries:
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or git_mode == '120000':
            continue
        info = path.stat()
        mode = stat.S_IMODE(info.st_mode)
        readable = bool(mode & stat.S_IRGRP)
        executable = git_mode != '100755' or bool(mode & stat.S_IXGRP)
        if info.st_gid != gid or not readable or not executable:
            failures.append(str(path.relative_to(root)))

    return {
        'ok': not failures,
        'group': group,
        'failureCount': len(failures),
        # Paths are repository-relative code paths only; never include private state.
        'failures': sorted(failures)[:50],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='CheckupAuto local runtime checkout permission guard',
    )
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('normalize', 'verify'):
        command = sub.add_parser(name)
        command.add_argument('--root', required=True)
        command.add_argument('--group', required=True)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        if args.command == 'normalize':
            result = normalize_checkout_permissions(args.root, args.group)
        else:
            result = verify_checkout_permissions(args.root, args.group)
        print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
        return 0 if result.get('ok') else 3
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            'ok': False,
            'error': type(exc).__name__,
            'detail': str(exc),
        }, ensure_ascii=False, separators=(',', ':')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
