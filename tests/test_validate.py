from __future__ import annotations

import plistlib
import struct
from pathlib import Path

import pytest

from libmpv_runtime.errors import VerificationError
from libmpv_runtime.files import write_json
from libmpv_runtime.models import RepositoryConfig
from libmpv_runtime.validate import validate_structure


def _elf(path: Path, *, bits: int, machine: int, alignment: int, text: bytes = b"") -> None:
    if bits == 64:
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", header, 18, machine)
        struct.pack_into("<Q", header, 32, 64)
        struct.pack_into("<H", header, 54, 56)
        struct.pack_into("<H", header, 56, 1)
        program = bytearray(56)
        struct.pack_into("<I", program, 0, 1)
        struct.pack_into("<Q", program, 48, alignment)
    else:
        header = bytearray(52)
        header[:6] = b"\x7fELF\x01\x01"
        struct.pack_into("<H", header, 18, machine)
        struct.pack_into("<I", header, 28, 52)
        struct.pack_into("<H", header, 42, 32)
        struct.pack_into("<H", header, 44, 1)
        program = bytearray(32)
        struct.pack_into("<I", program, 0, 1)
        struct.pack_into("<I", program, 28, alignment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + program + text)


def _provenance(stage: Path, target: str) -> None:
    write_json(stage / "libmpv-runtime.json", {"schemaVersion": 1, "artifact": target})


def test_android_structure_checks_all_abis_and_16k_alignment(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    stage = tmp_path / "android"
    filters = b"\0".join(item.encode() for item in config.contract.required_audio_filters)
    settings = {
        "arm64-v8a": (64, 183, 16_384),
        "armeabi-v7a": (32, 40, 4_096),
        "x86_64": (64, 62, 16_384),
        "x86": (32, 3, 4_096),
    }
    for abi, (bits, machine, alignment) in settings.items():
        for name in (
            "libmpv.so",
            "libavcodec.so",
            "libavfilter.so",
            "libc++_shared.so",
            "libmediakitandroidhelper.so",
        ):
            _elf(
                stage / "jniLibs" / abi / name,
                bits=bits,
                machine=machine,
                alignment=alignment,
                text=filters if name == "libavfilter.so" else b"",
            )
    _provenance(stage, "android")
    evidence = validate_structure(
        config, config.artifact("android"), stage, tmp_path / "android.json"
    )
    assert evidence.is_file()

    failing = stage / "jniLibs" / "x86_64" / "libmpv.so"
    _elf(failing, bits=64, machine=62, alignment=4_096)
    with pytest.raises(VerificationError, match="alignment"):
        validate_structure(config, config.artifact("android"), stage, tmp_path / "bad.json")


def test_darwin_structure_requires_real_filter_table(
    config: RepositoryConfig, tmp_path: Path
) -> None:
    stage = tmp_path / "macos"
    for name in ("Mpv", "Avfilter"):
        framework = stage / f"{name}.xcframework"
        framework.mkdir(parents=True)
        with (framework / "Info.plist").open("wb") as file:
            plistlib.dump(
                {
                    "AvailableLibraries": [
                        {
                            "SupportedArchitectures": ["arm64", "x86_64"],
                            "SupportedPlatform": "macos",
                        }
                    ]
                },
                file,
            )
    binary = stage / "Avfilter.xcframework" / "macos-arm64_x86_64" / "Avfilter"
    binary.parent.mkdir()
    binary.write_bytes(b"\0".join(item.encode() for item in config.contract.required_audio_filters))
    _provenance(stage, "macos")
    validate_structure(config, config.artifact("macos"), stage, tmp_path / "macos.json")
    binary.write_bytes(b"loudnorm")
    with pytest.raises(VerificationError, match="filter table"):
        validate_structure(config, config.artifact("macos"), stage, tmp_path / "bad.json")
