# libmpv-runtime

`libmpv-runtime` turns maintained upstream binary releases into one validated
runtime set for Flutter [`media_kit`](https://github.com/media-kit/media-kit).
It does not build mpv, FFmpeg, libplacebo, libass, or dav1d by default, and it
does not add a second player to the application.

The repository follows release channels instead of pinning builder dependency
trees. A candidate becomes immutable only after intake records its exact
release, commit, URLs, byte sizes, and SHA-256 digests and all applicable
structure, decoded-PCM, online playback, and real Flutter consumer gates pass.

## Runtime sources

| Platform | Source | Delivery to MediaKit |
| --- | --- | --- |
| Windows x86_64 | `zhongfly/mpv-winbuild` LGPL development archive plus maintained ANGLE release | exact-name `media_kit_libs_windows_video` drop-in |
| Android, four ABIs | `mpv-android/mpv-android` universal APK; only the MediaKit JNI helper is taken from MediaKit's Android build | exact-name `media_kit_libs_android_video` drop-in |
| macOS and iOS | `media-kit/libmpv-darwin-build` `video-encodersgpl` XCFramework releases | exact-name iOS and macOS drop-ins for CocoaPods and SwiftPM |
| Linux | the distribution's `libmpv.so.2` package | official `media_kit_libs_linux`; no runtime bundle or fallback |

Web is outside the contract because MediaKit does not use libmpv there.

## DSP contract

Every bundled promotion must actually run:

```text
loudnorm dynaudnorm acompressor alimiter volume aresample ebur128 astats
```

The native probe decodes deterministic PCM through libmpv, measures
`volume=0.5` as approximately `-6.0206 dB`, serves the same media over an HTTP
Range endpoint, and inserts the filter after the file is loaded. The Flutter
fixture then proves plugin registration, MediaKit loading, online playback, and
the property path in a real application. A property write alone never passes a
promotion.

## Local control plane

Python 3.12 and `uv` are sufficient for hermetic checks:

```shell
uv sync --locked --extra dev
uv run libmpv-runtime contract validate
uv run libmpv-runtime source list
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Example Windows intake:

```powershell
uv run libmpv-runtime candidate discover --source windows_libmpv --source windows_angle --output work/candidates
uv run libmpv-runtime candidate acquire --candidate work/candidates/windows_libmpv.json --output work/intake/windows_libmpv
uv run libmpv-runtime candidate acquire --candidate work/candidates/windows_angle.json --output work/intake/windows_angle
uv run libmpv-runtime normalize --artifact windows-x86_64 --intake work/intake/windows_libmpv/intake.json --intake work/intake/windows_angle/intake.json --output build/stage/windows-x86_64
uv run libmpv-runtime validate artifact --artifact windows-x86_64 --stage build/stage/windows-x86_64 --evidence build/evidence/windows-x86_64.json
```

GitHub-hosted runner capacity is not needed for candidate discovery or local
Windows/WSL/Android testing. Workflows are split into quality, discovery,
native validation, and explicit promotion so a rate-limited runner cannot
silently change the accepted runtime.

See [architecture](docs/architecture.md), [MediaKit integration](docs/media-kit-integration.md),
and [release policy](docs/release.md).
