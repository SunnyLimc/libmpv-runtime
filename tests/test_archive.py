from __future__ import annotations

import gzip
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

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


def test_apple_style_symlinks_are_preserved_with_posix_targets(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _fixture(source)
    link = source / "current"
    try:
        link.symlink_to("nested\\b.txt")
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    zipped = tmp_path / "framework.zip"
    deterministic_zip(source, zipped, 1_700_000_000)
    with zipfile.ZipFile(zipped) as archive:
        info = archive.getinfo("current")
        assert stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
        assert archive.read(info) == b"nested/b.txt"

    bundled = tmp_path / "framework.tar.gz"
    deterministic_tar_gz(source, bundled, 1_700_000_000)
    with tarfile.open(bundled, mode="r:gz") as archive:
        member = archive.getmember("current")
        assert member.issym()
        assert member.linkname == "nested/b.txt"
