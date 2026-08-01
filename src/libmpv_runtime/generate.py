from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .files import sha256_file, write_json
from .models import RepositoryConfig
from .promotion import load_promotion

_TEMPLATES = Path(__file__).with_name("templates")
_TOKEN = re.compile(r"@@[A-Z0-9_]+@@")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def _template(relative: str, replacements: dict[str, str] | None = None) -> str:
    path = _TEMPLATES / relative
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise IntegrityError(f"cannot read package template: {relative}") from error
    for name, value in (replacements or {}).items():
        content = content.replace(f"@@{name}@@", value)
    unresolved = sorted(set(_TOKEN.findall(content)))
    if unresolved:
        raise IntegrityError(f"unresolved template tokens in {relative}: {', '.join(unresolved)}")
    return content


def _copy_template(relative: str, destination: Path) -> None:
    _write(destination, _template(relative))


def _records(promotion: dict[str, Any], target: str) -> dict[str, dict[str, Any]]:
    artifacts = promotion.get("artifacts")
    values = artifacts.get(target) if isinstance(artifacts, dict) else None
    if not isinstance(values, list):
        raise IntegrityError(f"promotion is missing artifacts for {target}")
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("role"), str):
            raise IntegrityError(f"promotion has an invalid artifact for {target}")
        role = value["role"]
        if role in result:
            raise IntegrityError(f"promotion has duplicate artifact role for {target}: {role}")
        result[role] = value
    return result


def _field(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"promotion artifact has no {key}")
    return value


def _local_artifact(record: dict[str, Any]) -> Path | None:
    value = record.get("localPath")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise IntegrityError("promotion artifact has an invalid localPath")
    path = Path(value)
    if not path.is_file():
        raise IntegrityError(f"local promotion artifact is missing: {path}")
    if sha256_file(path) != _field(record, "sha256"):
        raise IntegrityError(f"local promotion artifact changed: {path}")
    return path


def _pubspec(
    config: RepositoryConfig,
    name: str,
    platform: str,
    plugin_class: str,
    package: str | None = None,
) -> str:
    package_line = f"        package: {package}\n" if package else ""
    return _template(
        "common/pubspec.yaml.tmpl",
        {
            "NAME": name,
            "DART_SDK": config.contract.toolchain.dart_sdk,
            "PLATFORM": platform,
            "PACKAGE_LINE": package_line,
            "PLUGIN_CLASS": plugin_class,
        },
    )


def _generate_android(config: RepositoryConfig, root: Path, bundle: dict[str, Any]) -> None:
    name = "media_kit_libs_android_video"
    package = root / name
    _write(
        package / "pubspec.yaml",
        _pubspec(
            config,
            name,
            "android",
            "MediaKitLibsAndroidVideoPlugin",
            "com.alexmercerind.media_kit_libs_android_video",
        ),
    )
    _write(package / "LICENSE", "See the libmpv-runtime promotion and upstream artifacts.")
    _copy_template("android/settings.gradle", package / "android" / "settings.gradle")
    _copy_template(
        "android/AndroidManifest.xml", package / "android" / "src" / "main" / "AndroidManifest.xml"
    )
    toolchain = config.contract.toolchain
    _write(
        package / "android" / "build.gradle",
        _template(
            "android/build.gradle.tmpl",
            {
                "URL": _field(bundle, "url"),
                "SHA256": _field(bundle, "sha256"),
                "ANDROID_GRADLE_PLUGIN": toolchain.android_gradle_plugin,
                "ANDROID_COMPILE_SDK": str(toolchain.android_compile_sdk),
                "ANDROID_MIN_SDK": str(toolchain.android_min_sdk),
            },
        ),
    )
    java = package / "android" / "src" / "main" / "java" / "com" / "alexmercerind"
    _copy_template(
        "android/MediaKitAndroidHelper.java",
        java / "mediakitandroidhelper" / "MediaKitAndroidHelper.java",
    )
    _copy_template(
        "android/MediaKitLibsAndroidVideoPlugin.java",
        java / "media_kit_libs_android_video" / "MediaKitLibsAndroidVideoPlugin.java",
    )


