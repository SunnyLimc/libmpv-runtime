from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

from libmpv_runtime.evidence import write_evidence
from libmpv_runtime.files import sha256_file
from libmpv_runtime.package import package_target


def test_windows_package_contains_manifest_sbom_and_source_lock(
    tmp_path: Path,
    config: object,
    monkeypatch: object,
) -> None:
    (tmp_path / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    (tmp_path / "NOTICE").write_text("notice fixture\n", encoding="utf-8")
    config = replace(config, root=tmp_path)
    stage = tmp_path / "stage"
    (stage / "include" / "mpv").mkdir(parents=True)
    (stage / "libmpv-2.dll").write_bytes(b"MZ deterministic fixture")
    (stage / "include" / "mpv" / "client.h").write_text(
        "unsigned long mpv_client_api_version(void);\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.json"
    write_evidence(
        evidence,
        target="windows-x86_64",
        filters=list(config.lock.required_audio_filters),
        structure=True,
        behavior=True,
        consumer=True,
    )
    monkeypatch.setattr(
        "libmpv_runtime.package.collect_core_licenses",
        lambda _config, destination: (destination / "LGPL.txt").write_text(
            "fixture license\n",
            encoding="utf-8",
        ),
    )
    (tmp_path / "build" / "evidence").mkdir(parents=True)
    evidence.replace(tmp_path / "build" / "evidence" / "windows-x86_64.json")

    target = config.target("windows-x86_64")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    package_target(config, target, stage=stage, output=first)
    package_target(config, target, stage=stage, output=second)
    assert sha256_file(first) == sha256_file(second)

    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        metadata = "share/libmpv-runtime"
        assert f"{metadata}/build-manifest.json" in names
        assert f"{metadata}/sbom.spdx.json" in names
        assert f"{metadata}/source-lock.json" in names
        manifest = json.loads(archive.read(f"{metadata}/build-manifest.json"))
        assert manifest["target"]["loadName"] == "libmpv-2.dll"
        assert manifest["capabilities"]["evidence"]["checks"]["behavior"] is True
