from __future__ import annotations

import shutil
import struct
import tarfile
import wave
from pathlib import Path

import pytest

from libmpv_runtime import consumer as consumer_module
from libmpv_runtime import evidence as evidence_module
from libmpv_runtime import probe as probe_module
from libmpv_runtime.consumer import run_consumer
from libmpv_runtime.errors import VerificationError
from libmpv_runtime.evidence import create_consumer_report
from libmpv_runtime.files import read_json, remove_tree, write_json
from libmpv_runtime.models import RepositoryConfig
from libmpv_runtime.normalize import _normalize_darwin
from libmpv_runtime.package import package_stage
from libmpv_runtime.pcm import create_fixture
from libmpv_runtime.plan import load_plan
from libmpv_runtime.probe import run_probe


def _scale(source: Path, destination: Path, factor: float) -> None:
    with wave.open(str(source), mode="rb") as input_file:
        parameters = input_file.getparams()
        frames = input_file.readframes(input_file.getnframes())
    scaled = bytearray()
    for (sample,) in struct.iter_unpack("<h", frames):
        scaled.extend(struct.pack("<h", round(sample * factor)))
    with wave.open(str(destination), mode="wb") as output:
        output.setparams(parameters)
        output.writeframes(scaled)


def test_probe_adapter_owns_workspace_and_verifies_decoded_pcm(
    monkeypatch: pytest.MonkeyPatch,
    config: RepositoryConfig,
    validation_plan: Path,
) -> None:
    work = config.root / "work" / "pytest-probe-adapter"
    stage = config.root / "work" / "pytest-probe-stage"
    stage.mkdir(parents=True, exist_ok=True)
    plan = load_plan(validation_plan)
    candidate = plan.candidates["windows_libmpv"]
    angle = plan.candidates["windows_angle"]
    write_json(
        stage / "libmpv-runtime.json",
        {
            "schemaVersion": 2,
            "artifact": "windows-x86_64",
            "contract": "contracts/runtime.toml",
            "intakes": [
                {
                    "schemaVersion": 2,
                    "candidate": item.to_dict(),
                    "assets": [{**asset.to_dict(), "path": asset.name} for asset in item.assets],
                }
                for item in (candidate, angle)
            ],
        },
    )
    report = config.root / "work" / "pytest-probe-report.json"

    def fake_run(_: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        assert cwd == config.root
        assert env["LIBMPV_RUNTIME_ANDROID_MIN_SDK"] == "23"
        output = Path(env["LIBMPV_RUNTIME_OUTPUT"])
        source = output / "input.wav"
        create_fixture(source, seconds=0.1)
        for item in config.contract.probe.filters:
            shutil.copy2(source, output / f"{item.name}.wav")
        _scale(source, output / "volume-http.wav", 0.5)

    monkeypatch.setattr(probe_module, "run", fake_run)
    try:
        result = run_probe(
            config,
            "windows-x86_64",
            validation_plan,
            stage,
            work,
            report,
        )
        value = read_json(result)
        assert value["mode"] == "native"
        assert value["measuredGainDb"] == pytest.approx(-6.0206, abs=0.01)
        assert {item["name"] for item in value["filters"]} == set(
            config.contract.required_audio_filters
        )
        provenance = read_json(stage / "libmpv-runtime.json")
        provenance["intakes"][0]["candidate"]["discoveredAt"] = "changed"
        write_json(stage / "libmpv-runtime.json", provenance)
        with pytest.raises(VerificationError, match="another validation plan"):
            run_probe(
                config,
                "windows-x86_64",
                validation_plan,
                stage,
                work,
                report,
            )
    finally:
        if work.exists():
            remove_tree(work, root=config.root)
        if stage.exists():
            remove_tree(stage, root=config.root)
        report.unlink(missing_ok=True)


def test_consumer_adapter_checks_exact_profile_and_collects_report(
    monkeypatch: pytest.MonkeyPatch,
    config: RepositoryConfig,
    validation_plan: Path,
) -> None:
    work = config.root / "work" / "pytest-consumer-adapter"
    artifact = config.root / "work" / "pytest-runtime.zip"
    report = config.root / "work" / "pytest-consumer.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"fixture")
    monkeypatch.setattr(consumer_module, "_flutter_version", lambda _: "3.44.7")

    def fake_run(_: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        assert cwd == config.root
        write_json(Path(env["LIBMPV_RUNTIME_REPORT"]), {"passed": True})

    monkeypatch.setattr(consumer_module, "run", fake_run)
    try:
        result = run_consumer(
            config,
            validation_plan,
            "windows",
            {"windows-x86_64": [artifact]},
            work,
            {"windows-x86_64": report},
            "minimum",
        )
        assert result["windows-x86_64"] == report
    finally:
        if work.exists():
            remove_tree(work, root=config.root)
        artifact.unlink(missing_ok=True)
        report.unlink(missing_ok=True)


def test_consumer_report_records_observed_flutter_and_pub_versions(
    monkeypatch: pytest.MonkeyPatch,
    config: RepositoryConfig,
    validation_plan: Path,
    tmp_path: Path,
) -> None:
    profile = config.contract.consumers["current"]
    monkeypatch.setattr(
        evidence_module,
        "_package_versions",
        lambda _: {
            "media_kit": profile.media_kit,
            "media_kit_video": profile.media_kit_video,
        },
    )
    monkeypatch.setattr(evidence_module, "_flutter_version", lambda: "3.44.7")
    output = tmp_path / "consumer.json"
    artifact = tmp_path / "libmpv-runtime-macos.tar.gz"
    artifact.write_bytes(b"fixture artifact")
    create_consumer_report(
        config,
        validation_plan,
        "macos",
        "current",
        tmp_path,
        [artifact],
        {
            "platform": "macos",
            "onlinePlayback": "passed",
            "filterAfterLoad": "passed",
        },
        output,
    )
    assert read_json(output)["packages"]["media_kit"] == profile.media_kit


def test_darwin_normalization_flattens_one_archive_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "release"
    for name in ("Mpv", "Avfilter"):
        framework = nested / f"{name}.xcframework"
        framework.mkdir(parents=True)
        (framework / "Info.plist").write_bytes(name.encode())
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, mode="w:gz") as value:
        value.add(nested, arcname="release")
    output = tmp_path / "output"
    output.mkdir()
    _normalize_darwin({"darwin_macos": [archive]}, "darwin_macos", output)
    assert (output / "Mpv.xcframework/Info.plist").is_file()
    assert not (output / "release").exists()


def test_apple_package_emits_bundle_components_and_checksums(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    stage = tmp_path / "stage"
    for name in ("Mpv", "Avfilter"):
        framework = stage / f"{name}.xcframework"
        framework.mkdir(parents=True)
        (framework / "Info.plist").write_bytes(name.encode())
    (stage / "libmpv-runtime.json").write_text("{}\n", encoding="utf-8")
    outputs = package_stage(config.artifact("macos"), stage, tmp_path / "dist")
    assert {path.name for path in outputs} == {
        "libmpv-runtime-macos.tar.gz",
        "libmpv-runtime-macos-Mpv.zip",
        "libmpv-runtime-macos-Avfilter.zip",
    }
    assert all(path.with_name(f"{path.name}.sha256").is_file() for path in outputs)
