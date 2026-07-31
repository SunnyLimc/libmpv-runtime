# MediaKit integration

Promotions contain four exact-name Flutter packages:

- `media_kit_libs_android_video`
- `media_kit_libs_windows_video`
- `media_kit_libs_ios_video`
- `media_kit_libs_macos_video`

They are `publish_to: none` drop-ins. Extract the package zip from one immutable
promotion into the application's `third_party` directory, then replace the
matching hosted dependency with a path dependency. Do not install both copies.

```yaml
dependencies:
  media_kit: ^1.2.6
  media_kit_video: ^2.0.1
  media_kit_libs_android_video:
    path: third_party/media_kit_libs_android_video
  media_kit_libs_windows_video:
    path: third_party/media_kit_libs_windows_video
```

Add the iOS/macOS package only when that application target is enabled. The
package name is significant: `media_kit_video` detects these exact names when it
configures CocoaPods.

Android downloads one promotion-owned universal native archive with SHA-256,
sets it as `jniLibs`, and retains MediaKit's Java helper contract. Windows
downloads one promotion-owned archive with CMake `EXPECTED_HASH`, restores the
layout expected by `media_kit_video`, and bundles libmpv plus ANGLE. Apple pins
both the aggregate CocoaPods tarball and per-XCFramework SwiftPM checksums.

On Linux, keep the official `media_kit_libs_linux` dependency and install the
distribution packages before building the Flutter app. Debian/Ubuntu use
`libmpv2`, `libmpv-dev`, and `libepoxy-dev`; Fedora uses `mpv-libs`; Arch uses
`mpv`. A build linked against `libmpv.so.2` must run with SONAME 2.

The application remains responsible for separating user volume, mute/startup
gating, and normalization gain. This repository supplies and verifies the DSP
capability; it does not choose loudness policy.
