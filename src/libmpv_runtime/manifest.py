from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

from .files import sha256_file
from .models import RepositoryConfig, SourceLock, Target
from .process import capture


def _source_entry(source: SourceLock) -> dict[str, str]:
    return {
        "name": source.name,
        "version": source.version,
        "url": source.url,
        "revision": source.revision,
        "sha256": source.sha256,
        "license": source.license,
    }


def source_lock_document(config: RepositoryConfig, target: Target) -> dict[str, Any]:
    builder = config.lock.builders[target.builder]
    builders = [builder]
    if target.platform == "android":
        builders.append(config.lock.builders["android_helper"])
    return {
        "schemaVersion": 1,
        "runtimeVersion": config.lock.runtime_version,
        "flavor": config.lock.flavor,
        "aggregateLicense": config.lock.aggregate_license,
        "toolchains": config.lock.toolchains,
        "sources": [
            _source_entry(config.lock.sources[name]) for name in sorted(config.lock.sources)
        ],
        "builders": [
            {
                "key": item.key,
                "name": item.name,
                "url": item.url,
                "revision": item.revision,
                "sha256": item.sha256,
            }
            for item in builders
        ],
    }


def _files(stage: Path, excluded: set[Path]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted(stage.rglob("*")):
        relative = path.relative_to(stage)
        if relative in excluded or not path.is_file() or path.is_symlink():
            continue
        result.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return result


def build_manifest(
    config: RepositoryConfig,
    target: Target,
    stage: Path,
    evidence: dict[str, Any],
    *,
    excluded: set[Path] | None = None,
) -> dict[str, Any]:
    commit = capture(["git", "rev-parse", "HEAD"], cwd=config.root)
    dirty = bool(capture(["git", "status", "--porcelain"], cwd=config.root))
    github_sha = os.environ.get("GITHUB_SHA", "")
    if github_sha and commit and github_sha != commit:
        commit = github_sha
    return {
        "schemaVersion": 1,
        "runtimeVersion": config.lock.runtime_version,
        "flavor": config.lock.flavor,
        "aggregateLicense": config.lock.aggregate_license,
        "target": {
            "name": target.name,
            "platform": target.platform,
            "architecture": target.architecture,
            "loadName": target.load_name,
            "package": target.package,
        },
        "source": {
            "repository": "https://github.com/SunnyLimc/libmpv-runtime",
            "commit": commit,
            "dirty": dirty,
        },
        "build": {
            "sourceDateEpoch": config.lock.source_date_epoch,
            "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "runner": os.environ.get("RUNNER_NAME", platform.node()),
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": sys.version.split()[0],
            },
        },
        "capabilities": {
            "audioFilters": list(config.lock.required_audio_filters),
            "evidence": evidence,
        },
        "inputs": source_lock_document(config, target),
        "files": _files(stage, excluded or set()),
    }
