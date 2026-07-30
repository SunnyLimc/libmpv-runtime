from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from libmpv_runtime.package import artifact_name
from libmpv_runtime.release import create_release_index

_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_BEHAVIOR_REFERENCES = {
    "android-arm64-v8a": "android-x86_64",
    "android-armeabi-v7a": "android-x86_64",
    "android-x86": "android-x86_64",
    "ios-universal": "macos-universal",
}


def _manifest(config: object, target: str) -> bytes:
    reference = _BEHAVIOR_REFERENCES.get(target)
    behavior = {"mode": "native"}
    if reference is not None:
        behavior = {"mode": "source-equivalent", "referenceTarget": reference}
    return json.dumps(
        {
            "runtimeVersion": config.lock.runtime_version,
            "target": {"name": target},
            "source": {"commit": _COMMIT, "dirty": False},
            "capabilities": {
                "evidence": {
                    "target": target,
                    "details": {"behavior": behavior},
                }
            },
        }
    ).encode()


def _write_archive(path: Path, config: object, target: str) -> None:
    manifest = _manifest(config, target)
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, mode="w:gz") as archive:
            info = tarfile.TarInfo("share/libmpv-runtime/build-manifest.json")
            info.size = len(manifest)
            archive.addfile(info, io.BytesIO(manifest))
        return
    with zipfile.ZipFile(path, mode="w") as archive:
        if path.suffix == ".aar":
            for abi in ("arm64-v8a", "armeabi-v7a", "x86_64", "x86"):
                archive.writestr(
                    f"assets/libmpv-runtime/{abi}/build-manifest.json",
                    _manifest(config, f"android-{abi}"),
                )
        elif path.suffix == ".jar":
            archive.writestr("META-INF/libmpv-runtime/build-manifest.json", manifest)
        else:
            archive.writestr("share/libmpv-runtime/build-manifest.json", manifest)


def _release_artifacts(tmp_path: Path, config: object) -> list[Path]:
    artifacts: list[Path] = []
    for target in config.targets.values():
        artifact = tmp_path / artifact_name(config, target)
        _write_archive(artifact, config, target.name)
        artifacts.append(artifact)
    aar = tmp_path / f"libmpv-runtime_v{config.lock.runtime_version}_android-universal.aar"
    _write_archive(aar, config, "android-universal")
    artifacts.append(aar)
    return artifacts


def test_release_index_requires_complete_platform_set(
    tmp_path: Path, config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", _COMMIT)
    artifacts = _release_artifacts(tmp_path, config)
    with pytest.raises(ValueError, match="incomplete release set"):
        create_release_index(artifacts[:-1], tmp_path / "release-index.json", config)


def test_release_index_contains_every_expected_artifact(
    tmp_path: Path, config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", _COMMIT)
    artifacts = _release_artifacts(tmp_path, config)
    output = tmp_path / "release-index.json"
    create_release_index(artifacts, output, config)
    index = json.loads(output.read_text(encoding="utf-8"))
    assert index["runtimeVersion"] == config.lock.runtime_version
    assert {entry["name"] for entry in index["artifacts"]} == {path.name for path in artifacts}
    assert (tmp_path / "SHA256SUMS").is_file()


def test_release_index_rejects_missing_behavior_reference(
    tmp_path: Path, config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", _COMMIT)
    monkeypatch.setitem(_BEHAVIOR_REFERENCES, "ios-universal", "missing-target")
    artifacts = _release_artifacts(tmp_path, config)
    with pytest.raises(ValueError, match="references missing behavior target"):
        create_release_index(artifacts, tmp_path / "release-index.json", config)
