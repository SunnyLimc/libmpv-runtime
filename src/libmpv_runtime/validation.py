from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .errors import IntegrityError, VerificationError
from .evidence import load_linux_evidence, load_releasable_evidence
from .files import read_json, sha256_file, write_json
from .models import RepositoryConfig
from .plan import load_plan, verify_plan
from .schema import validate_document


def _one(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise IntegrityError(f"expected exactly one {name} below {root}, found {len(matches)}")
    return matches[0]


def _artifacts(root: Path, target: str) -> list[Path]:
    bundle_names = {
        "windows-x86_64": "libmpv-runtime-windows-x86_64.zip",
        "android": "libmpv-runtime-android.zip",
        "macos": "libmpv-runtime-macos.tar.gz",
        "ios": "libmpv-runtime-ios.tar.gz",
    }
    paths = [_one(root, bundle_names[target])]
    if target in {"macos", "ios"}:
        prefix = f"libmpv-runtime-{target}-"
        paths.extend(
            sorted(
                path
                for path in root.rglob(f"{prefix}*.zip")
                if path.is_file() and not path.name.endswith(".sha256")
            )
        )
    return paths


def seal_validation_run(
    config: RepositoryConfig, plan_path: Path, input_root: Path, output: Path
) -> Path:
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    if output.exists():
        raise IntegrityError(f"validation output already exists: {output}")
    output.mkdir(parents=True)
    copied: list[dict[str, Any]] = []

    plan_destination = output / "validation-plan.json"
    shutil.copy2(plan_path, plan_destination)
    for target in sorted(config.contract.artifacts):
        evidence_path = _one(input_root, f"{target}.json")
        evidence = load_releasable_evidence(evidence_path, target)
        if evidence.get("planSha256") != sha256_file(plan_path):
            raise VerificationError(f"{target} evidence belongs to another plan")
        for source in [*_artifacts(input_root, target), evidence_path]:
            destination = output / source.name
            if destination.exists():
                raise IntegrityError(f"duplicate validation output name: {source.name}")
            shutil.copy2(source, destination)

    for profile in sorted(config.contract.linux.profiles):
        source = _one(input_root, f"linux-system-{profile}.json")
        evidence = load_linux_evidence(source, profile)
        if evidence.get("planSha256") != sha256_file(plan_path):
            raise VerificationError(f"Linux evidence belongs to another plan: {profile}")
        shutil.copy2(source, output / source.name)

    for path in sorted(output.iterdir()):
        if path.is_file():
            copied.append(
                {"name": path.name, "sha256": sha256_file(path), "size": path.stat().st_size}
            )
    index = output / "validation-index.json"
    value = {
        "schemaVersion": 1,
        "repositoryRevision": plan.repository_revision,
        "planSha256": sha256_file(plan_destination),
        "files": copied,
    }
    validate_document(config.root, "validation-index", value)
    write_json(index, value)
    return index


def verify_validation_run(config: RepositoryConfig, root: Path) -> dict[str, Any]:
    index_path = root / "validation-index.json"
    value = read_json(index_path)
    validate_document(config.root, "validation-index", value)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise IntegrityError(f"invalid validation index: {index_path}")
    plan_path = root / "validation-plan.json"
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    if value.get("repositoryRevision") != plan.repository_revision:
        raise VerificationError("validation index revision does not match plan")
    if value.get("planSha256") != sha256_file(plan_path):
        raise VerificationError("validation index plan digest is invalid")
    files = value.get("files")
    if not isinstance(files, list):
        raise IntegrityError("validation index has no files")
    seen_names: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise IntegrityError("validation index contains an invalid file")
        name = item.get("name")
        digest = item.get("sha256")
        size = item.get("size")
        if not isinstance(name, str) or Path(name).name != name or name in seen_names:
            raise IntegrityError(f"validation index file name is invalid: {name}")
        path = root / str(name)
        if not path.is_file() or path.stat().st_size != size or sha256_file(path) != digest:
            raise VerificationError(f"validation index file changed: {name}")
        seen_names.add(name)
    actual_names = {
        path.name for path in root.iterdir() if path.is_file() and path.name != index_path.name
    }
    indexed_names = {str(item.get("name")) for item in files if isinstance(item, dict)}
    if actual_names != indexed_names:
        raise VerificationError("validation index file set is incomplete")
    for target in config.contract.artifacts:
        load_releasable_evidence(root / f"{target}.json", target)
        _artifacts(root, target)
    for profile in config.contract.linux.profiles:
        load_linux_evidence(root / f"linux-system-{profile}.json", profile)
    return value
