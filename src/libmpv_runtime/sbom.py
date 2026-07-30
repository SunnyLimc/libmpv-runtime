from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .files import sha256_file
from .models import RepositoryConfig, Target


def _spdx_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ".-" else "-" for char in value)
    return f"SPDXRef-{safe}"


def create_spdx(config: RepositoryConfig, target: Target, stage: Path) -> dict[str, Any]:
    namespace_seed = (
        f"{config.lock.runtime_version}:{target.name}:{config.lock.source_date_epoch}".encode()
    )
    namespace_hash = hashlib.sha256(namespace_seed).hexdigest()
    root_id = _spdx_id(f"libmpv-runtime-{target.name}")
    packages: list[dict[str, Any]] = [
        {
            "name": f"libmpv-runtime-{target.name}",
            "SPDXID": root_id,
            "versionInfo": config.lock.runtime_version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "licenseConcluded": config.lock.aggregate_license,
            "licenseDeclared": config.lock.aggregate_license,
            "copyrightText": "NOASSERTION",
        }
    ]
    relationships: list[dict[str, str]] = []
    for source in sorted(config.lock.sources.values(), key=lambda value: value.name):
        source_id = _spdx_id(f"source-{source.name}")
        packages.append(
            {
                "name": source.name,
                "SPDXID": source_id,
                "versionInfo": source.version,
                "downloadLocation": source.url,
                "filesAnalyzed": False,
                "licenseConcluded": source.license,
                "licenseDeclared": source.license,
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:generic/{source.name}@{source.version}",
                    }
                ],
            }
        )
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": source_id,
            }
        )

    files: list[dict[str, Any]] = []
    for index, path in enumerate(sorted(stage.rglob("*")), start=1):
        if not path.is_file() or path.is_symlink() or path.name == "sbom.spdx.json":
            continue
        file_id = f"SPDXRef-File-{index}"
        files.append(
            {
                "fileName": f"./{path.relative_to(stage).as_posix()}",
                "SPDXID": file_id,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": sha256_file(path),
                    }
                ],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": file_id,
            }
        )

    created = datetime.fromtimestamp(config.lock.source_date_epoch, tz=UTC)
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"libmpv-runtime-{config.lock.runtime_version}-{target.name}",
        "documentNamespace": (
            "https://github.com/SunnyLimc/libmpv-runtime/spdx/"
            f"{config.lock.runtime_version}/{target.name}/{namespace_hash}"
        ),
        "creationInfo": {
            "created": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: libmpv-runtime-0.1.0a1"],
        },
        "documentDescribes": [root_id],
        "packages": packages,
        "files": files,
        "relationships": relationships,
    }
