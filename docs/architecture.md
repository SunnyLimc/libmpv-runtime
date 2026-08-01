# Architecture

## One plan, independent gates, one sealed result

Upstream builders remain responsible for SDKs, codecs, ABIs, linking, and their
dependency trees. This repository owns the trust boundary after those builders
publish a release.

```text
latest release channels + checkout contract/toolchain
                         |
                         v
                 validation-plan.json
                  /      |       \
                 v       v        v
          exact intake  ...   exact intake
                 |                 |
                 v                 v
          canonical stage  ... canonical stage
                 |                 |
         structure / behavior / minimum+current consumers
                  \       |       /
                   sealed evidence
                         |
                         v
                  validated-runtime
                         |
                         v
             runtime-YYYYMMDD.N promotion
                         |
                         v
              exact-name MediaKit packages
```

Discovery groups source rules by repository, so macOS and iOS share one GitHub
release query and one resolved commit. The plan is bound to the full repository
SHA, the hashes of `contracts/runtime.toml` and `sources/upstreams.toml`, the
Flutter/toolchain contract, and every selected upstream asset. A legacy asset
without a GitHub digest is streamed and hashed during plan creation; validators
still receive only fully hashed assets. Non-GitHub asset hosts are rejected.

## Authorities

- `contracts/runtime.toml` owns platform, architecture, toolchain, consumer,
  Linux SONAME, and decoded-PCM probe requirements.
- `sources/upstreams.toml` owns maintained repositories, the `latest` channel,
  and exact asset-name patterns. It contains no builder dependency pins.
- `validation-plan.json` is the only input authority for a validation run.
- `intake.json` proves that downloaded bytes match the plan.
- structure, behavior, and consumer reports are independent raw observations.
- sealed evidence requires every applicable report and every consumer profile;
  it is never updated in place.
- `validation-index.json` hashes one complete cross-platform fan-in.
- `promotion.json` is the published runtime identity. Generated packages never
  use an upstream `latest` URL.

The JSON Schemas in `contracts/` are executed by the control plane, not merely
documentation. Typed Python parsers additionally enforce semantic rules such as
source-equivalent release identity and complete target/profile sets.

## Platform normalization

Windows retains `libmpv-2.dll`, its import library and headers, and MediaKit's
expected ANGLE layout. Android extracts the native dependency closure from the
universal upstream APK, removes app-only `libplayer.so`, and adds only
`libmediakitandroidhelper.so`. Apple preserves every XCFramework and emits both
an aggregate tarball and per-framework SwiftPM archives.

Linux deliberately has no bundled artifact. The application links against the
distribution runtime and SONAME; a private post-build replacement cannot make
that binary portable across incompatible SONAMEs. Debian 12, Debian 13, Ubuntu
24.04, Fedora, and Arch each run structure and native decoded-PCM gates in their
own container.
The gate verifies `/etc/os-release` against the named profile and records it in
the sealed evidence, so a mislabeled container cannot impersonate another
distribution.

## Validation truth

Structure validation reads PE, ELF, and XCFramework facts, including all Android
ABIs and 16 KiB alignment. Behavior validation dynamically loads libmpv and
checks actual decoded audio, online Range playback, and after-load filter
insertion. Consumer validation creates a real Flutter application, installs the
generated exact-name package, and records actual Flutter and resolved pub
versions plus every consumed artifact's name, size, and SHA-256. Promotion
requires both consumer profiles to match the bytes it is about to publish.

iOS behavior is explicitly `source-equivalent`: it reuses native macOS DSP
evidence only when both artifacts resolve to the same upstream release and
commit, while iOS still has its own simulator compile/link/plugin gate. It is
never mislabeled as a native iOS playback probe.

All disposable work directories are created by the Python control plane and
carry an ownership marker. An unowned directory is refused rather than erased.
