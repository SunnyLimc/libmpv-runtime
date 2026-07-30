from __future__ import annotations

from pathlib import Path

import pytest

from libmpv_runtime.darwin import verify_darwin_package_lock
from libmpv_runtime.errors import IntegrityError
from libmpv_runtime.models import RepositoryConfig


def _package_lock(config: RepositoryConfig) -> str:
    entries: list[str] = []
    for source in config.lock.sources.values():
        fields = [
            f'    version = "{source.version}";',
            f'    url = "{source.url}";',
        ]
        if source.name == "libplacebo":
            fields.append(f'    rev = "{source.revision}";')
        else:
            fields.append(f'    sha256 = "{source.sha256}";')
        entries.append(f"  {source.name} = {{\n" + "\n".join(fields) + "\n  };")
    return "{\n" + "\n".join(entries) + "\n}\n"


def test_darwin_package_lock_matches_runtime_sources(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    path = tmp_path / "packages.lock.nix"
    path.write_text(_package_lock(config), encoding="utf-8")
    verify_darwin_package_lock(config, path)


def test_darwin_package_lock_rejects_source_drift(config: RepositoryConfig, tmp_path: Path) -> None:
    path = tmp_path / "packages.lock.nix"
    path.write_text(
        _package_lock(config).replace(
            f'version = "{config.lock.sources["ffmpeg"].version}"',
            'version = "drifted"',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(IntegrityError, match="ffmpeg version differs"):
        verify_darwin_package_lock(config, path)