def _generate_windows(config: RepositoryConfig, root: Path, bundle: dict[str, Any]) -> None:
    name = "media_kit_libs_windows_video"
    package = root / name
    _write(
        package / "pubspec.yaml",
        _pubspec(config, name, "windows", "MediaKitLibsWindowsVideoPluginCApi"),
    )
    _write(package / "LICENSE", "See the libmpv-runtime promotion and upstream artifacts.")
    native = package / "windows"
    _write(
        native / "CMakeLists.txt",
        _template(
            "windows/CMakeLists.txt.tmpl",
            {
                "URL": _field(bundle, "url"),
                "SHA256": _field(bundle, "sha256"),
                "CMAKE_MINIMUM": config.contract.toolchain.cmake_minimum,
            },
        ),
    )
    _copy_template("windows/plugin.cpp", native / "media_kit_libs_windows_video_plugin_c_api.cpp")
    _copy_template(
        "windows/plugin.h",
        native
        / "include"
        / "media_kit_libs_windows_video"
        / "media_kit_libs_windows_video_plugin_c_api.h",
    )


def _generate_apple(
    config: RepositoryConfig,
    root: Path,
    platform: str,
    records: dict[str, dict[str, Any]],
) -> None:
    title = "Ios" if platform == "ios" else "Macos"
    name = f"media_kit_libs_{platform}_video"
    package = root / name
    native = package / platform
    swift_root = native / name / "Sources" / name
    _write(
        package / "pubspec.yaml",
        _pubspec(config, name, platform, f"MediaKitLibs{title}VideoPlugin"),
    )
    _write(package / "LICENSE", "See the libmpv-runtime promotion and upstream artifacts.")
    try:
        bundle = records["bundle"]
    except KeyError as error:
        raise IntegrityError(f"promotion is missing {platform} bundle") from error
    _write(
        native / "Makefile",
        _template(
            "apple/Makefile.tmpl",
            {"URL": _field(bundle, "url"), "SHA256": _field(bundle, "sha256")},
        ),
    )
    _copy_template("apple/create_framework_symlinks.sh", native / "create_framework_symlinks.sh")
    toolchain = config.contract.toolchain
    flutter_dependency = "Flutter" if platform == "ios" else "FlutterMacOS"
    cocoa_platform = "ios" if platform == "ios" else "osx"
    minimum = (
        toolchain.ios_deployment_target if platform == "ios" else toolchain.macos_deployment_target
    )
    _write(
        native / f"{name}.podspec",
        _template(
            "apple/podspec.tmpl",
            {
                "NAME": name,
                "FLUTTER_DEPENDENCY": flutter_dependency,
                "COCOA_PLATFORM": cocoa_platform,
                "MINIMUM": minimum,
                "SWIFT_TOOLS": toolchain.swift_tools,
            },
        ),
    )
    component_records = {
        role.removeprefix("spm:"): record
        for role, record in records.items()
        if role.startswith("spm:")
    }
    if not component_records:
        raise IntegrityError(f"promotion has no SwiftPM components for {platform}")
    names = sorted(item for item in component_records if item != "Fftools-ffi")
    targets = "\n".join(f'    "{item}",' for item in names)
    binary_targets: list[str] = []
    artifacts_directory = native / name / "Artifacts"
    for item in names:
        record = component_records[item]
        local = _local_artifact(record)
        if local is None:
            binary_targets.append(
                f'    .binaryTarget(name: "{item}", '
                f'url: "{_field(record, "url")}", '
                f'checksum: "{_field(record, "sha256")}"),'
            )
            continue
        artifacts_directory.mkdir(parents=True, exist_ok=True)
        destination = artifacts_directory / _field(record, "name")
        shutil.copy2(local, destination)
        binary_targets.append(
            f'    .binaryTarget(name: "{item}", path: "Artifacts/{destination.name}"),'
        )
    swift_platform = f'.iOS("{minimum}")' if platform == "ios" else f'.macOS("{minimum}")'
    _write(
        native / name / "Package.swift",
        _template(
            "apple/Package.swift.tmpl",
            {
                "SWIFT_TOOLS": toolchain.swift_tools,
                "BINARY_TARGETS": "\n".join(binary_targets),
                "TARGETS": targets,
                "NAME": name,
                "SWIFT_PLATFORM": swift_platform,
                "PLATFORM": platform,
            },
        ),
    )
    imports = (
        "import Flutter\nimport UIKit" if platform == "ios" else "import Cocoa\nimport FlutterMacOS"
    )
    _write(
        swift_root / f"MediaKitLibs{title}VideoPlugin.swift",
        _template(
            "apple/Plugin.swift.tmpl",
            {"IMPORTS": imports, "PLUGIN_CLASS": f"MediaKitLibs{title}VideoPlugin"},
        ),
    )
    _copy_template("apple/PrivacyInfo.xcprivacy", swift_root / "PrivacyInfo.xcprivacy")


