# libmpv-runtime

Reproducible, cross-platform `libmpv` runtime artifacts for Flutter
[`media_kit`](https://github.com/media-kit/media-kit), with the audio DSP
capabilities needed for volume normalization.

The repository does not fork the player API. It builds upstream `mpv` and
FFmpeg, normalizes each platform's package layout, and refuses to publish an
artifact unless the declared capabilities are present and a decoded-audio
probe demonstrates that gain is actually applied.

## Supported runtime set

| Platform | Architectures | Release shape | `media_kit` load name |
| --- | --- | --- | --- |
| Android | `arm64-v8a`, `armeabi-v7a`, `x86_64`, `x86` | ABI JARs and one AAR | `libmpv.so` |
| Windows | `x86_64` | `.zip` | `libmpv-2.dll` |
| Linux | `x86_64`, `aarch64` | `.tar.gz` | `libmpv.so.2` |
| macOS | `arm64`, `x86_64` | universal XCFramework | `Mpv.framework/Mpv` |
| iOS | device `arm64`; simulator `arm64`, `x86_64` | XCFramework | `Mpv.framework/Mpv` |

Android runtimes target API 23 or newer. The 64-bit ABIs enforce the 16 KiB
ELF page alignment required for modern 64-bit Android devices; legacy 32-bit
ABIs enforce their supported 4 KiB minimum.

The first release flavor is `video-dsp-lgpl3`. It is intentionally built
without GPL or non-free components. The aggregate runtime license is
`LGPL-3.0-or-later`; every release contains notices, exact source locks,
corresponding-source pointers, an SPDX SBOM, and SHA-256 checksums.

## Guaranteed DSP contract

Every published target must expose these FFmpeg audio filters:

```text
loudnorm dynaudnorm acompressor alimiter volume aresample ebur128 astats
```

Static symbol/config checks are only the first gate. Desktop artifacts also run
`mpv_dsp_probe`, which decodes a deterministic PCM fixture through `libmpv`,
applies an audio filter, captures the result through `ao=pcm`, and verifies the
measured gain. Android runs the same native probe in an `x86_64` emulator.
Other Android ABIs record an explicit source-equivalent reference to that
probe instead of pretending they ran natively. Apple additionally links each
XCFramework slice in a minimal consumer; iOS records its behavioral reference
to the macOS probe built from the same locked DSP source graph and filter
configuration.

## Local workflow

Python 3.12 or newer is the control plane:

```shell
uv sync --locked --extra dev
uv run libmpv-runtime lock validate
uv run libmpv-runtime target list
uv run libmpv-runtime source prepare --target linux-x86_64
uv run libmpv-runtime build --target linux-x86_64
uv run libmpv-runtime verify --target linux-x86_64
uv run libmpv-runtime package --target linux-x86_64
```

Platform toolchains remain native: NDK/Gradle for Android, CMake/MinGW for
Windows, a Linux container for Linux, and Nix/Xcode for Apple. The Python layer
owns input verification, patching, normalized staging, manifests, SBOMs,
checksums, and release policy.

To inspect a build without running it:

```shell
uv run libmpv-runtime build --target android-arm64-v8a --dry-run
```

## Release model

- Pull requests run lock, policy, unit, packaging-fixture, and workflow tests.
- Per-platform workflows build and probe real artifacts.
- A tag named `v*` assembles only artifacts from the same commit.
- Every release index binds the full artifact set to the exact source commit.
- GitHub artifact attestations additionally bind the release to its workflow
  when the repository plan supports them.
- Builder archives and release-critical sources are commit/SHA-256 locked;
  any observed core revision mismatch blocks publication.

See [architecture](docs/architecture.md), [consumer integration](docs/media-kit-integration.md),
and [release policy](docs/release.md).

## Status

The runtime is pre-1.0. Artifact manifests are stable within a release, while
the orchestration API may still change.
