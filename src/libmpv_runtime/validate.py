from __future__ import annotations

import ctypes
import ctypes.util
import platform
import plistlib
import re
import struct
from pathlib import Path
from typing import Any

from .errors import VerificationError
from .files import read_json, write_json
from .models import ArtifactContract, RepositoryConfig

_ELF_MACHINE = {
    "arm64-v8a": 183,
    "armeabi-v7a": 40,
    "x86_64": 62,
    "x86": 3,
}


def _file(path: Path) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise VerificationError(f"required file is missing or empty: {path}")
    return path


def _contains_filters(paths: list[Path], required: tuple[str, ...]) -> None:
    data = b"".join(path.read_bytes() for path in paths)
    missing = [name for name in required if name.encode("ascii") not in data]
    if missing:
        raise VerificationError(f"binary filter table is missing: {', '.join(missing)}")


def _pe_machine(path: Path) -> int:
    data = path.read_bytes()[:4096]
    if data[:2] != b"MZ" or len(data) < 64:
        raise VerificationError(f"not a PE binary: {path}")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[offset : offset + 4] != b"PE\0\0":
        raise VerificationError(f"invalid PE header: {path}")
    return int(struct.unpack_from("<H", data, offset + 4)[0])


def _elf(path: Path) -> tuple[int, int]:
    with path.open("rb") as file:
        header = file.read(64)
        if header[:4] != b"\x7fELF" or len(header) < 52:
            raise VerificationError(f"not an ELF binary: {path}")
        elf_class = header[4]
        endian = "<" if header[5] == 1 else ">" if header[5] == 2 else ""
        if elf_class not in {1, 2} or not endian:
            raise VerificationError(f"unsupported ELF encoding: {path}")
        machine = struct.unpack_from(f"{endian}H", header, 18)[0]
        if elf_class == 2:
            phoff = struct.unpack_from(f"{endian}Q", header, 32)[0]
            phentsize = struct.unpack_from(f"{endian}H", header, 54)[0]
            phnum = struct.unpack_from(f"{endian}H", header, 56)[0]
        else:
            phoff = struct.unpack_from(f"{endian}I", header, 28)[0]
            phentsize = struct.unpack_from(f"{endian}H", header, 42)[0]
            phnum = struct.unpack_from(f"{endian}H", header, 44)[0]
        alignments: list[int] = []
        for index in range(phnum):
            file.seek(phoff + index * phentsize)
            program = file.read(phentsize)
            if len(program) != phentsize:
                raise VerificationError(f"truncated ELF program headers: {path}")
            if struct.unpack_from(f"{endian}I", program, 0)[0] != 1:
                continue
            alignment_offset = 48 if elf_class == 2 else 28
            alignment_format = "Q" if elf_class == 2 else "I"
            alignments.append(
                struct.unpack_from(f"{endian}{alignment_format}", program, alignment_offset)[0]
            )
    if not alignments:
        raise VerificationError(f"ELF binary has no load segments: {path}")
    return machine, min(alignments)


def _validate_windows(
    stage: Path, artifact: ArtifactContract, filters: tuple[str, ...]
) -> dict[str, Any]:
    library = _file(stage / "libmpv-2.dll")
    if _pe_machine(library) != 0x8664:
        raise VerificationError("Windows libmpv is not x86_64")
    for relative in artifact.required_files:
        _file(stage / relative)
    _contains_filters([library], filters)
    return {"architecture": "x86_64", "requiredFiles": list(artifact.required_files)}


