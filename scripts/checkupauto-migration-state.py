#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import uuid
from urllib.parse import quote

SCHEMA_VERSION=1
PURPOSE="planethoster-to-hostinger-cutover"
GROUPS=("data","private","security")
SQLITE_SUFFIXES={".sqlite",".sqlite3",".db"}
SQLITE_MAGIC=b"SQLite format 3\x00"
MAX_MANIFEST_BYTES=4*1024*1024
MAX_FILES=10000


def _sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_file(path: Path) -> bool:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SQLITE_SUFFIXES:
        return False
    with path.open("rb") as handle:
        return handle.read(16)==SQLITE_MAGIC


def _sqlite_backup(source: Path,destination: Path) -> None:
    destination.parent.mkdir(parents=True,exist_ok=True)
    source_uri="file:"+quote(str(source.resolve()),safe="/")+"?mode=ro"
    src=sqlite3.connect(source_uri,uri=True,timeout=15)
    dst=sqlite3.connect(destination,timeout=15)
    try:
        src.backup(dst)
        row=dst.execute("PRAGMA quick_check").fetchone()
        if not row or row[0]!="ok":
            raise RuntimeError("SQLite snapshot quick_check failed")
    finally:
        dst.close()
        src.close()


def _sqlite_quick_check(path: Path) -> None:
    uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
    con=sqlite3.connect(uri,uri=True,timeout=15)
    try:
        row=con.execute("PRAGMA quick_check").fetchone()
        if not row or row[0]!="ok":
            raise RuntimeError("SQLite snapshot invalid")
    finally:
        con.close()


def _freeze_marker(data_root: Path) -> dict:
    marker=data_root/".migration-write-freeze.json"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("migration freeze marker missing")
    raw=marker.read_bytes()
    if not raw or len(raw)>4096:
        raise RuntimeError("migration freeze marker invalid")
    payload=json.loads(raw.decode("utf-8"))
    if not isinstance(payload,dict) or payload.get("schemaVersion")!=1 or payload.get("state")!="frozen":
        raise RuntimeError("migration freeze marker invalid")
    created=str(payload.get("createdAt") or "")
    parsed=dt.datetime.fromisoformat(created)
    if parsed.tzinfo is None:
        raise RuntimeError("migration freeze marker invalid")
    return {"createdAt":parsed.isoformat(timespec="seconds"),"reason":str(payload.get("reason") or "")}


def _safe_relative(value: object) -> PurePosixPath:
    raw=str(value or "")
    path=PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts or "\x00" in raw:
        raise ValueError("relative path invalid")
    return path


def _source_files(root: Path):
    for path in sorted(root.rglob("*"),key=lambda p:p.as_posix()):
        if path.is_symlink():
            raise RuntimeError("snapshot source symlink refused")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError("snapshot source type refused")
        yield path,path.relative_to(root)


def _copy_file(source: Path,destination: Path) -> str:
    destination.parent.mkdir(parents=True,exist_ok=True)
    if _sqlite_file(source):
        _sqlite_backup(source,destination)
        kind="sqlite"
    else:
        shutil.copyfile(source,destination)
        kind="file"
    os.chmod(destination,0o600)
    return kind


