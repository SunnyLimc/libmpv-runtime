from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from libmpv_runtime.errors import IntegrityError, VerificationError
from libmpv_runtime.evidence import seal_evidence, seal_linux_evidence
from libmpv_runtime.files import read_json, sha256_file, sha256_json, write_json
from libmpv_runtime.generate import generate_packages
from libmpv_runtime.models import RepositoryConfig
from libmpv_runtime.plan import load_plan
from libmpv_runtime.promotion import assemble, load_promotion
from libmpv_runtime.validation import seal_validation_run, verify_validation_run


def _provenance(config: RepositoryConfig, validation_plan: Path, target: str) -> dict[str, Any]:
    plan = load_plan(validation_plan)
    intakes: list[dict[str, Any]] = []
    for source in config.artifact(target).sources:
        candidate = plan.candidates[source]
        intakes.append(
            {
                "schemaVersion": 2,
                "candidate": candidate.to_dict(),
                "assets": [
                    {
                        **asset.to_dict(),
                        "path": asset.name,
                    }
                    for asset in candidate.assets
                ],
            }
        )
    return {
        "schemaVersion": 2,
        "artifact": target,
        "contract": "contracts/runtime.toml",
        "intakes": intakes,
    }


def _behavior(config: RepositoryConfig, validation_plan: Path, target: str) -> dict[str, Any]:
    artifact = config.artifact(target)
    provenance = _provenance(config, validation_plan, target)
    return {
        "schemaVersion": 1,
        "kind": "behavior",
        "target": target,
        "mode": artifact.behavior_mode,
        "referenceTarget": artifact.behavior_reference,
        "planSha256": sha256_file(validation_plan),
        "architectures": list(artifact.behavior_architectures),
        "filters": [
            {
                "name": item.name,
                "expression": item.expression,
                "sha256": "e" * 64,
                "size": 512,
            }
            for item in config.contract.probe.filters
        ],
        "expectedGainDb": config.contract.probe.expected_gain_db,
        "gainToleranceDb": config.contract.probe.gain_tolerance_db,
        "measuredGainDb": config.contract.probe.expected_gain_db,
        "httpRange": True,
        "filterAfterLoad": True,
        "stageProvenanceSha256": (
            None if artifact.behavior_mode == "source-equivalent" else sha256_json(provenance)
        ),
    }


def _details(target: str) -> dict[str, str]:
    if target == "android":
        return {
            "platform": "android",
            "onlinePlayback": "passed",
            "filterAfterLoad": "passed",
            "jniHelper": "passed",
        }
    if target == "windows-x86_64":
        return {
            "platform": "windows",
            "onlinePlayback": "passed",
            "filterAfterLoad": "passed",
        }
    if target == "macos":
        return {
            "platform": "macos",
            "onlinePlayback": "passed",
            "filterAfterLoad": "passed",
        }
    return {
        "platform": "ios-simulator",
        "compileLink": "passed",
        "pluginRegistration": "passed",
    }


def _sealed_evidence(
    config: RepositoryConfig,
    validation_plan: Path,
    target: str,
    root: Path,
    artifact_paths: list[Path],
) -> Path:
    reports = root / "reports" / target
    structure = reports / "structure.json"
    behavior = reports / "behavior.json"
    provenance = _provenance(config, validation_plan, target)
    write_json(
        structure,
        {
            "schemaVersion": 1,
            "kind": "structure",
            "target": target,
            "requiredFilters": list(config.contract.required_audio_filters),
            "details": {"fixture": True},
            "provenance": provenance,
        },
    )
    write_json(behavior, _behavior(config, validation_plan, target))
    consumers: dict[str, Path] = {}
    plan = load_plan(validation_plan)
    for name, profile in plan.consumers.items():
        path = reports / f"consumer-{name}.json"
        write_json(
            path,
            {
                "schemaVersion": 1,
                "kind": "consumer",
                "target": target,
                "planSha256": sha256_file(validation_plan),
                "profile": name,
                "flutter": plan.toolchain.flutter,
                "packages": {
                    "media_kit": profile.media_kit,
                    "media_kit_video": profile.media_kit_video,
                },
                "artifacts": [
                    {
                        "name": artifact.name,
                        "sha256": sha256_file(artifact),
                        "size": artifact.stat().st_size,
                    }
                    for artifact in sorted(artifact_paths, key=lambda item: item.name)
                ],
                "details": _details(target),
            },
        )
        consumers[name] = path
    output = root / f"{target}.json"
    seal_evidence(config, validation_plan, target, structure, behavior, consumers, output)
    return output


