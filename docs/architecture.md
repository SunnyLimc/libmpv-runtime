# Architecture

## One runtime authority

Applications continue to use `media_kit` and its single `libmpv` instance for
playback. This repository replaces only the native binary package. It does not
add a second decoder, player, or volume owner.

User volume, mute/startup gating, and normalization gain remain separate
application concepts. DSP filters supplied here are capabilities; the runtime
does not decide product policy.

## Build pipeline

```text
runtime.lock.toml
        |
        v
verified builder archive ---> exact patch series ---> native toolchain
        |                                              |
        +---------------- manifest inputs <------------+
                                                       |
                                                       v
                                                normalized stage
                                                       |
                         +-----------------------------+------------------+
                         |                             |                  |
                         v                             v                  v
                 binary/config checks          decoded PCM probe     link/load probe
                         |                             |                  |
                         +-----------------------------+------------------+
                                                       |
                                                       v
                                      licenses + source lock + SPDX SBOM
                                                       |
                                                       v
                                        deterministic release archive
```

Python owns invariant enforcement and metadata. Platform-native build systems
remain responsible for compiling:

- Android: NDK/Gradle on Linux.
- Windows: CMake/Ninja/MinGW cross-build in a pinned Linux container.
- Linux: native build on each release architecture.
- Apple: Nix plus the selected Xcode toolchain.

## Why upstream builders are inputs

Each platform has non-trivial SDK and packaging behavior. Reusing a locked
builder commit keeps those details reviewable while this repository owns the
cross-platform contract. The builder archive is SHA-256 verified before
extraction, then patched locally. Core mpv, FFmpeg, libass, libplacebo, and
dav1d revisions are checked against the lock after source acquisition; a
builder dependency update cannot silently promote a release.

## Verification levels

1. **Policy:** GPL/non-free flags must be absent and the required filter list
   must be declared.
2. **Structure:** load names, architectures, headers, notices, and dependent
   libraries must match the target contract.
3. **Capability:** FFmpeg configuration or exported filter tables must contain
   all required filters.
4. **Behavior:** a deterministic WAV is decoded through `libmpv`; an applied
   gain must change measured PCM by the expected amount without clipping.
5. **Consumer:** native C plus platform link/package fixtures verify the
   layout and dynamic-loading contract used by `media_kit`.

Only artifacts passing all applicable levels are eligible for release.
