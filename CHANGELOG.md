# Changelog

## 0.3.0-alpha.1

- Replaced per-job discovery with one checkout-bound immutable validation plan.
- Split raw structure, behavior, and consumer observations from write-once
  sealed evidence; both minimum and current MediaKit profiles are mandatory.
- Added a hashed cross-platform validation fan-in and plan-bound promotion.
- Added typed executable JSON Schemas, centrally versioned toolchains, owned
  workspaces, template-backed package sources, and an 80% local coverage gate.
- Expanded Linux validation to Debian 12, Debian 13, Ubuntu 24.04, Fedora, and
  Arch with native decoded-PCM probes.
- Hardened workflows with read-only checkout credentials, pinned setup actions,
  protected release promotion, attestations, and draft-first publication.

## 0.2.0-alpha.1

- Replaced the source-builder architecture with maintained upstream binary
  discovery, verified intake, normalization, validation, and promotion.
- Removed dependency version locks, patches, license gates, and default source
  build workflows.
- Added exact-name MediaKit drop-in generation for Android, Windows, iOS, and
  macOS; Linux now explicitly uses distribution `libmpv.so.2`.
- Added Android 16 KiB ELF checks, Apple filter-table checks, online Range
  decoded-PCM probes, after-load filter insertion, and real Flutter consumers.
- Split GitHub Actions into hermetic quality, discovery, native validation, and
  immutable promotion workflows.
