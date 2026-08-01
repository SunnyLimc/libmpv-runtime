from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from libmpv_runtime.config import load_repository
from libmpv_runtime.files import sha256_file, write_json
from libmpv_runtime.models import (
    Candidate,
    CandidateAsset,
    RepositoryConfig,
    ValidationPlan,
)
from libmpv_runtime.plan import repository_revision


@pytest.fixture
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def config(repository_root: Path) -> RepositoryConfig:
    return load_repository(repository_root)


def candidate_for(config: RepositoryConfig, source: str) -> Candidate:
    rule = config.source(source)
    darwin = source.startswith("darwin_")
    identity = 900 if darwin else 100 + sorted(config.sources).index(source)
    commit = "d" * 40 if darwin else f"{identity:040x}"
    return Candidate(
        source=source,
        repository=rule.repository,
        release_tag="v1.2.3",
        release_id=identity,
        release_url=f"https://github.com/{rule.repository}/releases/tag/v1.2.3",
        target_commitish="main",
        commit_sha=commit,
        published_at="2026-08-01T00:00:00+00:00",
        discovered_at=datetime.now(UTC).isoformat(),
        assets=(
            CandidateAsset(
                name=f"{source}.bin",
                url=f"https://github.com/{rule.repository}/releases/download/v1.2.3/{source}.bin",
                sha256=f"{identity:064x}",
                size=128,
            ),
        ),
    )


@pytest.fixture
def validation_plan(config: RepositoryConfig, tmp_path: Path) -> Path:
    plan = ValidationPlan(
        repository_revision=repository_revision(config.root),
        created_at=datetime.now(UTC).isoformat(),
        contract_sha256=sha256_file(config.root / "contracts" / "runtime.toml"),
        sources_sha256=sha256_file(config.root / "sources" / "upstreams.toml"),
        candidates={name: candidate_for(config, name) for name in config.sources},
        artifacts={name: artifact.sources for name, artifact in config.contract.artifacts.items()},
        toolchain=config.contract.toolchain,
        consumers=config.contract.consumers,
    )
    path = tmp_path / "validation-plan.json"
    write_json(path, plan.to_dict())
    return path
