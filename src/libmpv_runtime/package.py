from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .archive import checksum_sidecar, deterministic_tar_gz, deterministic_zip
from .evidence import load_evidence
from .files import copy_tree_files, write_json
from .licenses import collect_core_licenses
from .manifest import build_manifest, source_lock_document
from .models import RepositoryConfig, Target
from .sbom import create_spdx
from .verify import verify_target


def artifact_name(config: RepositoryConfig, target: Target) -> str:
    stem = f"libmpv-runtime_v{config.lock.runtime_version}_{target.name}"
    extension = {
        "jar": ".jar",
        "zip": ".zip",
        "tar.gz": ".tar.gz",
        "xcframework": ".zip",
    }[target.package]
    return stem + extension


def _metadata_root(root: Path, target: Target) -> Path:
    if target.platform == "android":
        return root / "META-INF" / "libmpv-runtime"
    return root / "share" / "libmpv-runtime"


def _decorate(config: RepositoryConfig, target: Target, source: Path, destination: Path) -> None:
    copy_tree_files(source, destination)
    metadata = _metadata_root(destination, target)
    licenses = metadata / "LICENSES"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.root / "LICENSE", licenses / "libmpv-runtime-MIT.txt")
    shutil.copy2(config.root / "NOTICE", metadata / "NOTICE.txt")
    collect_core_licenses(config, licenses)

    staged_licenses = destination / "LICENSES"
    if staged_licenses.is_dir():
        copy_tree_files(staged_licenses, licenses)

    evidence_path = config.build_dir / "evidence" / f"{target.name}.json"
    evidence = load_evidence(evidence_path, target.name, config.lock.required_audio_filters)
    write_json(metadata / "source-lock.json", source_lock_document(config, target))
    write_json(metadata / "sbom.spdx.json", create_spdx(config, target, destination))
    excluded = {
        (metadata / "build-manifest.json").relative_to(destination),
    }
    write_json(
        metadata / "build-manifest.json",
        build_manifest(config, target, destination, evidence, excluded=excluded),
    )


def package_target(
    config: RepositoryConfig,
    target: Target,
    *,
    stage: Path | None = None,
    output: Path | None = None,
) -> Path:
    stage = verify_target(config, target, stage)
    output = output or config.dist_dir / artifact_name(config, target)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    package_work = config.build_dir / "package-work"
    package_work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{target.name}-", dir=package_work) as temporary:
        decorated = Path(temporary) / "root"
        decorated.mkdir()
        _decorate(config, target, stage, decorated)
        if target.package == "tar.gz":
            deterministic_tar_gz(decorated, output, config.lock.source_date_epoch)
        else:
            deterministic_zip(decorated, output, config.lock.source_date_epoch)
    checksum_sidecar(output)
    return output
