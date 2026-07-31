# Changelog

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
