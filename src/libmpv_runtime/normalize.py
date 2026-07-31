from __future__ import annotations

import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .acquire import load_intake
from .errors import IntegrityError
from .files import write_json
from .models import ArtifactContract, RepositoryConfig
from .process import run

_ANGLE_DLLS = (
    "d3dcompiler_47.dll",
    "libEGL.dll",
    "libGLESv2.dll",
    "vk_swiftshader.dll",
    "vulkan-1.dll",
    "zlib.dll",
)


def _fresh_directory(path: Path) -> None:
    if path.exists():
        raise IntegrityError(f"output already exists; remove it explicitly before retrying: {path}")
    path.mkdir(parents=True)


def _find_one(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise IntegrityError(f"expected exactly one {name} below {root}, found {len(matches)}")
    return matches[0]


def _asset_paths(intake_path: Path, value: dict[str, Any]) -> list[Path]:
    assets = value.get("assets")
    assert isinstance(assets, list)
    return [
        (intake_path.parent / str(item["path"])).resolve()
        for item in assets
        if isinstance(item, dict)
    ]


def _by_source(intakes: list[Path]) -> tuple[dict[str, list[Path]], list[dict[str, Any]]]:
    files: dict[str, list[Path]] = {}
    provenance: list[dict[str, Any]] = []
    for intake_path in intakes:
        value = load_intake(intake_path)
        candidate = value["candidate"]
        assert isinstance(candidate, dict)
        source = candidate.get("source")
        if not isinstance(source, str) or source in files:
            raise IntegrityError(f"duplicate or invalid intake source: {source}")
        files[source] = _asset_paths(intake_path, value)
        provenance.append(value)
    return files, provenance


def _extract_7z(archive: Path, output: Path) -> None:
    output.mkdir(parents=True)
    run(["7z", "x", "-y", f"-o{output}", str(archive)], cwd=output)


def _normalize_windows(files: dict[str, list[Path]], output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="libmpv-runtime-windows-") as temporary:
        temporary_root = Path(temporary)
        mpv_root = temporary_root / "mpv"
        angle_root = temporary_root / "angle"
        mpv_assets = files.get("windows_libmpv", [])
        angle_assets = files.get("windows_angle", [])
        if len(mpv_assets) != 1 or len(angle_assets) != 1:
            raise IntegrityError("Windows normalization needs one libmpv and one ANGLE asset")
        _extract_7z(mpv_assets[0], mpv_root)
        _extract_7z(angle_assets[0], angle_root)

        shutil.copy2(_find_one(mpv_root, "libmpv-2.dll"), output / "libmpv-2.dll")
        shutil.copy2(_find_one(mpv_root, "libmpv.dll.a"), output / "libmpv.dll.a")
        include = output / "include"
        include.mkdir()
        client = _find_one(mpv_root, "client.h")
        for header in sorted(client.parent.glob("*.h")):
            shutil.copy2(header, include / header.name)
        angle = output / "ANGLE"
        shutil.copytree(angle_root, angle)
        for name in _ANGLE_DLLS:
            _find_one(angle, name)


def _normalize_android(files: dict[str, list[Path]], output: Path, abis: tuple[str, ...]) -> None:
    apk_assets = files.get("android_libmpv", [])
    helper_assets = files.get("android_helper", [])
    if len(apk_assets) != 1 or len(helper_assets) != len(abis):
        raise IntegrityError(
            "Android normalization needs one universal APK and one helper JAR per ABI"
        )
    jni = output / "jniLibs"
    seen: dict[str, set[str]] = {abi: set() for abi in abis}
    with zipfile.ZipFile(apk_assets[0]) as archive:
        for name in archive.namelist():
            parts = Path(name).parts
            if len(parts) != 3 or parts[0] != "lib" or parts[1] not in seen:
                continue
            library = parts[2]
            if not library.endswith(".so") or library == "libplayer.so":
                continue
            destination = jni / parts[1] / library
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
            seen[parts[1]].add(library)

    for jar in helper_assets:
        with zipfile.ZipFile(jar) as archive:
            matches = [
                name for name in archive.namelist() if name.endswith("/libmediakitandroidhelper.so")
            ]
            if len(matches) != 1:
                raise IntegrityError(f"helper JAR must contain one helper library: {jar.name}")
            parts = Path(matches[0]).parts
            if len(parts) < 3 or parts[-2] not in seen:
                raise IntegrityError(f"helper JAR has an unsupported ABI: {jar.name}")
            abi = parts[-2]
            destination = jni / abi / "libmediakitandroidhelper.so"
            destination.write_bytes(archive.read(matches[0]))
            seen[abi].add(destination.name)

    for abi, names in seen.items():
        required = {"libmpv.so", "libavcodec.so", "libc++_shared.so", "libmediakitandroidhelper.so"}
        missing = required - names
        if missing:
            raise IntegrityError(f"Android {abi} is missing: {', '.join(sorted(missing))}")


def _normalize_darwin(files: dict[str, list[Path]], source: str, output: Path) -> None:
    assets = files.get(source, [])
    if len(assets) != 1:
        raise IntegrityError(f"{source} normalization needs exactly one XCFramework bundle")
    with tarfile.open(assets[0], mode="r:gz") as archive:
        archive.extractall(output, filter="data")
    frameworks = list(output.rglob("*.xcframework"))
    if not frameworks:
        raise IntegrityError(f"{source} bundle contains no XCFrameworks")
    common = Path(*frameworks[0].relative_to(output).parts[:-1])
    if common != Path() and all(
        Path(*framework.relative_to(output).parts[:-1]) == common for framework in frameworks
    ):
        nested = output / common
        for item in list(nested.iterdir()):
            shutil.move(str(item), output / item.name)
        while nested != output:
            parent = nested.parent
            nested.rmdir()
            nested = parent


def normalize(
    config: RepositoryConfig,
    artifact: ArtifactContract,
    intakes: list[Path],
    output: Path,
) -> Path:
    files, provenance = _by_source(intakes)
    expected = set(artifact.sources)
    if set(files) != expected:
        raise IntegrityError(
            f"{artifact.name} needs sources {sorted(expected)}, got {sorted(files)}"
        )
    _fresh_directory(output)
    if artifact.platform == "windows":
        _normalize_windows(files, output)
    elif artifact.platform == "android":
        _normalize_android(files, output, artifact.architectures)
    elif artifact.platform == "macos":
        _normalize_darwin(files, "darwin_macos", output)
    elif artifact.platform == "ios":
        _normalize_darwin(files, "darwin_ios", output)
    else:
        raise IntegrityError(f"unsupported normalization platform: {artifact.platform}")
    write_json(
        output / "libmpv-runtime.json",
        {
            "schemaVersion": 1,
            "artifact": artifact.name,
            "contract": "contracts/runtime.toml",
            "intakes": provenance,
        },
    )
    return output
