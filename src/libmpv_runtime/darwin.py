from __future__ import annotations

import re
from pathlib import Path

from .errors import IntegrityError
from .models import RepositoryConfig

_SECTION = re.compile(
    r"^  (?P<name>[A-Za-z0-9_-]+) = \{\n(?P<body>.*?)^  \};$",
    flags=re.MULTILINE | re.DOTALL,
)
_FIELD = re.compile(r'^\s{4}(?P<name>[A-Za-z0-9_-]+) = "(?P<value>[^"]*)";$', re.MULTILINE)


def _read_package_lock(path: Path) -> dict[str, dict[str, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise IntegrityError(f"cannot read Darwin package lock {path}: {error}") from error
    packages: dict[str, dict[str, str]] = {}
    for match in _SECTION.finditer(content):
        packages[match.group("name")] = {
            field.group("name"): field.group("value")
            for field in _FIELD.finditer(match.group("body"))
        }
    if not packages:
        raise IntegrityError(f"Darwin package lock has no package entries: {path}")
    return packages


def verify_darwin_package_lock(config: RepositoryConfig, path: Path) -> None:
    packages = _read_package_lock(path)
    for source in config.lock.sources.values():
        package = packages.get(source.name)
        if package is None:
            raise IntegrityError(f"Darwin package lock is missing {source.name}")
        if package.get("version") != source.version:
            raise IntegrityError(f"Darwin {source.name} version differs from runtime.lock.toml")
        if source.name == "libplacebo":
            if package.get("rev") != source.revision:
                raise IntegrityError("Darwin libplacebo revision differs from runtime.lock.toml")
            continue
        archive_url = package.get("url")
        archive_hash = package.get("sha256")
        if (
            not isinstance(archive_url, str)
            or not archive_url.startswith("https://")
            or not isinstance(archive_hash, str)
            or len(archive_hash) != 64
        ):
            raise IntegrityError(f"Darwin {source.name} archive lock is incomplete")
