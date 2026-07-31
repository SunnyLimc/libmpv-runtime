# Architecture

## Direct intake, not a universal builder

Platform builders already encode SDK, ABI, linker, codec, and packaging work.
Reimplementing them here would create a second large dependency graph without
improving the product contract. This repository therefore owns selection,
normalization, validation, and promotion; upstream projects continue to own
compilation.

```text
maintained release channel
          |
          v
candidate.json (release id, tag, commit, asset digest)
          |
          v
intake.json + unchanged downloaded bytes
          |
          v
canonical platform stage
          |
          +---- binary/ABI/dependency/filter inspection
          +---- native local + HTTP decoded-PCM probe
          +---- real Flutter/MediaKit consumer
          |
          v
immutable runtime-YYYYMMDD.N promotion
          |
          v
exact-name MediaKit drop-in packages
```

There is no source version lock, patch series, builder pin, compiler image, or
fallback source build in the default path. If an upstream later stops producing
a viable target, validation fails and the previous promotion remains current.
Only evidence of a persistent gap justifies adding a narrowly scoped builder.

## Authorities

- `contracts/runtime.toml` defines supported platforms, architectures, loader
  names, Linux SONAME, and required audio filters.
- `sources/upstreams.toml` defines maintained repositories, `latest` release
  channels, and exact asset-name patterns. It must not contain dependency
  versions.
- `candidate.json` freezes what discovery observed, but is not trusted yet.
- `intake.json` binds the actual downloaded bytes to independently calculated
  SHA-256 digests.
- evidence files are append-only gate state: structure, behavior, then consumer.
- `promotion.json` is the only accepted runtime identity. Consumers never use
  an upstream `latest` URL.

## Platform normalization

Windows keeps `libmpv-2.dll`, its import library and headers, and the ANGLE DLL
set expected by MediaKit. Android extracts the native dependency closure from
the universal upstream APK, excludes its app-only `libplayer.so`, and adds only
`libmediakitandroidhelper.so` from MediaKit's package. Apple preserves all
XCFrameworks from the `video-encodersgpl` bundle and also emits one zip per
framework for SwiftPM.

Linux is intentionally different. `media_kit_video` links with `pkg-config mpv`
and records the linked SONAME; installing another private libmpv after building
does not make one Flutter binary portable between SONAME 1 and 2. The supported
baseline is therefore distribution `libmpv.so.2`, with `libmpv-dev` and
`libepoxy-dev` in the application build environment. There is no hidden runtime
fallback.

## Validation semantics

Structure validation checks real binary facts: PE/ELF architecture, Android
load alignment for 16 KiB devices, complete ABI sets, required loader names,
Apple slices, and filter strings in Avfilter. Behavior validation dynamically
loads libmpv and observes decoded audio. Consumer validation uses the generated
package in a Flutter app and exercises online playback after applying `af`.

iOS currently uses native macOS DSP evidence from the same upstream release
plus an iOS-simulator compile/link/plugin consumer gate. It is labeled
`source-equivalent`, never native iOS behavior. Promotion metadata keeps that
distinction visible.
