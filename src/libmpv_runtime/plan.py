from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_repository
from .discover import discover_many
from .errors import IntegrityError
from .files import read_json, sha256_file, write_json
from .models import (
    Candidate,
    ConsumerProfile,
    RepositoryConfig,
    ToolchainContract,
    ValidationPlan,
)
from .process import capture
from .schema import validate_document

_REVISION = re.compile(r"^[0-9a-f]{40}$")


def repository_revision(root: Path) -> str:
    value = os.environ.get("GITHUB_SHA") or capture(["git", "rev-parse", "HEAD"], cwd=root)
    value = value.strip().lower()
    if not _REVISION.fullmatch(value):
        raise IntegrityError(f"repository revision is not a full commit SHA: {value}")
    return value


def create_plan(config: RepositoryConfig, revision: str, output: Path) -> Path:
    if output.exists():
        raise IntegrityError(f"validation plan already exists: {output}")
    revision = revision.lower()
    if not _REVISION.fullmatch(revision):
        raise IntegrityError("validation plan revision must be a full commit SHA")
    candidates = discover_many(tuple(config.sources[name] for name in sorted(config.sources)))
    plan = ValidationPlan(
        repository_revision=revision,
        created_at=datetime.now(UTC).isoformat(),
        contract_sha256=sha256_file(config.root / "contracts" / "runtime.toml"),
        sources_sha256=sha256_file(config.root / "sources" / "upstreams.toml"),
        candidates=candidates,
        artifacts={name: artifact.sources for name, artifact in config.contract.artifacts.items()},
        toolchain=config.contract.toolchain,
        consumers=config.contract.consumers,
    )
    write_json(output, plan.to_dict())
    verify_plan(config, load_plan(output), revision=revision)
    return output


def _text(value: Any, owner: str) -> str:
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"validation plan {owner} is invalid")
    return value


def load_plan(path: Path) -> ValidationPlan:
    value = read_json(path)
    validate_document(path.parent, "validation-plan", value)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise IntegrityError(f"invalid validation plan schema: {path}")
    raw_candidates = value.get("candidates")
    raw_artifacts = value.get("artifacts")
    raw_toolchain = value.get("toolchain")
    raw_consumers = value.get("consumers")
    if not isinstance(raw_candidates, dict) or not isinstance(raw_artifacts, dict):
        raise IntegrityError(f"validation plan candidates or artifacts are missing: {path}")
    if not isinstance(raw_toolchain, dict) or not isinstance(raw_consumers, dict):
        raise IntegrityError(f"validation plan toolchain or consumers are missing: {path}")
    artifacts: dict[str, tuple[str, ...]] = {}
    for name, sources in raw_artifacts.items():
        if (
            not isinstance(name, str)
            or not isinstance(sources, list)
            or not all(isinstance(source, str) and source for source in sources)
        ):
            raise IntegrityError(f"validation plan artifact is invalid: {name}")
        artifacts[name] = tuple(sources)
    consumers: dict[str, ConsumerProfile] = {}
    for name, raw_profile in raw_consumers.items():
        if not isinstance(name, str) or not isinstance(raw_profile, dict):
            raise IntegrityError("validation plan consumer profile is invalid")
        consumers[name] = ConsumerProfile(
            name=name,
            media_kit=_text(raw_profile.get("mediaKit"), f"consumers.{name}.mediaKit"),
            media_kit_video=_text(
                raw_profile.get("mediaKitVideo"), f"consumers.{name}.mediaKitVideo"
            ),
        )
    return ValidationPlan(
        repository_revision=_text(value.get("repositoryRevision"), "repositoryRevision"),
        created_at=_text(value.get("createdAt"), "createdAt"),
        contract_sha256=_text(value.get("contractSha256"), "contractSha256"),
        sources_sha256=_text(value.get("sourcesSha256"), "sourcesSha256"),
        candidates={name: Candidate.from_dict(item) for name, item in raw_candidates.items()},
        artifacts=artifacts,
        toolchain=ToolchainContract(
            python=_text(raw_toolchain.get("python"), "toolchain.python"),
            flutter=_text(raw_toolchain.get("flutter"), "toolchain.flutter"),
            dart_sdk=_text(raw_toolchain.get("dartSdk"), "toolchain.dartSdk"),
            android_gradle_plugin=_text(
                raw_toolchain.get("androidGradlePlugin"), "toolchain.androidGradlePlugin"
            ),
            android_compile_sdk=_integer(
                raw_toolchain.get("androidCompileSdk"), "toolchain.androidCompileSdk"
            ),
            android_min_sdk=_integer(raw_toolchain.get("androidMinSdk"), "toolchain.androidMinSdk"),
            android_emulator_api=_integer(
                raw_toolchain.get("androidEmulatorApi"),
                "toolchain.androidEmulatorApi",
            ),
            cmake_minimum=_text(raw_toolchain.get("cmakeMinimum"), "toolchain.cmakeMinimum"),
            swift_tools=_text(raw_toolchain.get("swiftTools"), "toolchain.swiftTools"),
            ios_deployment_target=_text(
                raw_toolchain.get("iosDeploymentTarget"),
                "toolchain.iosDeploymentTarget",
            ),
            macos_deployment_target=_text(
                raw_toolchain.get("macosDeploymentTarget"),
                "toolchain.macosDeploymentTarget",
            ),
        ),
        consumers=consumers,
    )


