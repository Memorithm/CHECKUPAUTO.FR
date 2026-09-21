from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
import ipaddress
import re
from typing import Any

PROFILE_VERSION = 1
_PROVIDER_PROFILES = {
    "planethoster-n0c": {
        "label": "PlanetHoster World / N0C",
        "defaultPort": 5022,
        "runtime": "passenger",
        "defaultRoot": "checkupauto",
        "sharedHosting": True,
        "supportsSystemd": False,
        "supportsCron": True,
    },
    "planethoster-cpanel": {
        "label": "PlanetHoster cPanel (legacy)",
        "defaultPort": 2908,
        "runtime": "passenger",
        "defaultRoot": "public_html",
        "sharedHosting": True,
        "supportsSystemd": False,
        "supportsCron": True,
    },
    "generic-ssh": {
        "label": "Hébergement SSH générique",
        "defaultPort": 22,
        "runtime": "probe",
        "defaultRoot": "public_html",
        "sharedHosting": False,
        "supportsSystemd": False,
        "supportsCron": True,
    },
    "linux-systemd": {
        "label": "Linux dédié / VPS systemd",
        "defaultPort": 22,
        "runtime": "systemd",
        "defaultRoot": "/opt/checkupauto",
        "sharedHosting": False,
        "supportsSystemd": True,
        "supportsCron": True,
    },
}

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
_SAFE_ROOT_RE = re.compile(r"^[A-Za-z0-9._~/-]{1,300}$")


@dataclass(frozen=True)
class DeploymentTarget:
    provider: str
    host: str
    port: int
    username: str
    domain: str
    root_path: str
    auth_mode: str = "key"

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityReport:
    python_version: str = ""
    node_version: str = ""
    passenger: bool = False
    systemd: bool = False
    cron: bool = False
    symlink: bool = False
    writable_root: bool = False
    free_disk_mb: int = 0
    passenger_wsgi_adapter: bool = False
    shared_host_tick: bool = False
    cloudlinux_selector: bool = False
    managed_python_version: str = ""


def provider_profiles() -> dict[str, dict[str, Any]]:
    return {
        key: {"id": key, **value}
        for key, value in _PROVIDER_PROFILES.items()
    }


