from __future__ import annotations

from pathlib import Path

import pytest

from libmpv_runtime.licenses import collect_core_licenses
from libmpv_runtime.models import RepositoryConfig


def test_license_bundle_covers_every_locked_core_source(
    config: RepositoryConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    def fake_download(*, key: str, url: str, sha256: str, cache_dir: Path) -> Path:
        del url, sha256, cache_dir
        archive = downloads / f"{key}.tar"
        archive.write_bytes(b"fixture")
        return archive

    def fake_extract(archive: Path, destination: Path, *, strip_components: int) -> None:
        del strip_components
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "LICENSE").write_text(archive.stem, encoding="utf-8")

    monkeypatch.setattr("libmpv_runtime.licenses.download_url_verified", fake_download)
    monkeypatch.setattr("libmpv_runtime.licenses.extract_tar", fake_extract)

    destination = tmp_path / "licenses"
    collect_core_licenses(config, destination)

    expected = {f"{source.name}-LICENSE.txt" for source in config.lock.sources.values()}
    assert {path.name for path in destination.iterdir()} == expected
