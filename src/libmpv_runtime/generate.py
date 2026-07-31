from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .files import sha256_file, write_json
from .promotion import load_promotion


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def _records(promotion: dict[str, Any], target: str) -> dict[str, dict[str, Any]]:
    artifacts = promotion.get("artifacts")
    values = artifacts.get(target) if isinstance(artifacts, dict) else None
    if not isinstance(values, list):
        raise IntegrityError(f"promotion is missing artifacts for {target}")
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("role"), str):
            raise IntegrityError(f"promotion has an invalid artifact for {target}")
        result[value["role"]] = value
    return result


def _field(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"promotion artifact has no {key}")
    return value


def _pubspec(name: str, platform: str, plugin_class: str, package: str | None = None) -> str:
    package_line = f"        package: {package}\n" if package else ""
    return f"""
name: {name}
description: Validated libmpv runtime drop-in for package:media_kit.
version: 0.0.0
publish_to: none

environment:
  sdk: ^3.6.0
  flutter: ">=3.27.4"

dependencies:
  flutter:
    sdk: flutter

flutter:
  plugin:
    platforms:
      {platform}:
{package_line}        pluginClass: {plugin_class}
"""


def _generate_android(root: Path, bundle: dict[str, Any]) -> None:
    name = "media_kit_libs_android_video"
    package = root / name
    _write(
        package / "pubspec.yaml",
        _pubspec(
            name,
            "android",
            "MediaKitLibsAndroidVideoPlugin",
            "com.alexmercerind.media_kit_libs_android_video",
        ),
    )
    _write(package / "LICENSE", "See the libmpv-runtime promotion and upstream artifacts.")
    _write(
        package / "android" / "settings.gradle", "rootProject.name = 'media_kit_libs_android_video'"
    )
    _write(
        package / "android" / "src" / "main" / "AndroidManifest.xml",
        """
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application android:extractNativeLibs="true" />
</manifest>
""",
    )
    url = _field(bundle, "url")
    sha256 = _field(bundle, "sha256")
    _write(
        package / "android" / "build.gradle",
        f"""
import java.nio.file.Files
import java.security.MessageDigest

group 'com.alexmercerind.media_kit_libs_android_video'
version '1.0'

buildscript {{
    repositories {{ google(); mavenCentral() }}
    dependencies {{ classpath 'com.android.tools.build:gradle:8.13.0' }}
}}

rootProject.allprojects {{ repositories {{ google(); mavenCentral() }} }}
apply plugin: 'com.android.library'

def runtimeUrl = System.getenv('LIBMPV_RUNTIME_ANDROID_URL') ?: '{url}'
def runtimeSha256 = System.getenv('LIBMPV_RUNTIME_ANDROID_SHA256') ?: '{sha256}'
def runtimeArchive = file("$buildDir/libmpv-runtime/runtime.zip")
def runtimeDirectory = file("$buildDir/libmpv-runtime/extracted")

tasks.register('prepareLibmpvRuntime') {{
    outputs.dir(runtimeDirectory)
    doLast {{
        runtimeArchive.parentFile.mkdirs()
        if (!runtimeArchive.exists()) {{
            runtimeArchive.withOutputStream {{ stream ->
                stream << new URL(runtimeUrl).openStream()
            }}
        }}
        def digest = MessageDigest.getInstance('SHA-256')
            .digest(Files.readAllBytes(runtimeArchive.toPath())).encodeHex().toString()
        if (digest != runtimeSha256) {{
            runtimeArchive.delete()
            throw new GradleException("libmpv-runtime SHA-256 mismatch: $digest")
        }}
        delete runtimeDirectory
        copy {{ from zipTree(runtimeArchive); into runtimeDirectory }}
    }}
}}

android {{
    if (project.android.hasProperty('namespace')) {{
        namespace 'com.alexmercerind.media_kit_libs_android_video'
    }}
    compileSdkVersion 36
    defaultConfig {{ minSdkVersion 23 }}
    compileOptions {{
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }}
    sourceSets {{ main {{ jniLibs.srcDirs = ["$buildDir/libmpv-runtime/extracted/jniLibs"] }} }}
}}

preBuild.dependsOn(tasks.named('prepareLibmpvRuntime'))
""",
    )
    java = package / "android" / "src" / "main" / "java" / "com" / "alexmercerind"
    _write(
        java / "mediakitandroidhelper" / "MediaKitAndroidHelper.java",
        """
package com.alexmercerind.mediakitandroidhelper;

import android.content.Context;
import android.net.Uri;
import androidx.annotation.Keep;

@Keep
public final class MediaKitAndroidHelper {
    static { System.loadLibrary("mediakitandroidhelper"); }
    private static Context applicationContext;
    public static native long newGlobalObjectRef(Object value);
    public static native void deleteGlobalObjectRef(long reference);
    public static native String copyAssetToFilesDir(String assetName);
    private static native void setApplicationContextNative(Context context);
    public static void setApplicationContextJava(Context context) {
        applicationContext = context;
        setApplicationContextNative(context);
    }
    public static native int openFileDescriptorNative(String uri);
    public static int openFileDescriptorJava(String uri) {
        try {
            return applicationContext.getContentResolver()
                .openFileDescriptor(Uri.parse(uri), "r").detachFd();
        } catch (Throwable error) {
            return -1;
        }
    }
    private MediaKitAndroidHelper() {}
}
""",
    )
    _write(
        java / "media_kit_libs_android_video" / "MediaKitLibsAndroidVideoPlugin.java",
        """
package com.alexmercerind.media_kit_libs_android_video;

import androidx.annotation.NonNull;
import com.alexmercerind.mediakitandroidhelper.MediaKitAndroidHelper;
import io.flutter.embedding.engine.plugins.FlutterPlugin;

public final class MediaKitLibsAndroidVideoPlugin implements FlutterPlugin {
    static { System.loadLibrary("mpv"); }
    @Override
    public void onAttachedToEngine(@NonNull FlutterPluginBinding binding) {
        MediaKitAndroidHelper.setApplicationContextJava(binding.getApplicationContext());
    }
    @Override
    public void onDetachedFromEngine(@NonNull FlutterPluginBinding binding) {}
}
""",
    )


