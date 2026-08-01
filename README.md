# libmpv-runtime

`libmpv-runtime` turns maintained upstream binary releases into one verified
runtime set for Flutter [`media_kit`](https://github.com/media-kit/media-kit).
It validates and repackages upstream bytes; it does not maintain another mpv,
FFmpeg, libplacebo, libass, or dav1d build graph.

The core rule is simple: discovery happens once. It seals the checkout,
contract, toolchain, exact upstream release IDs and commits, asset URLs, sizes,
and SHA-256 digests into `validation-plan.json`. GitHub-provided digests are
used directly; legacy assets without one are streamed once during discovery and
hashed locally. Every platform job consumes that same file. No validator is
allowed to rediscover `latest`.

## Runtime contract

| Platform | Runtime authority | MediaKit delivery |
| --- | --- | --- |
| Windows x86_64 | `zhongfly/mpv-winbuild` plus maintained ANGLE | exact-name `media_kit_libs_windows_video` drop-in |
| Android, four ABIs | `mpv-android/mpv-android`; MediaKit supplies only its JNI helper | exact-name `media_kit_libs_android_video` drop-in |
| macOS and iOS | `media-kit/libmpv-darwin-build` XCFramework releases | exact-name CocoaPods/SwiftPM drop-ins |
| Linux | each distribution's `libmpv.so.2` package | official `media_kit_libs_linux`; no private fallback |

Web is outside the contract because MediaKit does not use libmpv there.

Every bundled runtime must decode PCM through `loudnorm`, `dynaudnorm`,
`acompressor`, `alimiter`, `volume`, `aresample`, `ebur128`, and `astats`. The
probe measures `volume=0.5` near `-6.0206 dB`, repeats playback through a local
HTTP Range source, and applies a filter after load. Both the minimum and current
MediaKit dependency profiles must then pass a real Flutter consumer.

## Local quality gate

Python 3.12 and `uv` are the only control-plane prerequisites:

```shell
uv sync --locked --extra dev
uv run libmpv-runtime contract validate
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=libmpv_runtime --cov-report=term-missing --cov-fail-under=80
```

Create a plan without starting any native validation:

```shell
GH_TOKEN=... uv run libmpv-runtime plan create \
  --revision "$(git rev-parse HEAD)" \
  --output validation-plan.json
uv run libmpv-runtime plan verify --path validation-plan.json
```

An intake is always selected from that plan:

```shell
uv run libmpv-runtime intake acquire \
  --plan validation-plan.json \
  --source windows_libmpv \
  --output work/intake/windows_libmpv
```

See [architecture](docs/architecture.md), [release policy](docs/release.md), and
[MediaKit integration](docs/media-kit-integration.md).
