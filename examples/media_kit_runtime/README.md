# Consuming a release from `media_kit`

This directory documents the intentionally small integration boundary. The
Flutter application continues to depend on `media_kit`; it does not depend on a
second player plugin.

For Android, place the release AAR in an internal Maven repository or unpack
the matching ABI JARs from the release and declare them as Gradle file
dependencies. For Windows, replace the archive downloaded by
`media_kit_libs_windows_video` with the matching `libmpv-runtime` archive. For
Apple, embed every XCFramework from one release as a set. Linux may load the
release directory through the system loader.

At startup, compare the embedded `build-manifest.json` against the allowed
runtime version before enabling DSP-dependent product behavior. Unknown
runtimes should retain normal playback and skip unsupported normalization
filters.