def create_candidate_manifest(
    promotion_id: str,
    artifacts: dict[str, list[Path]],
    base_url: str,
    output: Path,
) -> Path:
    if not base_url.startswith(("http://", "https://")):
        raise IntegrityError("candidate package base URL must use HTTP or HTTPS")
    records: dict[str, list[dict[str, Any]]] = {}
    for target, paths in artifacts.items():
        target_records: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                raise IntegrityError(f"candidate package artifact is missing: {path}")
            if path.name in {
                f"libmpv-runtime-{target}.zip",
                f"libmpv-runtime-{target}.tar.gz",
            }:
                role = "bundle"
            else:
                prefix = f"libmpv-runtime-{target}-"
                if not path.name.startswith(prefix) or path.suffix != ".zip":
                    raise IntegrityError(f"cannot infer candidate artifact role: {path.name}")
                role = f"spm:{path.name.removeprefix(prefix).removesuffix('.zip')}"
            target_records.append(
                {
                    "role": role,
                    "name": path.name,
                    "url": f"{base_url.rstrip('/')}/{path.name}",
                    "localPath": str(path.resolve()),
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
        records[target] = target_records
    write_json(
        output,
        {
            "schemaVersion": 1,
            "id": promotion_id,
            "createdAt": "candidate-only",
            "repository": base_url,
            "contract": {"path": "candidate", "sha256": "0" * 64},
            "artifacts": records,
            "linux": {},
            "evidence": {},
        },
    )
    return output


def generate_packages(
    config: RepositoryConfig,
    promotion_path: Path,
    output: Path,
    platforms: tuple[str, ...] | None = None,
) -> Path:
    promotion = load_promotion(promotion_path)
    if output.exists():
        raise IntegrityError(f"package output already exists: {output}")
    output.mkdir(parents=True)
    selected = set(platforms or ("android", "windows", "ios", "macos"))
    unknown = selected - {"android", "windows", "ios", "macos"}
    if unknown:
        raise IntegrityError(f"unsupported package platforms: {', '.join(sorted(unknown))}")
    if "android" in selected:
        _generate_android(config, output, _records(promotion, "android")["bundle"])
    if "windows" in selected:
        _generate_windows(config, output, _records(promotion, "windows-x86_64")["bundle"])
    if "ios" in selected:
        _generate_apple(config, output, "ios", _records(promotion, "ios"))
    if "macos" in selected:
        _generate_apple(config, output, "macos", _records(promotion, "macos"))
    _write(
        output / "README.md",
        f"Generated from immutable promotion `{promotion['id']}`. "
        "Use these exact-name path packages in place of the corresponding media_kit_libs packages.",
    )
    return output