def export_snapshot(shared_root: str|Path,output: str|Path,*,now: dt.datetime|None=None) -> dict:
    root=Path(shared_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("shared root invalid")
    root=root.resolve()
    data=(root/"data")
    private=(root/"private")
    if not data.is_dir() or data.is_symlink() or not private.is_dir() or private.is_symlink():
        raise RuntimeError("required shared state missing")
    freeze=_freeze_marker(data)

    out=Path(output).expanduser()
    parent=out.parent.resolve()
    out=(parent/out.name)
    if out.exists() or out.is_symlink():
        raise FileExistsError("snapshot output already exists")
    if out==root or root in out.parents:
        raise ValueError("snapshot output must be outside shared root")
    out.mkdir(mode=0o700)

    entries=[]
    try:
        for group in GROUPS:
            source=root/group
            target=out/group
            target.mkdir(mode=0o700)
            if not source.exists():
                continue
            if source.is_symlink() or not source.is_dir():
                raise RuntimeError("snapshot group invalid")
            for src,relative in _source_files(source):
                if len(entries)>=MAX_FILES:
                    raise RuntimeError("snapshot file limit exceeded")
                dest=target/relative
                kind=_copy_file(src,dest)
                entries.append({
                    "group":group,
                    "relativePath":relative.as_posix(),
                    "kind":kind,
                    "bytes":dest.stat().st_size,
                    "sha256":_sha256(dest),
                })

        freeze_after=_freeze_marker(data)
        if freeze_after["createdAt"]!=freeze["createdAt"]:
            raise RuntimeError("migration freeze changed during snapshot")

        stamp=now or dt.datetime.now(dt.timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError("snapshot timestamp must be timezone-aware")
        manifest={
            "schemaVersion":SCHEMA_VERSION,
            "purpose":PURPOSE,
            "createdAt":stamp.isoformat(timespec="seconds"),
            "sourceFreezeCreatedAt":freeze["createdAt"],
            "groups":list(GROUPS),
            "files":entries,
        }
        raw=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
        if len(raw)>MAX_MANIFEST_BYTES:
            raise RuntimeError("snapshot manifest too large")
        manifest_path=out/"manifest.json"
        manifest_path.write_bytes(raw)
        os.chmod(manifest_path,0o600)
        _secure_tree(out,None,None)
        verified=verify_snapshot(out)
        return {
            "ok":True,
            "snapshot":out.name,
            "fileCount":verified["fileCount"],
            "sqliteCount":verified["sqliteCount"],
            "createdAt":manifest["createdAt"],
        }
    except Exception:
        shutil.rmtree(out,ignore_errors=True)
        raise


def _manifest(snapshot: Path) -> dict:
    path=snapshot/"manifest.json"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("snapshot manifest missing")
    raw=path.read_bytes()
    if not raw or len(raw)>MAX_MANIFEST_BYTES:
        raise RuntimeError("snapshot manifest invalid")
    payload=json.loads(raw.decode("utf-8"))
    if not isinstance(payload,dict):
        raise RuntimeError("snapshot manifest invalid")
    if payload.get("schemaVersion")!=SCHEMA_VERSION or payload.get("purpose")!=PURPOSE:
        raise RuntimeError("snapshot manifest contract mismatch")
    groups=payload.get("groups")
    if groups!=list(GROUPS):
        raise RuntimeError("snapshot groups mismatch")
    files=payload.get("files")
    if not isinstance(files,list) or len(files)>MAX_FILES:
        raise RuntimeError("snapshot file inventory invalid")
    return payload


def verify_snapshot(snapshot: str|Path) -> dict:
    root=Path(snapshot).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("snapshot root invalid")
    root=root.resolve()
    payload=_manifest(root)
    expected=set()
    sqlite_count=0
    for row in payload["files"]:
        if not isinstance(row,dict) or row.get("group") not in GROUPS:
            raise RuntimeError("snapshot inventory row invalid")
        relative=_safe_relative(row.get("relativePath"))
        key=(str(row["group"]),relative.as_posix())
        if key in expected:
            raise RuntimeError("duplicate snapshot path")
        expected.add(key)
        path=root/key[0]/Path(*relative.parts)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("snapshot file missing")
        if path.stat().st_size!=int(row.get("bytes",-1)) or _sha256(path)!=str(row.get("sha256") or ""):
            raise RuntimeError("snapshot file digest mismatch")
        kind=str(row.get("kind") or "")
        if kind=="sqlite":
            if not _sqlite_file(path):
                raise RuntimeError("snapshot sqlite type mismatch")
            _sqlite_quick_check(path)
            sqlite_count+=1
        elif kind!="file":
            raise RuntimeError("snapshot file kind invalid")

    actual=set()
    for group in GROUPS:
        group_root=root/group
        if group_root.is_symlink() or not group_root.is_dir():
            raise RuntimeError("snapshot group missing")
        for path,relative in _source_files(group_root):
            actual.add((group,relative.as_posix()))
    if actual!=expected:
        raise RuntimeError("snapshot contains unmanifested files")
    freeze=_freeze_marker(root/"data")
    if str(payload.get("sourceFreezeCreatedAt") or "")!=freeze["createdAt"]:
        raise RuntimeError("snapshot freeze evidence mismatch")
    return {
        "ok":True,
        "fileCount":len(expected),
        "sqliteCount":sqlite_count,
        "createdAt":str(payload.get("createdAt") or ""),
        "sourceFreezeCreatedAt":freeze["createdAt"],
    }


def _copy_group(source: Path,destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for src,relative in _source_files(source):
        dest=destination/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dest)
        os.chmod(dest,0o600)


def _normalize_hostinger_private(private: Path) -> None:
    legacy=private/"gsc-service-account.json"
    if not legacy.exists():
        return
    if legacy.is_symlink() or not legacy.is_file():
        raise RuntimeError("legacy GSC credentials invalid")
    integrations=private/"integrations"
    integrations.mkdir(mode=0o700,exist_ok=True)
    target=integrations/"gsc-service-account.json"
    if target.exists():
        if target.is_symlink() or not target.is_file() or _sha256(target)!=_sha256(legacy):
            raise RuntimeError("GSC credential migration conflict")
        legacy.unlink()
    else:
        os.replace(legacy,target)
    os.chmod(target,0o600)


def _secure_tree(root: Path,uid: int|None,gid: int|None) -> None:
    for path in sorted(root.rglob("*"),key=lambda p:len(p.parts),reverse=True):
        if path.is_symlink():
            raise RuntimeError("target symlink refused")
        if path.is_dir():
            os.chmod(path,0o700)
        elif path.is_file():
            os.chmod(path,0o600)
        else:
            raise RuntimeError("target type refused")
        if uid is not None or gid is not None:
            os.chown(path,-1 if uid is None else uid,-1 if gid is None else gid)
    os.chmod(root,0o700)
    if uid is not None or gid is not None:
        os.chown(root,-1 if uid is None else uid,-1 if gid is None else gid)


def import_snapshot(snapshot: str|Path,target_root: str|Path,*,uid: int|None=None,gid: int|None=None) -> dict:
    verified=verify_snapshot(snapshot)
    source=Path(snapshot).expanduser().resolve()
    target=Path(target_root).expanduser()
    if target.is_symlink() or not target.is_dir():
        raise ValueError("target state root invalid")
    target=target.resolve()

    token=uuid.uuid4().hex
    incoming=target/(".migration-incoming-"+token)
    previous=target/(".migration-previous-"+token)
    incoming.mkdir(mode=0o700)
    previous.mkdir(mode=0o700)
    swapped=[]
    try:
        for group in GROUPS:
            _copy_group(source/group,incoming/group)
        shutil.copyfile(source/"manifest.json",incoming/"manifest.json")
        os.chmod(incoming/"manifest.json",0o600)
        verify_snapshot(incoming)
        (incoming/"manifest.json").unlink()
        _normalize_hostinger_private(incoming/"private")
        _freeze_marker(incoming/"data")
        _secure_tree(incoming,uid,gid)

        for group in GROUPS:
            current=target/group
            old=previous/group
            had_current=False
            if current.exists():
                if current.is_symlink() or not current.is_dir():
                    raise RuntimeError("target group invalid")
                os.replace(current,old)
                had_current=True
            try:
                os.replace(incoming/group,current)
            except Exception:
                if had_current and old.exists() and not current.exists():
                    os.replace(old,current)
                raise
            swapped.append((group,old,current))

        incoming.rmdir()
        return {
            "ok":True,
            "state":"imported_frozen",
            "fileCount":verified["fileCount"],
            "sqliteCount":verified["sqliteCount"],
            "previousState":previous.name,
            "sourceFreezeCreatedAt":verified["sourceFreezeCreatedAt"],
        }
    except Exception:
        for group,old,current in reversed(swapped):
            if current.exists():
                os.replace(current,incoming/group)
            if old.exists():
                os.replace(old,current)
        shutil.rmtree(incoming,ignore_errors=True)
        if previous.exists() and not any(previous.iterdir()):
            previous.rmdir()
        raise


def _parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="Snapshot/import sécurisé de l'état CheckupAuto PlanetHoster vers Hostinger.")
    sub=parser.add_subparsers(dest="command",required=True)
    export=sub.add_parser("export")
    export.add_argument("--shared-root",required=True)
    export.add_argument("--output",required=True)
    verify=sub.add_parser("verify")
    verify.add_argument("--snapshot",required=True)
    imp=sub.add_parser("import")
    imp.add_argument("--snapshot",required=True)
    imp.add_argument("--target-root",required=True)
    imp.add_argument("--uid",type=int)
    imp.add_argument("--gid",type=int)
    return parser


def main() -> int:
    args=_parser().parse_args()
    try:
        if args.command=="export":
            result=export_snapshot(args.shared_root,args.output)
        elif args.command=="verify":
            result=verify_snapshot(args.snapshot)
        else:
            result=import_snapshot(args.snapshot,args.target_root,uid=args.uid,gid=args.gid)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":type(exc).__name__,"detail":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
