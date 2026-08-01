from __future__ import annotations

import re
from pathlib import Path

from libmpv_runtime.models import RepositoryConfig


def test_contract_has_one_runtime_authority_per_platform(config: RepositoryConfig) -> None:
    assert set(config.contract.artifacts) == {"windows-x86_64", "android", "macos", "ios"}
    assert config.contract.linux.soname_major == 2
    assert config.contract.linux.profiles["debian-13"].os_id == "debian"
    arch_version = config.contract.linux.profiles["arch"].version_pattern
    assert re.fullmatch(arch_version, "")
    assert re.fullmatch(arch_version, "20260726.0.562117")
    assert not re.fullmatch(arch_version, "stable")
    assert config.contract.schema_version == 3
    assert set(config.contract.consumers) == {"minimum", "current"}
    assert config.contract.toolchain.flutter == "3.44.7"
    assert config.contract.toolchain.android_emulator_api == 35
    assert config.contract.required_audio_filters == (
        "loudnorm",
        "dynaudnorm",
        "acompressor",
        "alimiter",
        "volume",
        "aresample",
        "ebur128",
        "astats",
    )


def test_source_rules_select_channels_not_versions(config: RepositoryConfig) -> None:
    assert all(source.release == "latest" for source in config.sources.values())
    assert all(source.asset_patterns for source in config.sources.values())
    assert config.sources["windows_libmpv"].repository == "zhongfly/mpv-winbuild"
    assert config.sources["android_libmpv"].repository == "mpv-android/mpv-android"
    assert "encodersgpl" in config.sources["darwin_macos"].asset_patterns[0]


def test_all_source_equivalent_behavior_has_a_release_peer(
    config: RepositoryConfig,
) -> None:
    ios = config.artifact("ios")
    assert ios.behavior_mode == "source-equivalent"
    assert ios.behavior_reference == "macos"
    assert config.source(ios.sources[0]).repository == config.source("darwin_macos").repository


def test_source_build_architecture_is_removed(repository_root: Path) -> None:
    assert not (repository_root / "runtime.lock.toml").exists()
    assert not (repository_root / "targets.toml").exists()
    assert not any(path.is_file() for path in (repository_root / "patches").rglob("*"))
    assert not any(path.is_file() for path in (repository_root / "scripts" / "build").rglob("*"))