def _generate_windows(root: Path, bundle: dict[str, Any]) -> None:
    name = "media_kit_libs_windows_video"
    package = root / name
    _write(
        package / "pubspec.yaml", _pubspec(name, "windows", "MediaKitLibsWindowsVideoPluginCApi")
    )
    _write(package / "LICENSE", "See the libmpv-runtime promotion and upstream artifacts.")
    url = _field(bundle, "url")
    sha256 = _field(bundle, "sha256")
    _write(
        package / "windows" / "CMakeLists.txt",
        f"""
cmake_minimum_required(VERSION 3.18)
set(PROJECT_NAME "media_kit_libs_windows_video")
project(${{PROJECT_NAME}} LANGUAGES CXX)

option(MEDIA_KIT_LIBS_AVAILABLE "package:media_kit libraries are available." ON)
add_compile_definitions(_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR)

set(RUNTIME_URL "{url}")
set(RUNTIME_SHA256 "{sha256}")
if(DEFINED ENV{{LIBMPV_RUNTIME_WINDOWS_URL}})
  set(RUNTIME_URL "$ENV{{LIBMPV_RUNTIME_WINDOWS_URL}}")
endif()
if(DEFINED ENV{{LIBMPV_RUNTIME_WINDOWS_SHA256}})
  set(RUNTIME_SHA256 "$ENV{{LIBMPV_RUNTIME_WINDOWS_SHA256}}")
endif()
set(RUNTIME_ARCHIVE "${{CMAKE_BINARY_DIR}}/libmpv-runtime-${{RUNTIME_SHA256}}.zip")
set(RUNTIME_ROOT "${{CMAKE_BINARY_DIR}}/libmpv")
if(NOT EXISTS "${{RUNTIME_ARCHIVE}}")
  file(DOWNLOAD "${{RUNTIME_URL}}" "${{RUNTIME_ARCHIVE}}"
       EXPECTED_HASH "SHA256=${{RUNTIME_SHA256}}" TLS_VERIFY ON SHOW_PROGRESS)
endif()
if(NOT EXISTS "${{RUNTIME_ROOT}}/libmpv-2.dll")
  file(REMOVE_RECURSE "${{RUNTIME_ROOT}}")
  file(MAKE_DIRECTORY "${{RUNTIME_ROOT}}")
  file(ARCHIVE_EXTRACT INPUT "${{RUNTIME_ARCHIVE}}" DESTINATION "${{RUNTIME_ROOT}}")
endif()
if(NOT EXISTS "${{CMAKE_BINARY_DIR}}/ANGLE/include/EGL/egl.h")
  file(REMOVE_RECURSE "${{CMAKE_BINARY_DIR}}/ANGLE")
  file(COPY "${{RUNTIME_ROOT}}/ANGLE/" DESTINATION "${{CMAKE_BINARY_DIR}}/ANGLE")
endif()

set(PLUGIN_NAME "media_kit_libs_windows_video_plugin")
add_library(${{PLUGIN_NAME}} SHARED
  "include/media_kit_libs_windows_video/media_kit_libs_windows_video_plugin_c_api.h"
  "media_kit_libs_windows_video_plugin_c_api.cpp")
apply_standard_settings(${{PLUGIN_NAME}})
set_target_properties(${{PLUGIN_NAME}} PROPERTIES CXX_VISIBILITY_PRESET hidden)
target_compile_definitions(${{PLUGIN_NAME}} PRIVATE FLUTTER_PLUGIN_IMPL)
target_include_directories(${{PLUGIN_NAME}} INTERFACE "${{CMAKE_CURRENT_SOURCE_DIR}}/include")
target_link_libraries(${{PLUGIN_NAME}} PRIVATE flutter flutter_wrapper_plugin)

set(media_kit_libs_windows_video_bundled_libraries
  "${{RUNTIME_ROOT}}/libmpv-2.dll"
  "${{RUNTIME_ROOT}}/ANGLE/d3dcompiler_47.dll"
  "${{RUNTIME_ROOT}}/ANGLE/libEGL.dll"
  "${{RUNTIME_ROOT}}/ANGLE/libGLESv2.dll"
  "${{RUNTIME_ROOT}}/ANGLE/vk_swiftshader.dll"
  "${{RUNTIME_ROOT}}/ANGLE/vulkan-1.dll"
  "${{RUNTIME_ROOT}}/ANGLE/zlib.dll"
  PARENT_SCOPE)
""",
    )
    _write(
        package / "windows" / "media_kit_libs_windows_video_plugin_c_api.cpp",
        """
#include "include/media_kit_libs_windows_video/media_kit_libs_windows_video_plugin_c_api.h"

void MediaKitLibsWindowsVideoPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar) {
  (void)registrar;
}
""",
    )
    _write(
        package
        / "windows"
        / "include"
        / "media_kit_libs_windows_video"
        / "media_kit_libs_windows_video_plugin_c_api.h",
        """
#ifndef FLUTTER_PLUGIN_MEDIA_KIT_LIBS_WINDOWS_VIDEO_PLUGIN_C_API_H_
#define FLUTTER_PLUGIN_MEDIA_KIT_LIBS_WINDOWS_VIDEO_PLUGIN_C_API_H_
#include <flutter_plugin_registrar.h>
#ifdef FLUTTER_PLUGIN_IMPL
#define FLUTTER_PLUGIN_EXPORT __declspec(dllexport)
#else
#define FLUTTER_PLUGIN_EXPORT __declspec(dllimport)
#endif
#ifdef __cplusplus
extern "C" {
#endif
FLUTTER_PLUGIN_EXPORT void MediaKitLibsWindowsVideoPluginCApiRegisterWithRegistrar(
    FlutterDesktopPluginRegistrarRef registrar);
#ifdef __cplusplus
}
#endif
#endif
""",
    )


