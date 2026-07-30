from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ConfigurationError
from .models import BuilderLock, RepositoryConfig, RuntimeLock, SourceLock, Target

_TARGET_NAME = re.compile(r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
_FULL_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_PLATFORMS = frozenset({"android", "windows", "linux", "macos", "ios"})
_SUPPORTED_PACKAGES = frozenset({"jar", "zip", "tar.gz", "xcframework"})


def find_repository_root(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / "runtime.lock.toml").is_file() and (directory / "targets.toml").is_file():
            return directory
    raise ConfigurationError("could not find runtime.lock.toml and targets.toml")


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


def _https_url(url: str, owner: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigurationError(f"{owner}.url must be an absolute HTTPS URL")


def load_runtime_lock(path: Path) -> RuntimeLock:
    data = _load_toml(path)
    if data.get("schema_version") != 1:
        raise ConfigurationError("runtime.lock.toml schema_version must be 1")

    version = data.get("runtime_version")
    flavor = data.get("flavor")
    aggregate_license = data.get("aggregate_license")
    epoch = data.get("source_date_epoch")
    filters = data.get("required_audio_filters")
    if not isinstance(version, str) or not version:
        raise ConfigurationError("runtime_version must be a non-empty string")
    if not isinstance(flavor, str) or not flavor:
        raise ConfigurationError("flavor must be a non-empty string")
    if aggregate_license != "LGPL-3.0-or-later":
        raise ConfigurationError("the release flavor must remain LGPL-3.0-or-later")
    if not isinstance(epoch, int) or epoch < 315532800:
        raise ConfigurationError("source_date_epoch must be an integer on or after 1980-01-01")
    if (
        not isinstance(filters, list)
        or not filters
        or not all(isinstance(item, str) and item for item in filters)
    ):
        raise ConfigurationError("required_audio_filters must be a non-empty string array")
    if len(filters) != len(set(filters)):
        raise ConfigurationError("required_audio_filters contains duplicates")

    source_tables = _table(data.get("source"), "source")
    builder_tables = _table(data.get("builder"), "builder")
    toolchains = _table(data.get("toolchain"), "toolchain")
    if not all(
        isinstance(value, (str, int)) and not isinstance(value, bool)
        for value in toolchains.values()
    ):
        raise ConfigurationError("toolchain values must be strings or integers")
    for required in (
        "python",
        "android_ndk",
        "android_api",
        "windows_container",
        "meson",
        "linux_image",
        "linux_arm_image",
        "apple_image",
        "xcode_path",
    ):
        if required not in toolchains:
            raise ConfigurationError(f"toolchain.{required} is required")
    sources = {
        name: SourceLock.from_table(name, _table(table, f"source.{name}"))
        for name, table in source_tables.items()
    }
    builders = {
        name: BuilderLock.from_table(name, _table(table, f"builder.{name}"))
        for name, table in builder_tables.items()
    }
    for source in sources.values():
        _https_url(source.url, f"source.{source.name}")
        if not source.sha256 and not source.url.endswith(".git"):
            raise ConfigurationError(f"source.{source.name} archive is missing sha256")
    for builder in builders.values():
        _https_url(builder.url, f"builder.{builder.key}")
        if not _FULL_REVISION.fullmatch(builder.revision):
            raise ConfigurationError(f"builder.{builder.key}.revision must be a full commit hash")
        if not builder.sha256:
            raise ConfigurationError(f"builder.{builder.key}.sha256 is required")

    for required in ("mpv", "ffmpeg", "libplacebo"):
        if required not in sources:
            raise ConfigurationError(f"source.{required} is required")
    for required in ("android", "android_helper", "windows", "linux", "darwin"):
        if required not in builders:
            raise ConfigurationError(f"builder.{required} is required")

    return RuntimeLock(
        path=path,
        schema_version=1,
        runtime_version=version,
        flavor=flavor,
        aggregate_license=aggregate_license,
        source_date_epoch=epoch,
        required_audio_filters=tuple(filters),
        toolchains=dict(toolchains),
        sources=sources,
        builders=builders,
    )


def load_targets(path: Path, lock: RuntimeLock) -> dict[str, Target]:
    data = _load_toml(path)
    if data.get("schema_version") != 1:
        raise ConfigurationError("targets.toml schema_version must be 1")
    tables = _table(data.get("target"), "target")
    targets = {
        name: Target.from_table(name, _table(table, f"target.{name}"))
        for name, table in tables.items()
    }
    if not targets:
        raise ConfigurationError("targets.toml must declare at least one target")
    for target in targets.values():
        if not _TARGET_NAME.fullmatch(target.name):
            raise ConfigurationError(f"invalid target name: {target.name}")
        if target.platform not in _SUPPORTED_PLATFORMS:
            raise ConfigurationError(f"target.{target.name}.platform is unsupported")
        if target.package not in _SUPPORTED_PACKAGES:
            raise ConfigurationError(f"target.{target.name}.package is unsupported")
        if target.builder not in lock.builders:
            raise ConfigurationError(
                f"target.{target.name}.builder refers to missing builder.{target.builder}"
            )
        if not target.name.startswith(f"{target.platform}-"):
            raise ConfigurationError(f"target.{target.name} must start with {target.platform}-")
    covered = {target.platform for target in targets.values()}
    missing = _SUPPORTED_PLATFORMS - covered
    if missing:
        raise ConfigurationError(f"targets.toml is missing platforms: {', '.join(sorted(missing))}")
    return targets


def load_repository(start: Path | None = None) -> RepositoryConfig:
    root = find_repository_root(start)
    lock = load_runtime_lock(root / "runtime.lock.toml")
    targets = load_targets(root / "targets.toml", lock)
    version_file = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version_file != lock.runtime_version:
        raise ConfigurationError(
            f"VERSION ({version_file}) and runtime.lock.toml ({lock.runtime_version}) differ"
        )
    return RepositoryConfig(root=root, lock=lock, targets=targets)