def _bundle(path: Path, provenance: dict[str, Any]) -> None:
    payload = json.dumps(provenance).encode()
    if path.suffix == ".zip":
        with zipfile.ZipFile(path, mode="w") as archive:
            archive.writestr("libmpv-runtime.json", payload)
        return
    manifest = path.parent / f"{path.name}.manifest" / "libmpv-runtime.json"
    manifest.parent.mkdir()
    manifest.write_bytes(payload)
    with tarfile.open(path, mode="w:gz") as archive:
        archive.add(manifest, arcname="libmpv-runtime.json")
        target = "macos" if "-macos" in path.name else "ios"
        for framework in ("Mpv", "Avfilter", "Avcodec"):
            payload = f"{target}:{framework}".encode()
            info = tarfile.TarInfo(f"{framework}.xcframework/Info.plist")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _validated_inputs(
    config: RepositoryConfig, validation_plan: Path, root: Path
) -> tuple[dict[str, list[Path]], dict[str, Path], list[Path]]:
    artifacts: dict[str, list[Path]] = {}
    evidence: dict[str, Path] = {}
    for target in config.contract.artifacts:
        provenance = _provenance(config, validation_plan, target)
        extension = ".tar.gz" if target in {"macos", "ios"} else ".zip"
        bundle = root / f"libmpv-runtime-{target}{extension}"
        _bundle(bundle, provenance)
        paths = [bundle]
        if target in {"macos", "ios"}:
            for framework in ("Mpv", "Avfilter", "Avcodec"):
                component = root / f"libmpv-runtime-{target}-{framework}.zip"
                with zipfile.ZipFile(component, mode="w") as archive:
                    archive.writestr(
                        f"{framework}.xcframework/Info.plist",
                        f"{target}:{framework}".encode(),
                    )
                paths.append(component)
        artifacts[target] = paths
        evidence[target] = _sealed_evidence(
            config,
            validation_plan,
            target,
            root,
            paths,
        )

    linux: list[Path] = []
    versions = {
        "debian-12": "12",
        "debian-13": "13",
        "ubuntu-24.04": "24.04",
        "fedora": "44",
        "arch": "",
    }
    for profile, contract in config.contract.linux.profiles.items():
        structure = root / "reports" / f"linux-{profile}-structure.json"
        behavior = root / "reports" / f"linux-{profile}-behavior.json"
        write_json(
            structure,
            {
                "schemaVersion": 1,
                "kind": "linux-structure",
                "planSha256": sha256_file(validation_plan),
                "profile": profile,
                "osRelease": {"id": contract.os_id, "versionId": versions[profile]},
                "library": "libmpv.so.2",
                "clientApi": "2.5",
                "runtimePackages": list(contract.runtime_packages),
            },
        )
        value = _behavior(config, validation_plan, "macos")
        value.update(
            {
                "target": "linux-system",
                "mode": "native",
                "referenceTarget": None,
                "architectures": ["system"],
                "stageProvenanceSha256": None,
            }
        )
        write_json(behavior, value)
        output = root / f"linux-system-{profile}.json"
        seal_linux_evidence(config, validation_plan, profile, structure, behavior, output)
        linux.append(output)
    return artifacts, evidence, linux


