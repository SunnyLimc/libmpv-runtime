from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import IntegrityError, VerificationError
from .files import read_json, sha256_file, sha256_json, write_json
from .models import Intake, RepositoryConfig
from .plan import load_plan, verify_plan
from .process import capture, find_json_object, tool_command
from .schema import validate_document

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _report(path: Path, kind: str) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or value.get("kind") != kind:
        raise VerificationError(f"invalid {kind} report: {path}")
    return value


def _release_identity(candidate: dict[str, Any]) -> tuple[object, object, object]:
    return candidate.get("repository"), candidate.get("releaseId"), candidate.get("commitSha")


def derive_behavior_report(
    config: RepositoryConfig,
    plan_path: Path,
    target: str,
    reference_report_path: Path,
    output: Path,
) -> Path:
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    artifact = config.artifact(target)
    reference_target = artifact.behavior_reference
    if artifact.behavior_mode != "source-equivalent" or reference_target is None:
        raise VerificationError(f"{target} does not use source-equivalent behavior")
    reference = _report(reference_report_path, "behavior")
    if reference.get("target") != reference_target or reference.get("mode") not in {
        "native",
        "native-subset",
    }:
        raise VerificationError(f"behavior reference is not native: {reference_target}")
    if reference.get("planSha256") != sha256_file(plan_path):
        raise VerificationError("behavior reference belongs to a different validation plan")
    write_json(
        output,
        {
            **reference,
            "target": target,
            "mode": "source-equivalent",
            "referenceTarget": reference_target,
            "architectures": [],
            "stageProvenanceSha256": None,
        },
    )
    return output


def _package_versions(app: Path) -> dict[str, str]:
    value = find_json_object(
        capture(tool_command("dart", "pub", "deps", "--json"), cwd=app),
        required_key="packages",
    )
    if value is None:
        raise VerificationError("dart pub deps returned no machine-readable dependency graph")
    packages = value.get("packages")
    if not isinstance(packages, list):
        raise VerificationError("dart pub deps did not return packages")
    result: dict[str, str] = {}
    for package in packages:
        if not isinstance(package, dict):
            continue
        name = package.get("name")
        version = package.get("version")
        if isinstance(name, str) and isinstance(version, str):
            result[name] = version
    return result


def _flutter_version() -> str:
    value = find_json_object(
        capture(tool_command("flutter", "--version", "--machine"), cwd=Path.cwd()),
        required_key="frameworkVersion",
    )
    if value is None:
        raise VerificationError("flutter --version returned no machine-readable version")
    version = value.get("frameworkVersion")
    if not isinstance(version, str) or not version:
        raise VerificationError("Flutter framework version is missing")
    return version


