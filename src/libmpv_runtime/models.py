from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


def _required_text(table: dict[str, Any], key: str, owner: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{owner}.{key} must be a non-empty string")
    return value


def _optional_hash(table: dict[str, Any], key: str, owner: str) -> str:
    value = table.get(key, "")
    if not isinstance(value, str):
        raise ConfigurationError(f"{owner}.{key} must be a string")
    if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
        raise ConfigurationError(f"{owner}.{key} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class SourceLock:
    name: str
    version: str
    url: str
    revision: str
    sha256: str
    license: str

    @classmethod
    def from_table(cls, name: str, table: dict[str, Any]) -> SourceLock:
        owner = f"source.{name}"
        return cls(
            name=name,
            version=_required_text(table, "version", owner),
            url=_required_text(table, "url", owner),
            revision=_required_text(table, "revision", owner),
            sha256=_optional_hash(table, "sha256", owner),
            license=_required_text(table, "license", owner),
        )


@dataclass(frozen=True, slots=True)
class BuilderLock:
    key: str
    name: str
    url: str
    revision: str
    sha256: str
    strip_components: int

    @classmethod
    def from_table(cls, key: str, table: dict[str, Any]) -> BuilderLock:
        owner = f"builder.{key}"
        strip_components = table.get("strip_components")
        if not isinstance(strip_components, int) or strip_components < 0:
            raise ConfigurationError(f"{owner}.strip_components must be a non-negative integer")
        return cls(
            key=key,
            name=_required_text(table, "name", owner),
            url=_required_text(table, "url", owner),
            revision=_required_text(table, "revision", owner),
            sha256=_optional_hash(table, "sha256", owner),
            strip_components=strip_components,
        )


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    path: Path
    schema_version: int
    runtime_version: str
    flavor: str
    aggregate_license: str
    source_date_epoch: int
    required_audio_filters: tuple[str, ...]
    toolchains: dict[str, str | int]
    sources: dict[str, SourceLock]
    builders: dict[str, BuilderLock]


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    platform: str
    architecture: str
    builder: str
    runner: str
    package: str
    load_name: str

    @classmethod
    def from_table(cls, name: str, table: dict[str, Any]) -> Target:
        owner = f"target.{name}"
        return cls(
            name=name,
            platform=_required_text(table, "platform", owner),
            architecture=_required_text(table, "architecture", owner),
            builder=_required_text(table, "builder", owner),
            runner=_required_text(table, "runner", owner),
            package=_required_text(table, "package", owner),
            load_name=_required_text(table, "load_name", owner),
        )


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    root: Path
    lock: RuntimeLock
    targets: dict[str, Target]

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    @property
    def work_dir(self) -> Path:
        return self.root / "work"

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def dist_dir(self) -> Path:
        return self.root / "dist"

    def target(self, name: str) -> Target:
        try:
            return self.targets[name]
        except KeyError as error:
            choices = ", ".join(sorted(self.targets))
            raise ConfigurationError(
                f"unknown target {name!r}; choose one of: {choices}"
            ) from error