def _integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise IntegrityError(f"validation plan {owner} is invalid")
    return value


def _release_identity(candidate: Candidate) -> tuple[str, int, str]:
    return candidate.repository, candidate.release_id, candidate.commit_sha


def verify_plan(
    config: RepositoryConfig, plan: ValidationPlan, *, revision: str | None = None
) -> None:
    expected_revision = (revision or repository_revision(config.root)).lower()
    if plan.repository_revision != expected_revision:
        raise IntegrityError(
            f"validation plan revision mismatch: {plan.repository_revision} != {expected_revision}"
        )
    if plan.contract_sha256 != sha256_file(config.root / "contracts" / "runtime.toml"):
        raise IntegrityError("validation plan runtime contract digest does not match checkout")
    if plan.sources_sha256 != sha256_file(config.root / "sources" / "upstreams.toml"):
        raise IntegrityError("validation plan source rules digest does not match checkout")
    if plan.toolchain != config.contract.toolchain or plan.consumers != config.contract.consumers:
        raise IntegrityError("validation plan toolchain does not match runtime contract")
    expected_artifacts = {
        name: artifact.sources for name, artifact in config.contract.artifacts.items()
    }
    if plan.artifacts != expected_artifacts:
        raise IntegrityError("validation plan artifacts do not match runtime contract")
    if set(plan.candidates) != set(config.sources):
        raise IntegrityError("validation plan source set does not match source rules")
    for name, candidate in plan.candidates.items():
        rule = config.source(name)
        if candidate.source != name or candidate.repository != rule.repository:
            raise IntegrityError(f"validation plan source identity mismatch: {name}")
        if any(asset.sha256 is None for asset in candidate.assets):
            raise IntegrityError(f"validation plan source has an unhashed asset: {name}")

    for artifact in config.contract.artifacts.values():
        reference_name = artifact.behavior_reference
        if reference_name is None:
            continue
        reference = config.artifact(reference_name)
        target_identities = {_release_identity(plan.candidates[name]) for name in artifact.sources}
        reference_identities = {
            _release_identity(plan.candidates[name]) for name in reference.sources
        }
        if not target_identities & reference_identities:
            raise IntegrityError(
                f"{artifact.name} behavior reference {reference.name} is not release-equivalent"
            )


def candidate_from_plan(
    config: RepositoryConfig, plan_path: Path, source: str, *, revision: str | None = None
) -> Candidate:
    plan = load_plan(plan_path)
    verify_plan(config, plan, revision=revision)
    try:
        return plan.candidates[source]
    except KeyError as error:
        raise IntegrityError(f"validation plan has no source: {source}") from error


def verify_plan_file(path: Path, revision: str | None = None) -> ValidationPlan:
    config = load_repository(path.parent)
    plan = load_plan(path)
    verify_plan(config, plan, revision=revision)
    return plan
