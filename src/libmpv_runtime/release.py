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
) -> None:
    manifests = _archive_manifests(artifact)
    observed_targets: set[str] = set()
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
        observed_targets.add(target["name"])
    if observed_targets != expected_targets or len(manifests) != len(expected_targets):
        raise ValueError(
            f"artifact target manifests mismatch for {artifact.name}: "
            f"expected {sorted(expected_targets)}, got {sorted(observed_targets)}"
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
    for artifact in sorted(artifacts, key=lambda value: value.name):
        if not artifact.is_file() or artifact.name.endswith(".sha256"):
            continue
        if artifact.name in observed:
            raise ValueError(f"duplicate release artifact: {artifact.name}")
        observed.add(artifact.name)
        if artifact.name not in expected:
            continue
        _validate_manifests(
            artifact,
            version=config.lock.runtime_version,
            expected_commit=expected_commit,
            expected_targets=expected[artifact.name],
        )
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
    write_json(
        output,
        {
            "schemaVersion": 1,
            "runtimeVersion": config.lock.runtime_version,
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
