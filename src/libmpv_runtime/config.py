from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .models import (
    ArtifactContract,
    LinuxContract,
    LinuxProfile,
    RepositoryConfig,
    RuntimeContract,
    SourceRule,
)

_SUPPORTED_PLATFORMS = frozenset({"android", "windows", "macos", "ios"})
_SUPPORTED_PACKAGES = frozenset({"zip", "xcframeworks"})
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
    if data.get("schema_version") != 2:
        raise ConfigurationError("contracts/runtime.toml schema_version must be 2")
    minimum_media_kit = data.get("minimum_media_kit")
    minimum_media_kit_video = data.get("minimum_media_kit_video")
    if not isinstance(minimum_media_kit, str) or not minimum_media_kit:
        raise ConfigurationError("minimum_media_kit must be a non-empty string")
    if not isinstance(minimum_media_kit_video, str) or not minimum_media_kit_video:
        raise ConfigurationError("minimum_media_kit_video must be a non-empty string")
    filters = _texts(data.get("required_audio_filters"), "required_audio_filters")
    if len(filters) != len(set(filters)):
        raise ConfigurationError("required_audio_filters contains duplicates")

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
        )
        for name, value in profile_tables.items()
    }
    linux = LinuxContract(
        soname_major=soname,
        loader_candidates=_texts(linux_table.get("loader_candidates"), "linux.loader_candidates"),
        build_packages=_texts(linux_table.get("build_packages"), "linux.build_packages"),
        profiles=profiles,
    )
    return RuntimeContract(
        schema_version=2,
        minimum_media_kit=minimum_media_kit,
        minimum_media_kit_video=minimum_media_kit_video,
        required_audio_filters=filters,
        artifacts=artifacts,
        linux=linux,
    )


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
