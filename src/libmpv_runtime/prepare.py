from __future__ import annotations

import hashlib
from pathlib import Path

from .download import download_verified, extract_tar
from .files import read_json, remove_tree, write_json
from .models import BuilderLock, RepositoryConfig, Target
from .process import run


def _patch_series_digest(config: RepositoryConfig, builder: BuilderLock) -> str:
    digest = hashlib.sha256()
    patch_dir = config.root / "patches" / builder.key
    if patch_dir.exists():
        for patch in sorted(patch_dir.glob("*.patch")):
            digest.update(patch.relative_to(config.root).as_posix().encode())
            digest.update(b"\0")
            digest.update(patch.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _builder_state(config: RepositoryConfig, builder: BuilderLock) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "builder": builder.key,
        "name": builder.name,
        "revision": builder.revision,
        "sha256": builder.sha256,
        "patchesSha256": _patch_series_digest(config, builder),
    }


def _apply_patch_series(config: RepositoryConfig, builder: BuilderLock, directory: Path) -> None:
    patch_dir = config.root / "patches" / builder.key
    if not patch_dir.exists():
        return
    relative_directory = directory.relative_to(config.root).as_posix()
    for patch in sorted(patch_dir.glob("*.patch")):
        options = ["--unidiff-zero", "--whitespace=error-all"]
        run(
            [
                "git",
                "apply",
                "--check",
                *options,
                f"--directory={relative_directory}",
                str(patch),
            ],
            cwd=config.root,
        )
        run(
            ["git", "apply", *options, f"--directory={relative_directory}", str(patch)],
            cwd=config.root,
        )
        run(
            [
                "git",
                "apply",
                "--check",
                "--reverse",
                *options,
                f"--directory={relative_directory}",
                str(patch),
            ],
            cwd=config.root,
        )


def prepare_builder(
    config: RepositoryConfig,
    builder: BuilderLock,
    directory: Path,
    *,
    clean: bool = False,
) -> Path:
    state_path = directory / ".libmpv-runtime-builder.json"
    expected = _builder_state(config, builder)
    if not clean and state_path.is_file() and read_json(state_path) == expected:
        return directory
    if directory.exists():
        remove_tree(directory, root=config.work_dir)
    archive = download_verified(builder, config.cache_dir / "downloads")
    extract_tar(archive, directory, strip_components=builder.strip_components)
    _apply_patch_series(config, builder, directory)
    write_json(state_path, expected)
    return directory


def prepare_target(
    config: RepositoryConfig,
    target: Target,
    *,
    clean: bool = False,
) -> Path:
    directory = config.work_dir / target.name / "builder"
    builder = config.lock.builders[target.builder]
    prepare_builder(config, builder, directory, clean=clean)
    if target.platform == "android":
        helper = config.lock.builders["android_helper"]
        prepare_builder(
            config,
            helper,
            config.work_dir / target.name / "android-helper",
            clean=clean,
        )
    return directory
