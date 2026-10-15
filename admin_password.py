"""Private admin HTTP Basic credential rotation; no secrets in Git or logs.

Multi-worker authentication reads the *current* private file on each request.
Rotations are serialized across processes, written with mode 0600, fsynced,
and atomically replaced. No browser or caller may choose a filesystem path.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time

MIN_LENGTH = 8
MAX_LENGTH = 128
CSRF_TTL_HOURS = 1


class AdminPasswordError(ValueError):
    """Only stable failure codes; never include submitted credentials."""


def _path() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / "admin-password"


def _read_private(path: Path) -> str:
    """Reject symlinks, public files and replaced file descriptors."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise AdminPasswordError("admin_password_file_invalid")
        with os.fdopen(os.dup(fd), "rb") as handle:
            raw = handle.read(4097)
        if not raw or len(raw) > 4096:
            raise AdminPasswordError("admin_password_file_invalid")
        # Compatible with the original admin_server startup .read_text().strip().
        value = raw.decode("utf-8").strip()
        if not value:
            raise AdminPasswordError("admin_password_file_invalid")
        return value
    except UnicodeDecodeError:
        raise AdminPasswordError("admin_password_file_invalid") from None
    finally:
        os.close(fd)


def current(*, path: Path | None = None) -> str:
    return _read_private(_path() if path is None else Path(path))


def verify(candidate: object, *, path: Path | None = None) -> bool:
    if not isinstance(candidate, str) or not 1 <= len(candidate) <= 4096:
        return False
    try:
        return hmac.compare_digest(
            candidate.encode("utf-8"), current(path=path).encode("utf-8")
        )
    except (OSError, ValueError, UnicodeError):
        return False


def csrf_token(headers, *, path: Path | None = None, hour: int | None = None) -> str:
    """Stateless double-auth-bound, time-limited token (not the payments token)."""
    period = int(time.time() // 3600) if hour is None else hour
    binding = hashlib.sha256(
        (headers.get("Authorization", "") + "\x00" + headers.get("Cookie", "")).encode()
    ).hexdigest()
    return hmac.new(
        current(path=path).encode(),
        ("admin-password-change:v1:" + str(period) + ":" + binding).encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_csrf(value: object, headers, *, path: Path | None = None) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        return False
    now = int(time.time() // 3600)
    return any(
        hmac.compare_digest(value, csrf_token(headers, path=path, hour=hour))
        for hour in (now, now - CSRF_TTL_HOURS)
    )


def _validate_new(value: object) -> str:
    if (not isinstance(value, str) or not MIN_LENGTH <= len(value) <= MAX_LENGTH
            or len(value.encode("utf-8")) > 512
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise AdminPasswordError("admin_password_new_invalid")
    return value


@contextmanager
def _rotation_lock(path: Path):
    root = path.parent
    if root.is_symlink() or not root.is_dir():
        raise AdminPasswordError("admin_password_storage_invalid")
    # The directory is a private deployment prerequisite, never created in Web.
    fd = os.open(root / ".admin-password-rotation.lock",
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise AdminPasswordError("admin_password_storage_invalid")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def change(*, old: object, new: object, confirmation: object,
           path: Path | None = None) -> None:
    """Change only after the HTTP layer has authenticated Basic + MFA + CSRF.

    An incorrect old credential or a concurrent rotation never replaces the
    current password. No password or path is included in any returned error.
    """
    target = _path() if path is None else Path(path)
    replacement = _validate_new(new)
    if not isinstance(old, str) or not isinstance(confirmation, str):
        raise AdminPasswordError("admin_password_input_invalid")
    if not hmac.compare_digest(replacement.encode(), confirmation.encode()):
        raise AdminPasswordError("admin_password_confirmation_mismatch")
    with _rotation_lock(target):
        saved = current(path=target)
        if not hmac.compare_digest(old.encode(), saved.encode()):
            raise AdminPasswordError("admin_password_current_invalid")
        if hmac.compare_digest(replacement.encode(), saved.encode()):
            raise AdminPasswordError("admin_password_unchanged")
        fd, temporary = tempfile.mkstemp(prefix=".admin-password-new-", dir=target.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(replacement.encode("utf-8") + b"\n")
                out.flush()
                os.fsync(out.fileno())
            fd = -1
            os.replace(temporary, target)
            dirfd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if fd != -1:
                os.close(fd)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
