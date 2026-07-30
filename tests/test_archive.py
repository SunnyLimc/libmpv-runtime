from __future__ import annotations

import gzip
import tarfile
import zipfile
from pathlib import Path

from libmpv_runtime.archive import deterministic_tar_gz, deterministic_zip
from libmpv_runtime.files import sha256_file


def _fixture(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "b.txt").write_text("bravo\n", encoding="utf-8")
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")


def test_zip_packaging_is_bit_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _fixture(source)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    deterministic_zip(source, first, 1_700_000_000)
    deterministic_zip(source, second, 1_700_000_000)
    assert sha256_file(first) == sha256_file(second)
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["a.txt", "nested/", "nested/b.txt"]


def test_tar_gz_packaging_is_bit_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _fixture(source)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    deterministic_tar_gz(source, first, 1_700_000_000)
    deterministic_tar_gz(source, second, 1_700_000_000)
    assert sha256_file(first) == sha256_file(second)
    with (
        first.open("rb") as file,
        gzip.GzipFile(fileobj=file) as compressed,
        tarfile.open(fileobj=compressed) as archive,
    ):
        assert archive.getnames() == ["a.txt", "nested", "nested/b.txt"]