def _host(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw or any(ch.isspace() for ch in raw):
        raise ValueError("host invalide")
    try:
        ipaddress.ip_address(raw)
        return raw
    except ValueError:
        pass
    if not _HOST_RE.fullmatch(raw):
        raise ValueError("host invalide")
    return raw


def _domain(value: object) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    if not _DOMAIN_RE.fullmatch(raw):
        raise ValueError("domaine invalide")
    return raw


def _root_path(value: object, *, shared: bool) -> str:
    raw = str(value or "").strip()
    if not raw or not _SAFE_ROOT_RE.fullmatch(raw) or "\x00" in raw:
        raise ValueError("répertoire cible invalide")
    path = PurePosixPath(raw)
    if ".." in path.parts:
        raise ValueError("répertoire cible invalide")
    if shared and path.is_absolute():
        raise ValueError("un hébergement mutualisé exige un chemin relatif au HOME")
    return str(path)


def validate_target(payload: dict[str, Any]) -> DeploymentTarget:
    if not isinstance(payload, dict):
        raise ValueError("configuration de déploiement invalide")
    provider = str(payload.get("provider") or "").strip()
    profile = _PROVIDER_PROFILES.get(provider)
    if not profile:
        raise ValueError("profil d hébergement inconnu")

    port_raw = payload.get("port", profile["defaultPort"])
    if isinstance(port_raw, bool):
        raise ValueError("port SSH invalide")
    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("port SSH invalide") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port SSH invalide")

    username = str(payload.get("username") or "").strip()
    if not _USER_RE.fullmatch(username):
        raise ValueError("utilisateur SSH invalide")

    auth_mode = str(payload.get("authMode") or "key").strip().lower()
    if auth_mode not in {"key", "password"}:
        raise ValueError("mode d authentification invalide")

    return DeploymentTarget(
        provider=provider,
        host=_host(payload.get("host")),
        port=port,
        username=username,
        domain=_domain(payload.get("domain")),
        root_path=_root_path(
            payload.get("rootPath", profile["defaultRoot"]),
            shared=bool(profile["sharedHosting"]),
        ),
        auth_mode=auth_mode,
    )


def _python_tuple(version: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", str(version or ""))
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def assess(target: DeploymentTarget, capabilities: CapabilityReport) -> dict[str, Any]:
    profile = _PROVIDER_PROFILES[target.provider]
    checks = []
    blockers = []

    def check(code: str, ok: bool, detail: str, *, blocking: bool = True) -> None:
        checks.append({
            "code": code,
            "ok": bool(ok),
            "detail": detail,
            "blocking": bool(blocking),
        })
        if blocking and not ok:
            blockers.append(code)

    effective_python = (
        capabilities.managed_python_version
        if _PROVIDER_PROFILES[target.provider]["runtime"] == "passenger"
        and capabilities.managed_python_version
        else capabilities.python_version
    )
    check(
        "python",
        _python_tuple(effective_python) >= (3, 11),
        effective_python or "python3 absent",
    )
    check("writable_root", capabilities.writable_root, target.root_path)
    check("free_disk", capabilities.free_disk_mb >= 1024, f"{capabilities.free_disk_mb} MB")
    check("symlink", capabilities.symlink, "symlink support")

    runtime = profile["runtime"]
    if runtime == "passenger":
        check("cloudlinux_selector", capabilities.cloudlinux_selector, "cloudlinux-selector")
        check("passenger", capabilities.passenger, "Passenger Python")
        check(
            "passenger_wsgi_adapter",
            capabilities.passenger_wsgi_adapter,
            "adaptateur WSGI CheckupAuto",
        )
        check("cron", capabilities.cron, "cron")
        check(
            "shared_host_tick",
            capabilities.shared_host_tick,
            "scheduler cron CheckupAuto",
        )
    elif runtime == "systemd":
        check("systemd", capabilities.systemd, "systemd")
    elif runtime == "probe":
        runtime_ok = capabilities.passenger or capabilities.systemd
        check(
            "supported_runtime",
            runtime_ok,
            "Passenger ou systemd requis",
        )

    state = "ready" if not blockers else "blocked"
    return {
        "ok": not blockers,
        "state": state,
        "provider": target.provider,
        "runtime": runtime,
        "checks": checks,
        "blockers": blockers,
    }


def installation_layout(target: DeploymentTarget, release_sha: str) -> dict[str, str]:
    sha = str(release_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("SHA de release invalide")
    root = target.root_path.rstrip("/")
    return {
        "root": root,
        "releases": f"{root}/releases",
        "release": f"{root}/releases/{sha}",
        "current": f"{root}/current",
        "shared": f"{root}/shared",
        "data": f"{root}/shared/data",
        "private": f"{root}/shared/private",
        "security": f"{root}/shared/security",
        "integrity": f"{root}/shared/integrity",
        "logs": f"{root}/shared/logs",
    }


def installation_plan(
    target: DeploymentTarget,
    release_sha: str,
    capabilities: CapabilityReport,
) -> dict[str, Any]:
    assessment = assess(target, capabilities)
    layout = installation_layout(target, release_sha)
    actions = [
        {"id": "connect", "label": "Connexion SSH et validation de l empreinte hôte"},
        {"id": "probe", "label": "Diagnostic runtime non destructif"},
        {"id": "directories", "label": "Création releases/current/shared"},
        {"id": "upload", "label": "Transfert de la release dans un répertoire neuf"},
        {"id": "dependencies", "label": "Installation des dépendances dans la release"},
        {"id": "health", "label": "Validation locale avant activation"},
        {"id": "activate", "label": "Bascule atomique du lien current"},
        {"id": "verify", "label": "Vérification HTTP après activation"},
    ]
    if not assessment["ok"]:
        actions = actions[:2]
    return {
        "schemaVersion": PROFILE_VERSION,
        "target": target.public_dict(),
        "assessment": assessment,
        "layout": layout,
        "actions": actions,
        "rollback": {
            "strategy": "atomic-current-symlink",
            "keepsPreviousRelease": True,
        },
        "secrets": {
            "persistInRepository": False,
            "passwordInPlan": False,
        },
    }
