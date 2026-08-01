from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from libmpv_runtime import acquire as acquire_module
from libmpv_runtime.acquire import acquire, load_candidate, load_intake
from libmpv_runtime.errors import IntegrityError
from libmpv_runtime.files import read_json, write_json
from libmpv_runtime.models import Candidate, CandidateAsset, RepositoryConfig
from libmpv_runtime.plan import load_plan, verify_plan
from libmpv_runtime.workspace import PipelineWorkspace


def test_validation_plan_is_typed_and_bound_to_checkout(
    config: RepositoryConfig, validation_plan: Path
) -> None:
    plan = load_plan(validation_plan)
    verify_plan(config, plan)
    value = read_json(validation_plan)
    value["contractSha256"] = "0" * 64
    write_json(validation_plan, value)
    with pytest.raises(IntegrityError, match="contract digest"):
        verify_plan(config, load_plan(validation_plan))


def test_acquire_downloads_and_revalidates_exact_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"immutable upstream asset"
    digest = hashlib.sha256(payload).hexdigest()
    candidate = Candidate(
        source="fixture",
        repository="example/runtime",
        release_tag="v1",
        release_id=1,
        release_url="https://github.com/example/runtime/releases/tag/v1",
        target_commitish="main",
        commit_sha="a" * 40,
        published_at="2026-08-01T00:00:00Z",
        discovered_at="2026-08-01T00:00:01Z",
        assets=(
            CandidateAsset(
                name="runtime.bin",
                url="https://github.com/example/runtime/releases/download/v1/runtime.bin",
                sha256=digest,
                size=len(payload),
            ),
        ),
    )
    downloads = 0

    def download(_: str, destination: Path) -> None:
        nonlocal downloads
        downloads += 1
        destination.write_bytes(payload)

    monkeypatch.setattr(acquire_module, "_download", download)
    output = tmp_path / "intake"
    candidate_path = tmp_path / "candidate.json"
    write_json(candidate_path, candidate.to_dict())
    assert load_candidate(candidate_path) == candidate
    manifest = acquire(candidate, output)
    assert load_intake(manifest).assets[0].sha256 == digest
    assert downloads == 1
    acquire(candidate, output)
    assert downloads == 1
    (output / "runtime.bin").write_bytes(b"changed")
    acquire(candidate, output)
    assert downloads == 2


def test_pipeline_workspace_only_replaces_owned_paths(
    repository_root: Path,
) -> None:
    path = repository_root / "work" / "pytest-owned-workspace"
    path.mkdir(parents=True, exist_ok=True)
    (path / "user.txt").write_text("preserve", encoding="utf-8")
    try:
        with pytest.raises(IntegrityError, match="unowned"):
            PipelineWorkspace.fresh(repository_root, path)
        (path / ".libmpv-runtime-workspace").write_text("owned\n", encoding="ascii")
        workspace = PipelineWorkspace.fresh(repository_root, path)
        assert not (path / "user.txt").exists()
        assert workspace.directory("output").is_dir()
    finally:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
