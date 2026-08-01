from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .models import (
    ArtifactContract,
    ConsumerProfile,
    LinuxContract,
    LinuxProfile,
    ProbeContract,
    ProbeFilter,
    RepositoryConfig,
    RuntimeContract,
    SourceRule,
    ToolchainContract,
)

_SUPPORTED_PLATFORMS = frozenset({"android", "windows", "macos", "ios"})
_SUPPORTED_PACKAGES = frozenset({"zip", "xcframeworks"})
_BEHAVIOR_MODES = frozenset({"native", "native-subset", "source-equivalent"})
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def find_repository_root(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / "contracts" / "runtime.toml").is_file() and (
            directory / "sources" / "upstreams.toml"
        ).is_file():
            return directory
    raise ConfigurationError("could not find contracts/runtime.toml and sources/upstreams.toml")


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            value = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{path} must contain a TOML table")
    return value


def _table(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{owner} must be a table")
    return value


def _texts(value: Any, owner: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ConfigurationError(f"{owner} must be a non-empty string array")
    return tuple(value)


def load_contract(path: Path) -> RuntimeContract:
    data = _load_toml(path)
    if data.get("schema_version") != 3:
        raise ConfigurationError("contracts/runtime.toml schema_version must be 3")
    minimum_media_kit = data.get("minimum_media_kit")
    minimum_media_kit_video = data.get("minimum_media_kit_video")
    if not isinstance(minimum_media_kit, str) or not minimum_media_kit:
        raise ConfigurationError("minimum_media_kit must be a non-empty string")
    if not isinstance(minimum_media_kit_video, str) or not minimum_media_kit_video:
        raise ConfigurationError("minimum_media_kit_video must be a non-empty string")
    toolchain_table = _table(data.get("toolchain"), "toolchain")
    toolchain = ToolchainContract(
        python=_nonempty(toolchain_table.get("python"), "toolchain.python"),
        flutter=_nonempty(toolchain_table.get("flutter"), "toolchain.flutter"),
        dart_sdk=_nonempty(toolchain_table.get("dart_sdk"), "toolchain.dart_sdk"),
        android_gradle_plugin=_nonempty(
            toolchain_table.get("android_gradle_plugin"), "toolchain.android_gradle_plugin"
        ),
        android_compile_sdk=_positive_int(
            toolchain_table.get("android_compile_sdk"), "toolchain.android_compile_sdk"
        ),
        android_min_sdk=_positive_int(
            toolchain_table.get("android_min_sdk"), "toolchain.android_min_sdk"
        ),
        android_emulator_api=_positive_int(
            toolchain_table.get("android_emulator_api"),
            "toolchain.android_emulator_api",
        ),
        cmake_minimum=_nonempty(toolchain_table.get("cmake_minimum"), "toolchain.cmake_minimum"),
        swift_tools=_nonempty(toolchain_table.get("swift_tools"), "toolchain.swift_tools"),
        ios_deployment_target=_nonempty(
            toolchain_table.get("ios_deployment_target"),
            "toolchain.ios_deployment_target",
        ),
        macos_deployment_target=_nonempty(
            toolchain_table.get("macos_deployment_target"),
            "toolchain.macos_deployment_target",
        ),
    )
    consumer_tables = _table(data.get("consumer"), "consumer")
    consumers = {
        name: ConsumerProfile(
            name=name,
            media_kit=_nonempty(
                _table(value, f"consumer.{name}").get("media_kit"), f"consumer.{name}.media_kit"
            ),
            media_kit_video=_nonempty(
                _table(value, f"consumer.{name}").get("media_kit_video"),
                f"consumer.{name}.media_kit_video",
            ),
        )
        for name, value in consumer_tables.items()
    }
    if set(consumers) != {"minimum", "current"}:
        raise ConfigurationError("consumer must define minimum and current profiles")
    if consumers["minimum"].media_kit != minimum_media_kit:
        raise ConfigurationError("consumer.minimum.media_kit must equal minimum_media_kit")
    if consumers["minimum"].media_kit_video != minimum_media_kit_video:
        raise ConfigurationError(
            "consumer.minimum.media_kit_video must equal minimum_media_kit_video"
        )

    probe_table = _table(data.get("probe"), "probe")
    raw_filters = probe_table.get("filters")
    if not isinstance(raw_filters, list) or not raw_filters:
        raise ConfigurationError("probe.filters must be a non-empty table array")
    filters = tuple(
        ProbeFilter(
            name=_nonempty(_table(value, "probe.filters[]").get("name"), "probe.filters[].name"),
            expression=_nonempty(
                _table(value, "probe.filters[]").get("expression"),
                "probe.filters[].expression",
            ),
        )
        for value in raw_filters
    )
    if len({item.name for item in filters}) != len(filters):
        raise ConfigurationError("probe.filters contains duplicate names")
    expected_gain = probe_table.get("expected_gain_db")
    tolerance = probe_table.get("gain_tolerance_db")
    if not isinstance(expected_gain, (int, float)) or not isinstance(tolerance, (int, float)):
        raise ConfigurationError("probe gain values must be numeric")
    if float(tolerance) <= 0:
        raise ConfigurationError("probe.gain_tolerance_db must be positive")
    after_load = _nonempty(
        probe_table.get("http_after_load_filter"), "probe.http_after_load_filter"
    )
    if after_load not in {item.name for item in filters}:
        raise ConfigurationError("probe.http_after_load_filter is not a probe filter")
    probe = ProbeContract(
        filters=filters,
        expected_gain_db=float(expected_gain),
        gain_tolerance_db=float(tolerance),
        http_after_load_filter=after_load,
    )

    artifact_tables = _table(data.get("artifact"), "artifact")
    artifacts = {
        name: ArtifactContract.from_table(name, _table(value, f"artifact.{name}"))
        for name, value in artifact_tables.items()
    }
    if set(artifacts) != {"windows-x86_64", "android", "macos", "ios"}:
        raise ConfigurationError(
            "artifact contract must define windows-x86_64, android, macos and ios"
        )
    for artifact in artifacts.values():
        if artifact.platform not in _SUPPORTED_PLATFORMS:
            raise ConfigurationError(f"artifact.{artifact.name}.platform is unsupported")
        if artifact.package not in _SUPPORTED_PACKAGES:
            raise ConfigurationError(f"artifact.{artifact.name}.package is unsupported")
        if artifact.behavior_mode not in _BEHAVIOR_MODES:
            raise ConfigurationError(f"artifact.{artifact.name}.behavior_mode is unsupported")
        if artifact.behavior_mode == "source-equivalent" and not artifact.behavior_reference:
            raise ConfigurationError(
                f"artifact.{artifact.name} source-equivalent behavior needs a reference"
            )
        if artifact.behavior_mode != "source-equivalent" and artifact.behavior_reference:
            raise ConfigurationError(
                f"artifact.{artifact.name} native behavior cannot have a reference"
            )

    linux_table = _table(data.get("linux"), "linux")
    soname = linux_table.get("soname_major")
    if soname != 2:
        raise ConfigurationError("linux.soname_major must be 2")
    profile_tables = _table(linux_table.get("profile"), "linux.profile")
    profiles = {
        name: LinuxProfile(
            name=name,
            runtime_packages=_texts(
                _table(value, f"linux.profile.{name}").get("runtime_packages"),
                f"linux.profile.{name}.runtime_packages",
            ),
            os_id=_nonempty(
                _table(value, f"linux.profile.{name}").get("os_id"),
                f"linux.profile.{name}.os_id",
            ),
            version_pattern=_nonempty(
                _table(value, f"linux.profile.{name}").get("version_pattern"),
                f"linux.profile.{name}.version_pattern",
            ),
        )
        for name, value in profile_tables.items()
    }
    for profile in profiles.values():
        try:
            re.compile(profile.version_pattern)
        except re.error as error:
            raise ConfigurationError(
                f"linux.profile.{profile.name}.version_pattern is invalid: {error}"
            ) from error
    linux = LinuxContract(
        soname_major=soname,
        loader_candidates=_texts(linux_table.get("loader_candidates"), "linux.loader_candidates"),
        build_packages=_texts(linux_table.get("build_packages"), "linux.build_packages"),
        profiles=profiles,
    )
    return RuntimeContract(
        schema_version=3,
        minimum_media_kit=minimum_media_kit,
        minimum_media_kit_video=minimum_media_kit_video,
        toolchain=toolchain,
        consumers=consumers,
        probe=probe,
        artifacts=artifacts,
        linux=linux,
    )


def _nonempty(value: Any, owner: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{owner} must be a non-empty string")
    return value


def _positive_int(value: Any, owner: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{owner} must be a positive integer")
    return value


def load_sources(path: Path) -> dict[str, SourceRule]:
    data = _load_toml(path)
    if data.get("schema_version") != 1:
        raise ConfigurationError("sources/upstreams.toml schema_version must be 1")
    tables = _table(data.get("source"), "source")
    sources = {
        name: SourceRule.from_table(name, _table(value, f"source.{name}"))
        for name, value in tables.items()
    }
    for source in sources.values():
        if not _REPOSITORY.fullmatch(source.repository):
            raise ConfigurationError(f"source.{source.name}.repository is invalid")
        if source.release != "latest":
            raise ConfigurationError(
                f"source.{source.name}.release must be latest; version pins belong in promotions"
            )
        for pattern in source.asset_patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ConfigurationError(
                    f"source.{source.name}.asset_patterns contains invalid regex: {error}"
                ) from error
    return sources


def load_repository(start: Path | None = None) -> RepositoryConfig:
    root = find_repository_root(start)
    contract = load_contract(root / "contracts" / "runtime.toml")
    try:
        bootstrap_python = (root / ".python-version").read_text(encoding="ascii").strip()
    except OSError as error:
        raise ConfigurationError(f"cannot read .python-version: {error}") from error
    if bootstrap_python != contract.toolchain.python:
        raise ConfigurationError(
            ".python-version must equal toolchain.python in contracts/runtime.toml"
        )
    sources = load_sources(root / "sources" / "upstreams.toml")
    referenced = {source for artifact in contract.artifacts.values() for source in artifact.sources}
    missing = referenced - set(sources)
    if missing:
        raise ConfigurationError(
            f"artifact contract refers to missing sources: {', '.join(sorted(missing))}"
        )
    unused = set(sources) - referenced
    if unused:
        raise ConfigurationError(f"unreferenced source rules: {', '.join(sorted(unused))}")
    return RepositoryConfig(root=root, contract=contract, sources=sources)
