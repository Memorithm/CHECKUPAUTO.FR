from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import deployment_activation as activation
import deployment_github_source as github_source
import deployment_release as release
import deployment_transport as transport
import deployment_update as deployment_update
from deployment_center import CapabilityReport, DeploymentTarget, assess


@dataclass(frozen=True)
class DeploymentExecutionResult:
    action: str
    sha: str
    previous_sha: str
    staged: bool
    release_path: str
    archive_sha256: str
    file_count: int
    readiness_state: str
    activation_allowed: bool
    blocker_count: int


def _local_runtime_flags(repo_root: str | Path) -> tuple[bool, bool]:
    root = Path(repo_root).resolve()
    passenger_wsgi_adapter = (
        (root / "passenger_wsgi.py").is_file()
        or (root / "deploy" / "passenger_wsgi.py").is_file()
    )
    shared_host_tick = (root / "scripts" / "checkupauto-shared-tick.py").is_file()
    return passenger_wsgi_adapter, shared_host_tick


def probe_deployment_target(
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    repo_root: str | Path,
    *,
    timeout: int = 30,
) -> CapabilityReport:
    adapter, shared_tick = _local_runtime_flags(repo_root)
    capabilities = transport.probe_target(
        target,
        known_hosts,
        credential,
        passenger_wsgi_adapter=adapter,
        shared_host_tick=shared_tick,
        timeout=timeout,
    )
    readiness = assess(target, capabilities)
    if not readiness["ok"]:
        blockers = ",".join(str(item) for item in readiness["blockers"])
        raise RuntimeError(
            "cible de déploiement non prête"
            + (f": {blockers}" if blockers else "")
        )
    return capabilities


def _assert_action_state(
    action: str,
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    repo_root: str | Path,
    release_sha: str,
    *,
    timeout: int = 30,
) -> None:
    remote = deployment_update.read_remote_state(
        target,
        known_hosts,
        credential,
        timeout=timeout,
    )
    if action == "install":
        if remote.installed:
            raise RuntimeError("cible déjà installée; utiliser update")
        return

    state = deployment_update.classify_update(
        remote,
        release_sha,
        repo_root,
    )
    if state.get("state") != "update_available":
        reason = str(state.get("state") or "unknown")
        raise RuntimeError(
            "mise à jour distante non autorisée: " + reason
        )


def execute_deployment(
    action: str,
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    repo_root: str | Path,
    release_sha: str,
    *,
    admin_password: str = "",
    probe_timeout: int = 30,
    stage_timeout: int = 900,
    activation_timeout: int = 180,
) -> DeploymentExecutionResult:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"install", "update"}:
        raise ValueError("action de déploiement invalide")

    capabilities = probe_deployment_target(
        target,
        known_hosts,
        credential,
        repo_root,
        timeout=probe_timeout,
    )
    _assert_action_state(
        normalized_action,
        target,
        known_hosts,
        credential,
        repo_root,
        release_sha,
        timeout=probe_timeout,
    )
    staged = release.stage_release(
        target,
        capabilities,
        known_hosts,
        credential,
        repo_root,
        release_sha,
        timeout=stage_timeout,
    )
    activated = activation.activate_release(
        target,
        capabilities,
        known_hosts,
        credential,
        staged.sha,
        admin_password=admin_password,
        update_source=github_source.bootstrap_material(),
        timeout=activation_timeout,
    )
    if activated.sha != staged.sha:
        raise RuntimeError("activation distante incohérente")

    return DeploymentExecutionResult(
        action=normalized_action,
        sha=activated.sha,
        previous_sha=activated.previous_sha,
        staged=True,
        release_path=staged.release_path,
        archive_sha256=staged.archive_sha256,
        file_count=staged.file_count,
        readiness_state=activated.readiness_state,
        activation_allowed=activated.activation_allowed,
        blocker_count=activated.blocker_count,
    )


def execute_rollback(
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    repo_root: str | Path,
    release_sha: str,
    *,
    admin_password: str = "",
    probe_timeout: int = 30,
    activation_timeout: int = 180,
) -> DeploymentExecutionResult:
    capabilities = probe_deployment_target(
        target,
        known_hosts,
        credential,
        repo_root,
        timeout=probe_timeout,
    )
    activated = activation.rollback_release(
        target,
        capabilities,
        known_hosts,
        credential,
        release_sha,
        admin_password=admin_password,
        timeout=activation_timeout,
    )
    return DeploymentExecutionResult(
        action="rollback",
        sha=activated.sha,
        previous_sha=activated.previous_sha,
        staged=False,
        release_path="",
        archive_sha256="",
        file_count=0,
        readiness_state=activated.readiness_state,
        activation_allowed=activated.activation_allowed,
        blocker_count=activated.blocker_count,
    )