def test_sealing_requires_every_consumer_profile(
    config: RepositoryConfig, validation_plan: Path, tmp_path: Path
) -> None:
    target = "windows-x86_64"
    bundle = tmp_path / "libmpv-runtime-windows-x86_64.zip"
    _bundle(bundle, _provenance(config, validation_plan, target))
    complete = _sealed_evidence(config, validation_plan, target, tmp_path, [bundle])
    value = read_json(complete)
    assert set(value["consumers"]) == {"minimum", "current"}
    reports = tmp_path / "reports" / target
    with pytest.raises(VerificationError, match="profile set mismatch"):
        seal_evidence(
            config,
            validation_plan,
            target,
            reports / "structure.json",
            reports / "behavior.json",
            {"current": reports / "consumer-current.json"},
            tmp_path / "incomplete.json",
        )
    current_path = reports / "consumer-current.json"
    current = read_json(current_path)
    current["artifacts"][0]["sha256"] = "f" * 64
    write_json(current_path, current)
    with pytest.raises(VerificationError, match="different artifacts"):
        seal_evidence(
            config,
            validation_plan,
            target,
            reports / "structure.json",
            reports / "behavior.json",
            {
                "minimum": reports / "consumer-minimum.json",
                "current": current_path,
            },
            tmp_path / "mismatched.json",
        )
    with pytest.raises(IntegrityError, match="already exists"):
        seal_evidence(
            config,
            validation_plan,
            target,
            reports / "structure.json",
            reports / "behavior.json",
            {
                "minimum": reports / "consumer-minimum.json",
                "current": reports / "consumer-current.json",
            },
            complete,
        )


def test_validation_fan_in_detects_any_changed_byte(
    config: RepositoryConfig, validation_plan: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    _validated_inputs(config, validation_plan, input_root)
    sealed = tmp_path / "sealed"
    index = seal_validation_run(config, validation_plan, input_root, sealed)
    assert index.is_file()
    assert verify_validation_run(config, sealed)["planSha256"] == sha256_file(validation_plan)
    (sealed / "android.json").write_text("changed", encoding="utf-8")
    with pytest.raises(VerificationError, match="changed"):
        verify_validation_run(config, sealed)


def test_promotion_is_plan_bound_and_generates_real_dropin_packages(
    config: RepositoryConfig, validation_plan: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    artifacts, evidence, linux = _validated_inputs(config, validation_plan, input_root)
    macos_component = artifacts["macos"][1]
    original_component = macos_component.read_bytes()
    with zipfile.ZipFile(macos_component, mode="w") as archive:
        archive.writestr("Mpv.xcframework/Info.plist", b"changed")
    with pytest.raises(VerificationError, match="does not match aggregate"):
        assemble(
            config,
            "runtime-20260801.2",
            validation_plan,
            artifacts,
            evidence,
            linux,
            tmp_path / "bad-promotion",
        )
    macos_component.write_bytes(original_component)
    manifest = assemble(
        config,
        "runtime-20260801.1",
        validation_plan,
        artifacts,
        evidence,
        linux,
        tmp_path / "promotion",
    )
    promotion = load_promotion(manifest)
    assert promotion["schemaVersion"] == 2
    assert promotion["validationPlan"]["sha256"] == sha256_file(validation_plan)
    assert len(promotion["linux"]["validationReports"]) == len(config.contract.linux.profiles)
    windows = promotion["artifacts"]["windows-x86_64"][0]
    assert windows["url"].endswith("/runtime-20260801.1/libmpv-runtime-windows-x86_64.zip")

    packages = generate_packages(config, manifest, tmp_path / "packages")
    names = {path.name for path in packages.iterdir() if path.is_dir()}
    assert names == {
        "media_kit_libs_android_video",
        "media_kit_libs_windows_video",
        "media_kit_libs_ios_video",
        "media_kit_libs_macos_video",
    }
    gradle = (packages / "media_kit_libs_android_video/android/build.gradle").read_text(
        encoding="utf-8"
    )
    assert "SHA-256" in gradle
    assert str(config.contract.toolchain.android_compile_sdk) in gradle
    cmake = (packages / "media_kit_libs_windows_video/windows/CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert windows["sha256"] in cmake
    assert "EXPECTED_HASH" in cmake
    makefile = (packages / "media_kit_libs_macos_video/macos/Makefile").read_text(encoding="utf-8")
    assert "shasum -a 256 -c -" in makefile
    swift = (
        packages / "media_kit_libs_macos_video/macos/media_kit_libs_macos_video/Package.swift"
    ).read_text(encoding="utf-8")
    assert "swift-tools-version: 5.9" in swift
    assert '"Fftools-ffi"' not in swift
