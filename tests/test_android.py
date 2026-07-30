from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from libmpv_runtime.android import combine_aar
from libmpv_runtime.archive import deterministic_zip
from libmpv_runtime.errors import IntegrityError
from libmpv_runtime.files import sha256_file


def _jar(tmp_path: Path, abi: str, *, include_cxx_runtime: bool = True) -> Path:
    root = tmp_path / f"root-{abi}"
    libraries = root / "lib" / abi
    metadata = root / "META-INF" / "libmpv-runtime"
    libraries.mkdir(parents=True)
    metadata.mkdir(parents=True)
    (libraries / "libmpv.so").write_bytes(b"\x7fELF mpv")
    (libraries / "libmediakitandroidhelper.so").write_bytes(b"\x7fELF helper")
    if include_cxx_runtime:
        (libraries / "libc++_shared.so").write_bytes(b"\x7fELF c++ runtime")
    helper_class = (
        root / "com" / "alexmercerind" / "mediakitandroidhelper" / "MediaKitAndroidHelper.class"
    )
    helper_class.parent.mkdir(parents=True)
    helper_class.write_bytes(b"\xca\xfe\xba\xbe helper")
    (metadata / "build-manifest.json").write_text(
        json.dumps({"target": abi}),
        encoding="utf-8",
    )
    jar = tmp_path / f"{abi}.jar"
    deterministic_zip(root, jar, 1_700_000_000)
    return jar


def test_combined_aar_contains_every_media_kit_abi(tmp_path: Path) -> None:
    abis = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
    jars = [_jar(tmp_path, abi) for abi in abis]
    first = tmp_path / "first.aar"
    second = tmp_path / "second.aar"
    combine_aar(jars, first, 1_700_000_000)
    combine_aar(jars, second, 1_700_000_000)
    assert sha256_file(first) == sha256_file(second)
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        for abi in abis:
            assert f"jni/{abi}/libmpv.so" in names
            assert f"jni/{abi}/libmediakitandroidhelper.so" in names
            assert f"jni/{abi}/libc++_shared.so" in names
        assert "classes.jar" in names
        assert "AndroidManifest.xml" in names
        for abi in abis:
            assert f"assets/libmpv-runtime/{abi}/build-manifest.json" in names
        with archive.open("classes.jar") as classes_file:
            classes_archive = tmp_path / "classes.jar"
            classes_archive.write_bytes(classes_file.read())
        with zipfile.ZipFile(classes_archive) as classes:
            assert (
                "com/alexmercerind/mediakitandroidhelper/MediaKitAndroidHelper.class"
                in classes.namelist()
            )


def test_combined_aar_rejects_missing_cxx_runtime(tmp_path: Path) -> None:
    jars = [
        _jar(tmp_path, "arm64-v8a", include_cxx_runtime=False),
        _jar(tmp_path, "armeabi-v7a"),
        _jar(tmp_path, "x86_64"),
        _jar(tmp_path, "x86"),
    ]
    with pytest.raises(IntegrityError, match=r"missing libc\+\+_shared\.so"):
        combine_aar(jars, tmp_path / "invalid.aar", 1_700_000_000)
