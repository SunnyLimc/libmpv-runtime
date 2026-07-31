from __future__ import annotations

import json
import tarfile
import zipfile
from pathlib import Path

from libmpv_runtime.evidence import (
    create_structure_evidence,
    record_behavior,
    record_consumer,
)
from libmpv_runtime.generate import generate_packages
from libmpv_runtime.models import RepositoryConfig
from libmpv_runtime.promotion import assemble, load_promotion


def _complete_evidence(
    config: RepositoryConfig, target: str, path: Path, provenance: dict[str, object]
) -> Path:
    create_structure_evidence(
        path,
        target=target,
        filters=config.contract.required_audio_filters,
        details={"fixture": True},
        provenance=provenance,
    )
    record_behavior(
        path,
        filters=list(config.contract.required_audio_filters),
        measured_gain_db=-6.0206,
        mode="native",
        reference_target=None,
    )
    return record_consumer(path, details={"mediaKit": "passed"})


def test_promotion_is_immutable_and_generates_exact_name_dropins(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    artifacts: dict[str, list[Path]] = {}
    evidence: dict[str, Path] = {}
    for target in config.contract.artifacts:
        extension = ".tar.gz" if target in {"macos", "ios"} else ".zip"
        bundle = tmp_path / f"libmpv-runtime-{target}{extension}"
        provenance = {"schemaVersion": 1, "artifact": target, "fixture": True}
        manifest = json.dumps(provenance).encode()
        if extension == ".zip":
            with zipfile.ZipFile(bundle, mode="w") as archive:
                archive.writestr("libmpv-runtime.json", manifest)
        else:
            manifest_path = tmp_path / target / "libmpv-runtime.json"
            manifest_path.parent.mkdir()
            manifest_path.write_bytes(manifest)
            with tarfile.open(bundle, mode="w:gz") as archive:
                archive.add(manifest_path, arcname="libmpv-runtime.json")
        paths = [bundle]
        if target in {"macos", "ios"}:
            for framework in ("Mpv", "Avfilter", "Avcodec"):
                component = tmp_path / f"libmpv-runtime-{target}-{framework}.zip"
                component.write_bytes(f"{target}:{framework}".encode())
                paths.append(component)
        artifacts[target] = paths
        evidence_path = tmp_path / f"{target}.evidence.json"
        evidence[target] = _complete_evidence(config, target, evidence_path, provenance)

    linux_report = tmp_path / "linux-system.json"
    linux_report.write_text(
        json.dumps(
            {
                "profile": "ubuntu-24.04",
                "library": "libmpv.so.2",
                "clientApi": "2.5",
                "runtimePackages": ["libmpv2"],
            }
        ),
        encoding="utf-8",
    )
    manifest = assemble(
        config,
        "runtime-20260801.1",
        artifacts,
        evidence,
        [linux_report],
        tmp_path / "promotion",
    )
    promotion = load_promotion(manifest)
    assert promotion["id"] == "runtime-20260801.1"
    linux = promotion["linux"]["validationReports"]
    assert linux[0]["profile"] == "ubuntu-24.04"
    assert len(linux[0]["sha256"]) == 64
    windows = promotion["artifacts"]["windows-x86_64"][0]
    assert windows["url"].endswith("/runtime-20260801.1/libmpv-runtime-windows-x86_64.zip")
    assert len(windows["sha256"]) == 64

    packages = generate_packages(manifest, tmp_path / "packages")
    names = {path.name for path in packages.iterdir() if path.is_dir()}
    assert names == {
        "media_kit_libs_android_video",
        "media_kit_libs_windows_video",
        "media_kit_libs_ios_video",
        "media_kit_libs_macos_video",
    }
    for name in names:
        pubspec = (packages / name / "pubspec.yaml").read_text(encoding="utf-8")
        assert f"name: {name}" in pubspec
        assert "publish_to: none" in pubspec
    gradle = (packages / "media_kit_libs_android_video" / "android" / "build.gradle").read_text(
        encoding="utf-8"
    )
    assert windows["sha256"] not in gradle
    assert "SHA-256" in gradle
    cmake = (packages / "media_kit_libs_windows_video" / "windows" / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert windows["sha256"] in cmake
    assert "EXPECTED_HASH" in cmake
    assert 'file(COPY "${RUNTIME_ROOT}/ANGLE/"' in cmake
    assert 'DESTINATION "${CMAKE_BINARY_DIR}/ANGLE"' in cmake
    makefile = (packages / "media_kit_libs_macos_video" / "macos" / "Makefile").read_text(
        encoding="utf-8"
    )
    assert "shasum -a 256 -c -" in makefile
    assert "printf '%s  %s\\n'" in makefile
    assert "<<<" not in makefile
    swift = (
        packages
        / "media_kit_libs_macos_video"
        / "macos"
        / "media_kit_libs_macos_video"
        / "Package.swift"
    ).read_text(encoding="utf-8")
    assert '"Fftools-ffi"' not in swift