def create_consumer_report(
    config: RepositoryConfig,
    plan_path: Path,
    target: str,
    profile_name: str,
    app: Path,
    artifact_paths: list[Path],
    details: dict[str, str],
    output: Path,
) -> Path:
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    try:
        profile = plan.consumers[profile_name]
    except KeyError as error:
        raise VerificationError(
            f"validation plan has no consumer profile: {profile_name}"
        ) from error
    versions = _package_versions(app)
    observed_flutter = _flutter_version()
    if observed_flutter != plan.toolchain.flutter:
        raise VerificationError(
            f"Flutter version mismatch: expected {plan.toolchain.flutter}, got {observed_flutter}"
        )
    expected = {
        "media_kit": profile.media_kit,
        "media_kit_video": profile.media_kit_video,
    }
    observed = {name: versions.get(name) for name in expected}
    if observed != expected:
        raise VerificationError(
            f"MediaKit dependency mismatch: expected {expected}, got {observed}"
        )
    if not artifact_paths or any(not path.is_file() for path in artifact_paths):
        raise VerificationError(f"{target} consumer artifacts are missing")
    artifact_records = [
        {
            "name": path.name,
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
        for path in sorted(artifact_paths, key=lambda item: item.name)
    ]
    write_json(
        output,
        {
            "schemaVersion": 1,
            "kind": "consumer",
            "target": target,
            "planSha256": sha256_file(plan_path),
            "profile": profile_name,
            "flutter": observed_flutter,
            "packages": expected,
            "artifacts": artifact_records,
            "details": details,
        },
    )
    return output


def _validate_provenance(
    config: RepositoryConfig, target: str, provenance: Any, plan_path: Path
) -> None:
    plan = load_plan(plan_path)
    if not isinstance(provenance, dict) or provenance.get("schemaVersion") != 2:
        raise VerificationError(f"{target} stage provenance is invalid")
    if provenance.get("artifact") != target:
        raise VerificationError(f"{target} stage provenance identifies another artifact")
    raw_intakes = provenance.get("intakes")
    if not isinstance(raw_intakes, list):
        raise VerificationError(f"{target} stage provenance has no intakes")
    intakes = [Intake.from_dict(value) for value in raw_intakes]
    expected_sources = set(config.artifact(target).sources)
    if {intake.candidate.source for intake in intakes} != expected_sources:
        raise VerificationError(f"{target} stage provenance source set is invalid")
    for intake in intakes:
        if intake.candidate != plan.candidates[intake.candidate.source]:
            raise VerificationError(f"{target} stage was not built from the sealed validation plan")


def _validate_behavior(
    config: RepositoryConfig,
    target: str,
    value: dict[str, Any],
    plan_path: Path,
    provenance: Any,
) -> None:
    artifact = config.artifact(target)
    if value.get("target") != target or value.get("mode") != artifact.behavior_mode:
        raise VerificationError(f"{target} behavior mode or identity is invalid")
    if value.get("planSha256") != sha256_file(plan_path):
        raise VerificationError(f"{target} behavior belongs to another validation plan")
    if value.get("referenceTarget") != artifact.behavior_reference:
        raise VerificationError(f"{target} behavior reference is invalid")
    if value.get("architectures") != list(artifact.behavior_architectures):
        raise VerificationError(f"{target} behavior architecture coverage is invalid")
    expected_provenance = (
        None if artifact.behavior_mode == "source-equivalent" else sha256_json(provenance)
    )
    if value.get("stageProvenanceSha256") != expected_provenance:
        raise VerificationError(f"{target} behavior stage provenance is invalid")
    raw_filters = value.get("filters")
    if not isinstance(raw_filters, list):
        raise VerificationError(f"{target} behavior has no filter reports")
    observed: dict[str, str] = {}
    for item in raw_filters:
        if not isinstance(item, dict):
            raise VerificationError(f"{target} behavior filter report is invalid")
        name = item.get("name")
        expression = item.get("expression")
        digest = item.get("sha256")
        size = item.get("size")
        if (
            not isinstance(name, str)
            or not isinstance(expression, str)
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
            or not isinstance(size, int)
            or size <= 44
        ):
            raise VerificationError(f"{target} behavior filter report is incomplete")
        observed[name] = expression
    expected_filters = {item.name: item.expression for item in config.contract.probe.filters}
    if observed != expected_filters:
        raise VerificationError(f"{target} behavior did not run the contract probe plan")
    measured = value.get("measuredGainDb")
    expected_gain = config.contract.probe.expected_gain_db
    tolerance = config.contract.probe.gain_tolerance_db
    if (
        not isinstance(measured, (int, float))
        or abs(float(measured) - expected_gain) > tolerance
        or value.get("expectedGainDb") != expected_gain
        or value.get("gainToleranceDb") != tolerance
        or value.get("httpRange") is not True
        or value.get("filterAfterLoad") is not True
    ):
        raise VerificationError(f"{target} decoded PCM behavior is invalid")


def _required_consumer_details(target: str) -> dict[str, str]:
    if target == "android":
        return {
            "platform": "android",
            "onlinePlayback": "passed",
            "filterAfterLoad": "passed",
            "jniHelper": "passed",
        }
    if target in {"windows-x86_64", "macos"}:
        return {
            "platform": "windows" if target == "windows-x86_64" else "macos",
            "onlinePlayback": "passed",
            "filterAfterLoad": "passed",
        }
    if target == "ios":
        return {
            "platform": "ios-simulator",
            "compileLink": "passed",
            "pluginRegistration": "passed",
        }
    raise VerificationError(f"unsupported consumer evidence target: {target}")


def _validate_consumer(
    config: RepositoryConfig, target: str, value: dict[str, Any], plan_path: Path
) -> None:
    plan = load_plan(plan_path)
    if value.get("target") != target or value.get("planSha256") != sha256_file(plan_path):
        raise VerificationError(f"{target} consumer belongs to another target or plan")
    profile_name = value.get("profile")
    if not isinstance(profile_name, str) or profile_name not in plan.consumers:
        raise VerificationError(f"{target} consumer profile is invalid")
    profile = plan.consumers[profile_name]
    if value.get("flutter") != plan.toolchain.flutter or value.get("packages") != {
        "media_kit": profile.media_kit,
        "media_kit_video": profile.media_kit_video,
    }:
        raise VerificationError(f"{target} consumer toolchain is invalid")
    details = value.get("details")
    required = _required_consumer_details(target)
    if not isinstance(details, dict) or any(
        details.get(key) != expected for key, expected in required.items()
    ):
        raise VerificationError(f"{target} consumer details are incomplete")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise VerificationError(f"{target} consumer artifacts are missing")
    for artifact in artifacts:
        if (
            not isinstance(artifact, dict)
            or not isinstance(artifact.get("name"), str)
            or Path(str(artifact.get("name"))).name != artifact.get("name")
            or not isinstance(artifact.get("sha256"), str)
            or not _SHA256.fullmatch(str(artifact.get("sha256")))
            or not isinstance(artifact.get("size"), int)
            or int(artifact.get("size", 0)) <= 0
        ):
            raise VerificationError(f"{target} consumer artifact record is invalid")


def seal_evidence(
    config: RepositoryConfig,
    plan_path: Path,
    target: str,
    structure_path: Path,
    behavior_path: Path,
    consumer_paths: dict[str, Path],
    output: Path,
) -> Path:
    if output.exists():
        raise IntegrityError(f"sealed evidence already exists: {output}")
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    structure = _report(structure_path, "structure")
    behavior = _report(behavior_path, "behavior")
    expected_profiles = set(plan.consumers)
    if set(consumer_paths) != expected_profiles:
        raise VerificationError(
            f"{target} consumer profile set mismatch: expected {sorted(expected_profiles)}, "
            f"got {sorted(consumer_paths)}"
        )
    consumers: dict[str, dict[str, Any]] = {}
    for profile, path in sorted(consumer_paths.items()):
        consumer = _report(path, "consumer")
        if consumer.get("profile") != profile:
            raise VerificationError(f"{target} consumer report profile mismatch: {profile}")
        _validate_consumer(config, target, consumer, plan_path)
        consumers[profile] = consumer
    artifact_sets = {
        json.dumps(value.get("artifacts"), sort_keys=True) for value in consumers.values()
    }
    if len(artifact_sets) != 1:
        raise VerificationError(f"{target} consumer profiles tested different artifacts")
    if structure.get("target") != target:
        raise VerificationError(f"structure report target mismatch: {target}")
    if structure.get("requiredFilters") != list(config.contract.required_audio_filters):
        raise VerificationError(f"structure report contract mismatch: {target}")
    _validate_provenance(config, target, structure.get("provenance"), plan_path)
    _validate_behavior(config, target, behavior, plan_path, structure.get("provenance"))
    write_json(
        output,
        {
            "schemaVersion": 4,
            "sealed": True,
            "target": target,
            "planSha256": sha256_file(plan_path),
            "repositoryRevision": plan.repository_revision,
            "contractSha256": plan.contract_sha256,
            "checks": {"structure": True, "behavior": True, "consumers": True},
            "structure": structure,
            "behavior": behavior,
            "consumers": consumers,
            "provenance": structure["provenance"],
        },
    )
    return output


def load_releasable_evidence(path: Path, target: str) -> dict[str, Any]:
    value = read_json(path)
    validate_document(path.parent, "evidence", value)
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 4
        or value.get("sealed") is not True
        or value.get("target") != target
        or value.get("checks") != {"structure": True, "behavior": True, "consumers": True}
    ):
        raise VerificationError(f"evidence is not sealed and releasable: {path}")
    return value


