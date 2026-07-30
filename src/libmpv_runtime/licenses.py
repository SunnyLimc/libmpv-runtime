from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .download import download_url_verified, extract_tar
from .errors import IntegrityError
from .models import RepositoryConfig

_LICENSE_PREFIXES = ("copyright", "copying", "license")


def collect_archive_licenses(
    *,
    name: str,
    version: str,
    url: str,
    sha256: str,
    cache_dir: Path,
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    archive = download_url_verified(
        key=f"source-{name}-{version}",
        url=url,
        sha256=sha256,
        cache_dir=cache_dir,
    )
    with tempfile.TemporaryDirectory(prefix=f"license-{name}-") as temporary:
        extracted = Path(temporary)
        extract_tar(archive, extracted, strip_components=1)
        copied = 0
        for path in sorted(extracted.iterdir()):
            if path.is_file() and path.name.casefold().startswith(_LICENSE_PREFIXES):
                shutil.copy2(path, destination / f"{name}-{path.name}.txt")
                copied += 1
        if copied == 0:
            raise IntegrityError(f"no recognized license files in source.{name}")


def collect_core_licenses(config: RepositoryConfig, destination: Path) -> None:
    for source in sorted(config.lock.sources.values(), key=lambda value: value.name):
        if not source.sha256:
            raise IntegrityError(
                f"source.{source.name} needs an archive hash for license collection"
            )
        collect_archive_licenses(
            name=source.name,
            version=source.version,
            url=source.url,
            sha256=source.sha256,
            cache_dir=config.cache_dir / "sources",
            destination=destination,
        )
