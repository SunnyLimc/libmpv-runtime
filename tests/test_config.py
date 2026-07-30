from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from libmpv_runtime.config import load_repository, load_runtime_lock
from libmpv_runtime.errors import ConfigurationError
from libmpv_runtime.models import RepositoryConfig
from libmpv_runtime.prepare import _apply_patch_series, _builder_state


def test_repository_declares_every_native_platform(repository_root: Path) -> None:
    config = load_repository(repository_root)
    assert {target.platform for target in config.targets.values()} == {
        "android",
        "windows",
        "linux",
        "macos",
        "ios",
    }


def test_required_filters_are_unique_and_complete(repository_root: Path) -> None:
    filters = load_repository(repository_root).lock.required_audio_filters
    assert filters == (
        "loudnorm",
        "dynaudnorm",
        "acompressor",
        "alimiter",
        "volume",
        "aresample",
        "ebur128",
        "astats",
    )
    assert len(filters) == len(set(filters))


def test_all_builder_archives_use_full_revisions_and_sha256(repository_root: Path) -> None:
    for builder in load_repository(repository_root).lock.builders.values():
        assert len(builder.revision) == 40
        assert len(builder.sha256) == 64
        int(builder.revision, 16)
        int(builder.sha256, 16)


def test_all_core_sources_use_full_revisions_and_archive_hashes(
    repository_root: Path,
) -> None:
    for source in load_repository(repository_root).lock.sources.values():
        assert len(source.revision) == 40
        assert len(source.sha256) == 64
        int(source.revision, 16)
        int(source.sha256, 16)
        assert not source.url.endswith(".git")


def test_invalid_aggregate_license_is_rejected(tmp_path: Path, repository_root: Path) -> None:
    value = (repository_root / "runtime.lock.toml").read_text(encoding="utf-8")
    path = tmp_path / "runtime.lock.toml"
    path.write_text(
        value.replace(
            'aggregate_license = "LGPL-3.0-or-later"',
            'aggregate_license = "GPL-3.0-or-later"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match=r"LGPL-3\.0-or-later"):
        load_runtime_lock(path)


def test_unknown_target_has_actionable_error(config: object) -> None:
    with pytest.raises(ConfigurationError, match="choose one of"):
        config.target("plan9-mips")


def test_builder_state_changes_when_patch_series_changes(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    builder = config.lock.builders["windows"]
    original = _builder_state(config, builder)
    patch_root = tmp_path / "patches" / builder.key
    patch_root.mkdir(parents=True)
    (patch_root / "0001-example.patch").write_text("first", encoding="utf-8")
    temporary_config = replace(config, root=tmp_path)
    first = _builder_state(temporary_config, builder)
    (patch_root / "0001-example.patch").write_text("second", encoding="utf-8")
    second = _builder_state(temporary_config, builder)
    assert original["patchesSha256"] != first["patchesSha256"]
    assert first["patchesSha256"] != second["patchesSha256"]


def test_patch_series_modifies_nested_ignored_builder(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    builder = config.lock.builders["windows"]
    temporary_config = replace(config, root=tmp_path)
    directory = tmp_path / "work" / "windows-x86_64" / "builder"
    source = directory / "packages" / "example.cmake"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"GIT_TAG main\n")
    patch_root = tmp_path / "patches" / builder.key
    patch_root.mkdir(parents=True)
    (patch_root / "0001-pin.patch").write_bytes(
        b"""diff --git a/packages/example.cmake b/packages/example.cmake
--- a/packages/example.cmake
+++ b/packages/example.cmake
@@ -1 +1 @@
-GIT_TAG main
+GIT_TAG 0123456789012345678901234567890123456789
""",
    )

    _apply_patch_series(temporary_config, builder, directory)

    assert source.read_text(encoding="utf-8") == (
        "GIT_TAG 0123456789012345678901234567890123456789\n"
    )