def _symlink_script() -> str:
    return """
#!/bin/sh
set -eu
source_dir="$1"
links_dir="$2"
relpath() {
  current="${2:+$1}"; target="${2:-$1}"; target="/${target##/}"; current="/${current##/}"
  appendix="${target##/}"; relative=''
  while appendix="${target#"$current"/}"; [ "$current" != '/' ] && [ "$appendix" = "$target" ]; do
    if [ "$current" = "$appendix" ]; then echo "${relative:-.}"; return 0; fi
    current="${current%/*}"; relative="$relative${relative:+/}.."
  done
  echo "$relative${relative:+${appendix:+/}}${appendix#/}"
}
find "$source_dir" -mindepth 1 -maxdepth 1 -type d | while read -r source; do
  slug="$(basename "$source")"; name="$(echo "$slug" | cut -d '-' -f 1,3)"
  ln -s "$(relpath "$links_dir" "$source")" "$links_dir/$name"
done
"""


def _privacy_manifest() -> str:
    return """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>NSPrivacyTrackingDomains</key><array/>
<key>NSPrivacyAccessedAPITypes</key><array/>
<key>NSPrivacyCollectedDataTypes</key><array/>
<key>NSPrivacyTracking</key><false/>
</dict></plist>
"""


def _generate_apple(root: Path, platform: str, records: dict[str, dict[str, Any]]) -> None:
    title = "Ios" if platform == "ios" else "Macos"
    name = f"media_kit_libs_{platform}_video"
    package = root / name
    native = package / platform
    swift_root = native / name / "Sources" / name
    _write(package / "pubspec.yaml", _pubspec(name, platform, f"MediaKitLibs{title}VideoPlugin"))
    _write(package / "LICENSE", "See the libmpv-runtime promotion and upstream artifacts.")
    bundle = records.get("bundle")
    if bundle is None:
        raise IntegrityError(f"promotion is missing {platform} bundle")
    url = _field(bundle, "url")
    sha256 = _field(bundle, "sha256")
    _write(
        native / "Makefile",
        f"""
all: Frameworks/*.xcframework Frameworks/.symlinks
RUNTIME_URL?={url}
RUNTIME_SHA256?={sha256}
SED=sed
SED_INPLACE_FLAG := $(shell ${{SED}} --version 2>&1 | grep -q 'GNU' && echo "" || echo "''")
.cache/runtime.tar.gz:
	mkdir -p .cache
	curl -fL "$(RUNTIME_URL)" -o .cache/runtime.tar.gz.tmp
	printf '%s  %s\\n' '$(RUNTIME_SHA256)' '.cache/runtime.tar.gz.tmp' | shasum -a 256 -c -
	mv .cache/runtime.tar.gz.tmp .cache/runtime.tar.gz
Frameworks/*.xcframework: .cache/runtime.tar.gz
	rm -rf Frameworks
	mkdir -p Frameworks
	tar -xzf .cache/runtime.tar.gz -C Frameworks
	touch Frameworks/*.xcframework
Frameworks/.symlinks: Frameworks/*.xcframework
	rm -rf Frameworks/.symlinks
	mkdir -p Frameworks/.symlinks/mpv
	${{SED}} -i ${{SED_INPLACE_FLAG}} 's/\\r$$//g' create_framework_symlinks.sh
	sh create_framework_symlinks.sh Frameworks/Mpv.xcframework Frameworks/.symlinks/mpv
clean:
	rm -rf .cache Frameworks
.PHONY: all clean
""",
    )
    _write(native / "create_framework_symlinks.sh", _symlink_script())
    flutter_dependency = "Flutter" if platform == "ios" else "FlutterMacOS"
    cocoa_platform = "ios" if platform == "ios" else "osx"
    minimum = "9.0" if platform == "ios" else "10.9"
    _write(
        native / f"{name}.podspec",
        f"""
Pod::Spec.new do |s|
  system("make")
  s.name = '{name}'
  s.version = '0.0.0'
  s.summary = 'Validated libmpv runtime for package:media_kit'
  s.homepage = 'https://github.com/SunnyLimc/libmpv-runtime'
  s.license = {{ :file => '../LICENSE' }}
  s.author = {{ 'libmpv-runtime' => 'noreply@example.invalid' }}
  s.source = {{ :path => '.' }}
  s.source_files = '{name}/Sources/{name}/**/*.swift'
  s.dependency '{flutter_dependency}'
  s.resource_bundles = {{ '{name}_privacy' => ['{name}/Sources/{name}/PrivacyInfo.xcprivacy'] }}
  s.vendored_frameworks = 'Frameworks/*.xcframework'
  s.platform = :{cocoa_platform}, '{minimum}'
  s.pod_target_xcconfig = {{ 'DEFINES_MODULE' => 'YES' }}
  s.swift_version = '5.0'
end
""",
    )
    component_records = {
        role.removeprefix("spm:"): record
        for role, record in records.items()
        if role.startswith("spm:")
    }
    if not component_records:
        raise IntegrityError(f"promotion has no SwiftPM components for {platform}")
    # Fftools-ffi is an ffmpeg command-line bridge, not part of libmpv's
    # runtime link closure, and its hyphenated module name is not Swift-safe.
    names = sorted(name for name in component_records if name != "Fftools-ffi")
    declarations = "\n".join(
        f'    "{item}": ("{_field(component_records[item], "url")}", '
        f'"{_field(component_records[item], "sha256")}"),'
        for item in names
    )
    targets = "\n".join(f'    "{item}",' for item in names)
    swift_platform = '.iOS("9.0")' if platform == "ios" else '.macOS("10.9")'
    _write(
        native / name / "Package.swift",
        f"""
// swift-tools-version: 5.9
import PackageDescription
let artifacts: [String: (String, String)] = [
{declarations}
]
let frameworks = [
{targets}
]
let package = Package(
  name: "{name}",
  platforms: [{swift_platform}],
  products: [
    .library(name: "media-kit-libs-{platform}-video", targets: ["{name}"] + frameworks),
    .library(name: "Mpv", targets: ["Mpv"]),
  ],
  targets: frameworks.map {{ framework in
    .binaryTarget(name: framework, url: artifacts[framework]!.0, checksum: artifacts[framework]!.1)
  }} + [
    .target(name: "{name}", dependencies: frameworks.map {{ .target(name: $0) }},
            resources: [.process("PrivacyInfo.xcprivacy")])
  ]
)
""",
    )
    framework_import = (
        "Flutter\nimport UIKit" if platform == "ios" else "Cocoa\nimport FlutterMacOS"
    )
    registrar = "FlutterPluginRegistrar"
    _write(
        swift_root / f"MediaKitLibs{title}VideoPlugin.swift",
        f"""
import {framework_import}
public class MediaKitLibs{title}VideoPlugin: NSObject, FlutterPlugin {{
  public static func register(with registrar: {registrar}) {{}}
}}
""",
    )
    _write(swift_root / "PrivacyInfo.xcprivacy", _privacy_manifest())


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
    promotion_path: Path, output: Path, platforms: tuple[str, ...] | None = None
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
        _generate_android(output, _records(promotion, "android")["bundle"])
    if "windows" in selected:
        _generate_windows(output, _records(promotion, "windows-x86_64")["bundle"])
    if "ios" in selected:
        _generate_apple(output, "ios", _records(promotion, "ios"))
    if "macos" in selected:
        _generate_apple(output, "macos", _records(promotion, "macos"))
    _write(
        output / "README.md",
        f"Generated from immutable promotion `{promotion['id']}`. "
        "Use these exact-name path packages "
        "in place of the corresponding media_kit_libs packages.",
    )
    return output
