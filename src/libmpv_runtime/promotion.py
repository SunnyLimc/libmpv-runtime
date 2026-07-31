from __future__ import annotations

import json
import re
import shutil
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import IntegrityError, VerificationError
from .evidence import load_releasable_evidence
from .files import read_json, sha256_file, write_json
from .models import RepositoryConfig

_PROMOTION = re.compile(r"^runtime-[0-9]{8}\.[1-9][0-9]*$")
_REPOSITORY_URL = "https://github.com/SunnyLimc/libmpv-runtime"


def _role(target: str, path: Path) -> str:
    if path.name in {
        f"libmpv-runtime-{target}.zip",
        f"libmpv-runtime-{target}.tar.gz",
    }:
        return "bundle"
    prefix = f"libmpv-runtime-{target}-"
    if path.name.startswith(prefix) and path.suffix == ".zip":
        return f"spm:{path.name.removeprefix(prefix).removesuffix('.zip')}"
    raise IntegrityError(f"cannot infer artifact role for {target}: {path.name}")


def _bundle_provenance(target: str, path: Path) -> dict[str, Any]:
    name = "libmpv-runtime.json"
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                matches = [item for item in archive.namelist() if item == name]
                if len(matches) != 1:
                    raise IntegrityError(f"{target} bundle has no root {name}")
                value = json.loads(archive.read(matches[0]))
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, mode="r:gz") as archive:
                member = archive.getmember(name)
                stream = archive.extractfile(member)
                if stream is None:
                    raise IntegrityError(f"{target} bundle has no readable root {name}")
                value = json.loads(stream.read())
        else:
            raise IntegrityError(f"unsupported bundle format for {target}: {path.name}")
    except (json.JSONDecodeError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise IntegrityError(f"invalid {target} bundle provenance: {path}") from error
    if not isinstance(value, dict) or value.get("artifact") != target:
        raise IntegrityError(f"{target} bundle provenance does not identify its artifact")
    return value


def assemble(
    config: RepositoryConfig,
    promotion_id: str,
    artifacts: dict[str, list[Path]],
    evidence_paths: dict[str, Path],
    linux_report_paths: list[Path],
    output: Path,
) -> Path:
    if not _PROMOTION.fullmatch(promotion_id):
        raise IntegrityError("promotion id must match runtime-YYYYMMDD.N")
    expected_targets = set(config.contract.artifacts)
    if set(artifacts) != expected_targets:
        raise IntegrityError(
            f"promotion artifact set mismatch: expected {sorted(expected_targets)}, "
            f"got {sorted(artifacts)}"
        )
    if set(evidence_paths) != expected_targets:
        raise IntegrityError(
            f"promotion evidence set mismatch: expected {sorted(expected_targets)}, "
            f"got {sorted(evidence_paths)}"
        )
    if output.exists():
        raise IntegrityError(f"promotion output already exists: {output}")
    if not linux_report_paths:
        raise IntegrityError("promotion requires at least one Linux system validation report")
    output.mkdir(parents=True)

    evidence: dict[str, dict[str, Any]] = {}
    for target, path in evidence_paths.items():
        evidence[target] = load_releasable_evidence(
            path, target, config.contract.required_audio_filters
        )
    for target, value in evidence.items():
        behavior = value.get("behavior")
        if not isinstance(behavior, dict) or behavior.get("mode") != "source-equivalent":
            continue
        reference = behavior.get("referenceTarget")
        referenced = evidence.get(str(reference))
        referenced_behavior = referenced.get("behavior") if isinstance(referenced, dict) else None
        if not isinstance(referenced_behavior, dict) or referenced_behavior.get("mode") != "native":
            raise VerificationError(
                f"{target} references behavior evidence that is not native: {reference}"
            )

    for target, paths in artifacts.items():
        bundles = [path for path in paths if _role(target, path) == "bundle"]
        if len(bundles) != 1:
            raise IntegrityError(f"{target} must have exactly one bundle artifact")
        if _bundle_provenance(target, bundles[0]) != evidence[target].get("provenance"):
            raise VerificationError(f"{target} bundle and validation provenance do not match")

    artifact_records: dict[str, list[dict[str, Any]]] = {}
    used_names: set[str] = set()
    for target, paths in sorted(artifacts.items()):
        records: list[dict[str, Any]] = []
        roles: set[str] = set()
        for source in sorted(paths, key=lambda item: item.name):
            if not source.is_file() or source.name in used_names:
                raise IntegrityError(f"missing or duplicate promotion artifact: {source}")
            used_names.add(source.name)
            role = _role(target, source)
            if role in roles:
                raise IntegrityError(f"duplicate artifact role for {target}: {role}")
            roles.add(role)
            destination = output / source.name
            shutil.copy2(source, destination)
            records.append(
                {
                    "role": role,
                    "name": source.name,
                    "url": f"{_REPOSITORY_URL}/releases/download/{promotion_id}/{source.name}",
                    "sha256": sha256_file(destination),
                    "size": destination.stat().st_size,
                }
            )
        if "bundle" not in roles:
            raise IntegrityError(f"{target} has no bundle artifact")
        if target in {"macos", "ios"} and not {"spm:Mpv", "spm:Avfilter"}.issubset(roles):
            raise IntegrityError(f"{target} is missing required SwiftPM components")
        artifact_records[target] = records

    linux_reports: list[dict[str, Any]] = []
    seen_profiles: set[str] = set()
    for source in linux_report_paths:
        value = read_json(source)
        if not isinstance(value, dict):
            raise IntegrityError(f"invalid Linux validation report: {source}")
        profile = value.get("profile")
        if not isinstance(profile, str) or profile not in config.contract.linux.profiles:
            raise IntegrityError(f"Linux report has an unsupported profile: {source}")
        if profile in seen_profiles:
            raise IntegrityError(f"duplicate Linux validation profile: {profile}")
        seen_profiles.add(profile)
        library = value.get("library")
        client_api = value.get("clientApi")
        packages = value.get("runtimePackages")
        expected_packages = list(config.contract.linux.profiles[profile].runtime_packages)
        if (
            not isinstance(library, str)
            or f".so.{config.contract.linux.soname_major}" not in library
            or not isinstance(client_api, str)
            or packages != expected_packages
        ):
            raise VerificationError(f"Linux report does not satisfy the contract: {source}")
        name = f"linux-system-{profile}.json"
        destination = output / name
        shutil.copy2(source, destination)
        linux_reports.append(
            {
                "profile": profile,
                "name": name,
                "url": f"{_REPOSITORY_URL}/releases/download/{promotion_id}/{name}",
                "sha256": sha256_file(destination),
                "library": library,
                "clientApi": client_api,
                "runtimePackages": packages,
            }
        )

    manifest = output / "promotion.json"
    write_json(
        manifest,
        {
            "schemaVersion": 1,
            "id": promotion_id,
            "createdAt": datetime.now(UTC).isoformat(),
            "repository": _REPOSITORY_URL,
            "contract": {
                "path": "contracts/runtime.toml",
                "sha256": sha256_file(config.root / "contracts" / "runtime.toml"),
            },
            "artifacts": artifact_records,
            "linux": {
                "artifact": None,
                "sonameMajor": config.contract.linux.soname_major,
                "validationReports": sorted(
                    linux_reports, key=lambda report: str(report["profile"])
                ),
                "profiles": {
                    name: list(profile.runtime_packages)
                    for name, profile in sorted(config.contract.linux.profiles.items())
                },
            },
            "evidence": evidence,
        },
    )
    sums = [path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(sums)),
        encoding="ascii",
        newline="\n",
    )
    return manifest


def load_promotion(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise IntegrityError(f"invalid promotion manifest: {path}")
    promotion_id = value.get("id")
    if not isinstance(promotion_id, str) or not _PROMOTION.fullmatch(promotion_id):
        raise IntegrityError(f"invalid promotion id: {path}")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict):
        raise IntegrityError(f"promotion artifacts are missing: {path}")
    return value
