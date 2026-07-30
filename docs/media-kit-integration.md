# `media_kit` integration

## Android

Each ABI artifact is a Gradle-compatible JAR:

```text
lib/<abi>/libmpv.so
lib/<abi>/libmediakitandroidhelper.so
lib/<abi>/libc++_shared.so
lib/<abi>/<runtime dependencies>.so
com/alexmercerind/mediakitandroidhelper/MediaKitAndroidHelper.class
META-INF/libmpv-runtime/build-manifest.json
META-INF/libmpv-runtime/sbom.spdx.json
META-INF/libmpv-runtime/LICENSES/...
```

The `libmpv.so` build exports `mpv_lavc_set_java_vm`, allowing `media_kit` to
initialize FFmpeg JNI support before playback. All ELF dependencies required by
`libmpv.so` are placed in the same ABI directory, including the matching
NDK `libc++_shared.so`. The combined AAR carries the helper Java bytecode in
`classes.jar`; it is not a native-libraries-only shell.

A consuming Flutter package may either download these JARs in its Gradle build
or unpack the matching ABI directories into `src/main/jniLibs`. Do not add a
different NDK version of `libc++_shared.so` beside this runtime.

## Windows

Bundle `libmpv-2.dll` beside the application executable and retain the other
runtime DLLs in the archive. The import library and headers are included for
native consumers but are not required by Dart FFI.

## Linux

Extract the target `.tar.gz` and place its `lib` directory on the loader path
before starting Flutter. `libmpv.so`, `libmpv.so.1`, and `libmpv.so.2` resolve
to the same release binary.

## macOS and iOS

Use the `Mpv.xcframework` supplied for the target. The framework executable is
named `Mpv`, matching `media_kit`'s `Mpv.framework/Mpv` lookup. Dependent
XCFrameworks from the same release must be embedded together.

## Runtime capability gate

Applications should still detect filter application failures. A successful
property write is not proof of decoded output behavior. The release manifest
records the tested filters and probe result so applications can allowlist known
runtime builds and fall back safely on unknown ones.
