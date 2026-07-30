from __future__ import annotations

import json
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from .files import sha256_file, write_json
from .models import RepositoryConfig
from .package import artifact_name
from .process import capture


def _expected_artifacts(config: RepositoryConfig) -> dict[str, set[str]]:
    expected = {artifact_name(config, target): {target.name} for target in config.targets.values()}
    expected[f"libmpv-runtime_v{config.lock.runtime_version}_android-universal.aar"] = {
        target.name for target in config.targets.values() if target.platform == "android"
    }
    return expected


def _archive_manifests(artifact: Path) -> list[tuple[str, dict[str, Any]]]:
    raw: list[tuple[str, bytes]]
    if artifact.name.endswith(".tar.gz"):
        with tarfile.open(artifact, mode="r:gz") as archive:
            raw = []
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith("/build-manifest.json"):
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError(f"cannot read release manifest: {artifact.name}:{member.name}")
                raw.append((member.name, extracted.read()))
    else:
        with zipfile.ZipFile(artifact) as archive:
            raw = [
                (name, archive.read(name))
                for name in archive.namelist()
                if name.endswith("/build-manifest.json")
            ]
    manifests: list[tuple[str, dict[str, Any]]] = []
    for name, content in raw:
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError(f"release manifest is not an object: {artifact.name}:{name}")
        manifests.append((name, value))
    if not manifests:
        raise ValueError(f"release artifact has no build manifest: {artifact.name}")
    return manifests


def _validate_manifests(
    artifact: Path,
    *,
    version: str,
    expected_commit: str,
    expected_targets: set[str],
) -> dict[str, dict[str, Any]]:
    manifests = _archive_manifests(artifact)
    observed_targets: set[str] = set()
    evidence_by_target: dict[str, dict[str, Any]] = {}
    for name, manifest in manifests:
        source = manifest.get("source")
        target = manifest.get("target")
        if manifest.get("runtimeVersion") != version:
            raise ValueError(f"runtime version mismatch: {artifact.name}:{name}")
        if not isinstance(source, dict) or source.get("commit") != expected_commit:
            raise ValueError(f"source commit mismatch: {artifact.name}:{name}")
        if source.get("dirty") is not False:
            raise ValueError(f"dirty build is not releasable: {artifact.name}:{name}")
        if not isinstance(target, dict) or not isinstance(target.get("name"), str):
            raise ValueError(f"target is missing from manifest: {artifact.name}:{name}")
        target_name = target["name"]
        observed_targets.add(target_name)
        capabilities = manifest.get("capabilities")
        evidence = capabilities.get("evidence") if isinstance(capabilities, dict) else None
        if not isinstance(evidence, dict) or evidence.get("target") != target_name:
            raise ValueError(f"target evidence is missing from manifest: {artifact.name}:{name}")
        evidence_by_target[target_name] = evidence
    if observed_targets != expected_targets or len(manifests) != len(expected_targets):
        raise ValueError(
            f"artifact target manifests mismatch for {artifact.name}: "
            f"expected {sorted(expected_targets)}, got {sorted(observed_targets)}"
        )
    return evidence_by_target


def _validate_behavior_references(evidence_by_target: dict[str, dict[str, Any]]) -> None:
    for target, evidence in evidence_by_target.items():
        details = evidence.get("details")
        behavior = details.get("behavior") if isinstance(details, dict) else None
        if not isinstance(behavior, dict):
            raise ValueError(f"behavior provenance is missing for release target {target}")
        mode = behavior.get("mode")
        reference = behavior.get("referenceTarget")
        if mode == "native":
            if reference is not None:
                raise ValueError(f"native release target {target} has a behavior reference")
            continue
        if mode != "source-equivalent" or not isinstance(reference, str):
            raise ValueError(f"invalid behavior provenance for release target {target}")
        referenced_evidence = evidence_by_target.get(reference)
        if referenced_evidence is None:
            raise ValueError(
                f"release target {target} references missing behavior target {reference}"
            )
        referenced_details = referenced_evidence.get("details")
        referenced_behavior = (
            referenced_details.get("behavior") if isinstance(referenced_details, dict) else None
        )
        if not isinstance(referenced_behavior, dict) or referenced_behavior.get("mode") != "native":
            raise ValueError(
                f"release target {target} behavior reference {reference} is not native"
            )


def create_release_index(artifacts: list[Path], output: Path, config: RepositoryConfig) -> Path:
    expected_commit = os.environ.get("GITHUB_SHA") or capture(
        ["git", "rev-parse", "HEAD"], cwd=config.root
    )
    if len(expected_commit) != 40:
        raise ValueError("cannot determine the expected release commit")
    expected = _expected_artifacts(config)
    entries: list[dict[str, Any]] = []
    observed: set[str] = set()
    evidence_by_target: dict[str, dict[str, Any]] = {}
    for artifact in sorted(artifacts, key=lambda value: value.name):
        if not artifact.is_file() or artifact.name.endswith(".sha256"):
            continue
        if artifact.name in observed:
            raise ValueError(f"duplicate release artifact: {artifact.name}")
        observed.add(artifact.name)
        if artifact.name not in expected:
            continue
        artifact_evidence = _validate_manifests(
            artifact,
            version=config.lock.runtime_version,
            expected_commit=expected_commit,
            expected_targets=expected[artifact.name],
        )
        for target, evidence in artifact_evidence.items():
            previous = evidence_by_target.get(target)
            if previous is not None and previous != evidence:
                raise ValueError(f"inconsistent release evidence for target {target}")
            evidence_by_target[target] = evidence
        entries.append(
            {
                "name": artifact.name,
                "sha256": sha256_file(artifact),
                "size": artifact.stat().st_size,
            }
        )
    if not entries:
        raise ValueError("release index requires at least one artifact")
    expected_names = set(expected)
    if observed != expected_names:
        missing = ", ".join(sorted(expected_names - observed)) or "none"
        unexpected = ", ".join(sorted(observed - expected_names)) or "none"
        raise ValueError(f"incomplete release set; missing: {missing}; unexpected: {unexpected}")
    _validate_behavior_references(evidence_by_target)
    write_json(
        output,
        {
            "schemaVersion": 1,
            "runtimeVersion": config.lock.runtime_version,
            "source": {
                "repository": "https://github.com/SunnyLimc/libmpv-runtime",
                "commit": expected_commit,
            },
            "artifacts": entries,
        },
    )
    sums = output.with_name("SHA256SUMS")
    sums.write_text(
        "".join(f"{entry['sha256']}  {entry['name']}\n" for entry in entries),
        encoding="ascii",
        newline="\n",
    )
    return output
