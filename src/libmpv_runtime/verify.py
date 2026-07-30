from __future__ import annotations

import os
from pathlib import Path

from .errors import VerificationError
from .evidence import load_evidence
from .models import RepositoryConfig, Target


def _require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise VerificationError(f"required file is missing or empty: {path}")


def _verify_android(stage: Path, target: Target) -> None:
    abi = target.architecture
    _require_file(stage / "lib" / abi / "libmpv.so")
    _require_file(stage / "lib" / abi / "libmediakitandroidhelper.so")
    _require_file(stage / "lib" / abi / "libc++_shared.so")
    _require_file(
        stage / "com" / "alexmercerind" / "mediakitandroidhelper" / "MediaKitAndroidHelper.class"
    )


def _verify_windows(stage: Path, _: Target) -> None:
    _require_file(stage / "libmpv-2.dll")
    _require_file(stage / "include" / "mpv" / "client.h")


def _verify_linux(stage: Path, _: Target) -> None:
    _require_file(stage / "lib" / "libmpv.so.2")
    _require_file(stage / "include" / "mpv" / "client.h")
    for alias in ("libmpv.so", "libmpv.so.1"):
        path = stage / "lib" / alias
        if not (path.exists() or path.is_symlink()):
            raise VerificationError(f"required libmpv alias is missing: {path}")


def _verify_apple(stage: Path, _: Target) -> None:
    framework = stage / "Mpv.xcframework"
    if not framework.is_dir():
        raise VerificationError(f"required XCFramework is missing: {framework}")
    _require_file(framework / "Info.plist")
    binaries = [path for path in framework.rglob("Mpv") if path.is_file()]
    if not binaries:
        raise VerificationError(f"Mpv.xcframework contains no Mpv binary: {framework}")


def verify_target(config: RepositoryConfig, target: Target, stage: Path | None = None) -> Path:
    stage = stage or config.build_dir / "stage" / target.name
    if not stage.is_dir():
        raise VerificationError(f"stage directory does not exist: {stage}")
    verifier = {
        "android": _verify_android,
        "windows": _verify_windows,
        "linux": _verify_linux,
        "macos": _verify_apple,
        "ios": _verify_apple,
    }[target.platform]
    verifier(stage, target)

    evidence_path = config.build_dir / "evidence" / f"{target.name}.json"
    load_evidence(evidence_path, target.name, config.lock.required_audio_filters)

    for path in stage.rglob("*"):
        if path.is_file() and path.stat().st_size == 0:
            raise VerificationError(f"empty staged file: {path}")
        if path.is_symlink() and not (path.parent / os.readlink(path)).exists():
            raise VerificationError(f"broken staged symlink: {path}")
    return stage