def _validate_android(
    stage: Path, artifact: ArtifactContract, filters: tuple[str, ...]
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for abi in artifact.architectures:
        directory = stage / "jniLibs" / abi
        libraries = sorted(directory.glob("*.so"))
        if not libraries:
            raise VerificationError(f"Android ABI is empty: {abi}")
        names = {path.name for path in libraries}
        required = set(artifact.required_libraries)
        missing = required - names
        if missing:
            raise VerificationError(f"Android {abi} is missing: {', '.join(sorted(missing))}")
        minimum_alignment = 16_384 if abi in {"arm64-v8a", "x86_64"} else 4_096
        observed_alignment: int | None = None
        for library in libraries:
            machine, alignment = _elf(library)
            if machine != _ELF_MACHINE[abi]:
                raise VerificationError(f"Android architecture mismatch: {abi}/{library.name}")
            if alignment < minimum_alignment:
                raise VerificationError(
                    f"Android load alignment is too small: {abi}/{library.name}={alignment}"
                )
            observed_alignment = (
                alignment if observed_alignment is None else min(observed_alignment, alignment)
            )
        _contains_filters([directory / "libavfilter.so"], filters)
        results[abi] = {"libraries": sorted(names), "minimumLoadAlignment": observed_alignment}
    return {"abis": results}


def _validate_darwin(
    stage: Path, artifact: ArtifactContract, filters: tuple[str, ...]
) -> dict[str, Any]:
    mpv = stage / "Mpv.xcframework"
    avfilter = stage / "Avfilter.xcframework"
    _file(mpv / "Info.plist")
    _file(avfilter / "Info.plist")
    with (mpv / "Info.plist").open("rb") as file:
        info = plistlib.load(file)
    libraries = info.get("AvailableLibraries") if isinstance(info, dict) else None
    if not isinstance(libraries, list) or not libraries:
        raise VerificationError("Mpv.xcframework has no slices")
    observed_architectures: set[str] = set()
    for library in libraries:
        if not isinstance(library, dict):
            raise VerificationError("Mpv.xcframework contains an invalid slice")
        architectures = library.get("SupportedArchitectures")
        supported_platform = library.get("SupportedPlatform")
        variant = library.get("SupportedPlatformVariant")
        if not isinstance(architectures, list) or not isinstance(supported_platform, str):
            raise VerificationError("Mpv.xcframework slice metadata is incomplete")
        if artifact.platform == "ios" and supported_platform != "ios":
            continue
        if artifact.platform == "macos" and supported_platform != "macos":
            continue
        for architecture in architectures:
            name = str(architecture)
            if artifact.platform == "ios" and variant == "simulator":
                name = f"simulator-{name}"
            observed_architectures.add(name)
    required_architectures = set(artifact.architectures)
    if not required_architectures.issubset(observed_architectures):
        raise VerificationError(
            f"Mpv.xcframework is missing architectures: "
            f"{', '.join(sorted(required_architectures - observed_architectures))}"
        )
    binaries = [path for path in avfilter.rglob("Avfilter") if path.is_file()]
    if not binaries:
        raise VerificationError("Avfilter.xcframework has no binaries")
    _contains_filters(binaries, filters)
    frameworks = sorted(path.name for path in stage.glob("*.xcframework"))
    return {"frameworks": frameworks, "architectures": sorted(observed_architectures)}


def validate_structure(
    config: RepositoryConfig,
    artifact: ArtifactContract,
    stage: Path,
    evidence: Path,
) -> Path:
    if not stage.is_dir():
        raise VerificationError(f"stage directory does not exist: {stage}")
    provenance_path = _file(stage / "libmpv-runtime.json")
    provenance = read_json(provenance_path)
    filters = config.contract.required_audio_filters
    if artifact.platform == "windows":
        details = _validate_windows(stage, artifact, filters)
    elif artifact.platform == "android":
        details = _validate_android(stage, artifact, filters)
    elif artifact.platform in {"macos", "ios"}:
        details = _validate_darwin(stage, artifact, filters)
    else:
        raise VerificationError(f"unsupported platform: {artifact.platform}")
    write_json(
        evidence,
        {
            "schemaVersion": 1,
            "kind": "structure",
            "target": artifact.name,
            "requiredFilters": list(filters),
            "details": details,
            "provenance": provenance,
        },
    )
    return evidence


def validate_linux_system(
    config: RepositoryConfig, profile: str, plan_sha256: str
) -> dict[str, Any]:
    if profile not in config.contract.linux.profiles:
        choices = ", ".join(sorted(config.contract.linux.profiles))
        raise VerificationError(f"unknown Linux profile {profile!r}; choose one of: {choices}")
    profile_contract = config.contract.linux.profiles[profile]
    try:
        os_release = platform.freedesktop_os_release()
    except OSError as error:
        raise VerificationError(f"cannot read /etc/os-release: {error}") from error
    os_id = os_release.get("ID", "")
    version_id = os_release.get("VERSION_ID", "")
    if os_id != profile_contract.os_id or not re.fullmatch(
        profile_contract.version_pattern, version_id
    ):
        raise VerificationError(f"Linux profile {profile} does not match host {os_id} {version_id}")
    discovered = ctypes.util.find_library("mpv")
    if not discovered:
        raise VerificationError("system libmpv was not found")
    if f".so.{config.contract.linux.soname_major}" not in discovered:
        raise VerificationError(
            f"system libmpv SONAME is incompatible: expected .so.2, found {discovered}"
        )
    try:
        library = ctypes.CDLL(discovered)
        symbol = library.mpv_client_api_version
    except (OSError, AttributeError) as error:
        raise VerificationError(
            f"cannot load mpv_client_api_version from {discovered}: {error}"
        ) from error
    symbol.restype = ctypes.c_ulong
    api = int(symbol())
    return {
        "schemaVersion": 1,
        "kind": "linux-structure",
        "planSha256": plan_sha256,
        "profile": profile,
        "osRelease": {"id": os_id, "versionId": version_id},
        "library": discovered,
        "clientApi": f"{api >> 16}.{api & 0xFFFF}",
        "runtimePackages": list(config.contract.linux.profiles[profile].runtime_packages),
    }