def seal_linux_evidence(
    config: RepositoryConfig,
    plan_path: Path,
    profile: str,
    structure_path: Path,
    behavior_path: Path,
    output: Path,
) -> Path:
    if output.exists():
        raise IntegrityError(f"sealed Linux evidence already exists: {output}")
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    if profile not in config.contract.linux.profiles:
        raise VerificationError(f"unsupported Linux profile: {profile}")
    structure = _report(structure_path, "linux-structure")
    behavior = _report(behavior_path, "behavior")
    if structure.get("profile") != profile:
        raise VerificationError(f"Linux structure profile mismatch: {profile}")
    if structure.get("planSha256") != sha256_file(plan_path):
        raise VerificationError(f"Linux structure belongs to another plan: {profile}")
    os_release = structure.get("osRelease")
    profile_contract = config.contract.linux.profiles[profile]
    if (
        not isinstance(os_release, dict)
        or os_release.get("id") != profile_contract.os_id
        or not isinstance(os_release.get("versionId"), str)
        or not re.fullmatch(
            profile_contract.version_pattern,
            str(os_release.get("versionId")),
        )
    ):
        raise VerificationError(f"Linux structure OS identity is invalid: {profile}")
    if behavior.get("target") != "linux-system" or behavior.get("mode") != "native":
        raise VerificationError(f"Linux behavior identity is invalid: {profile}")
    if behavior.get("planSha256") != sha256_file(plan_path):
        raise VerificationError(f"Linux behavior belongs to another plan: {profile}")
    if behavior.get("stageProvenanceSha256") is not None:
        raise VerificationError(f"Linux behavior must use the system runtime: {profile}")
    raw_filters = behavior.get("filters")
    expected_filters = {item.name: item.expression for item in config.contract.probe.filters}
    observed_filters = (
        {
            str(item.get("name")): str(item.get("expression"))
            for item in raw_filters
            if isinstance(item, dict)
        }
        if isinstance(raw_filters, list)
        else {}
    )
    measured = behavior.get("measuredGainDb")
    if (
        observed_filters != expected_filters
        or not isinstance(measured, (int, float))
        or abs(float(measured) - config.contract.probe.expected_gain_db)
        > config.contract.probe.gain_tolerance_db
        or behavior.get("httpRange") is not True
        or behavior.get("filterAfterLoad") is not True
    ):
        raise VerificationError(f"Linux DSP behavior is invalid: {profile}")
    write_json(
        output,
        {
            "schemaVersion": 1,
            "kind": "linux-evidence",
            "sealed": True,
            "profile": profile,
            "planSha256": sha256_file(plan_path),
            "repositoryRevision": plan.repository_revision,
            "structure": structure,
            "behavior": behavior,
        },
    )
    return output


def load_linux_evidence(path: Path, profile: str) -> dict[str, Any]:
    value = read_json(path)
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or value.get("kind") != "linux-evidence"
        or value.get("sealed") is not True
        or value.get("profile") != profile
    ):
        raise VerificationError(f"Linux evidence is not sealed: {path}")
    return value
