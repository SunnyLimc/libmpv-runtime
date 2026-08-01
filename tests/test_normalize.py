from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from libmpv_runtime.files import read_json, write_json
from libmpv_runtime.models import (
    Candidate,
    CandidateAsset,
    Intake,
    IntakeAsset,
    RepositoryConfig,
)
from libmpv_runtime.normalize import normalize


def _candidate(source: str, assets: list[tuple[str, bytes]]) -> Candidate:
    return Candidate(
        source=source,
        repository="example/runtime",
        release_tag="v1",
        release_id=1,
        release_url="https://github.com/example/runtime/releases/tag/v1",
        target_commitish="main",
        commit_sha="a" * 40,
        published_at="2026-08-01T00:00:00Z",
        discovered_at="2026-08-01T00:00:01Z",
        assets=tuple(
            CandidateAsset(
                name=name,
                url=f"https://github.com/example/runtime/releases/download/v1/{name}",
                sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            )
            for name, payload in assets
        ),
    )


def _intake(root: Path, source: str, assets: list[tuple[str, bytes]]) -> Path:
    root.mkdir(parents=True)
    candidate = _candidate(source, assets)
    observed: list[IntakeAsset] = []
    for asset, (_, payload) in zip(candidate.assets, assets, strict=True):
        (root / asset.name).write_bytes(payload)
        assert asset.sha256 is not None
        observed.append(
            IntakeAsset(
                name=asset.name,
                url=asset.url,
                sha256=asset.sha256,
                size=asset.size,
                path=asset.name,
            )
        )
    manifest = root / "intake.json"
    write_json(manifest, Intake(candidate, tuple(observed)).to_dict())
    return manifest


def _zip_bytes(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return path.read_bytes()


def test_android_normalization_is_complete_and_provenanced(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    artifact = config.artifact("android")
    required = [*artifact.required_libraries, "libavfilter.so"]
    apk_files = {
        f"lib/{abi}/{name}": f"{abi}:{name}".encode()
        for abi in artifact.architectures
        for name in required
        if name != "libmediakitandroidhelper.so"
    }
    apk = _zip_bytes(tmp_path / "runtime.apk", apk_files)
    libmpv = _intake(tmp_path / "libmpv", "android_libmpv", [("runtime.apk", apk)])
    helpers: list[tuple[str, bytes]] = []
    for abi in artifact.architectures:
        payload = _zip_bytes(
            tmp_path / f"helper-{abi}.jar",
            {f"jni/{abi}/libmediakitandroidhelper.so": abi.encode()},
        )
        helpers.append((f"helper-{abi}.jar", payload))
    helper = _intake(tmp_path / "helper", "android_helper", helpers)
    stage = normalize(config, artifact, [libmpv, helper], tmp_path / "stage")
    for abi in artifact.architectures:
        assert {path.name for path in (stage / "jniLibs" / abi).glob("*.so")} >= set(required)
    provenance = read_json(stage / "libmpv-runtime.json")
    assert provenance["schemaVersion"] == 2
    assert {item["candidate"]["source"] for item in provenance["intakes"]} == {
        "android_libmpv",
        "android_helper",
    }
