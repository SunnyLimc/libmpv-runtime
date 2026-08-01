# MediaKit integration

Each promotion contains four exact-name, `publish_to: none` Flutter packages:

- `media_kit_libs_android_video`
- `media_kit_libs_windows_video`
- `media_kit_libs_ios_video`
- `media_kit_libs_macos_video`

Extract the required package zip into an application's `third_party` directory
and replace the corresponding hosted dependency with a path dependency. Never
install both implementations of the same exact package name.

```yaml
dependencies:
  media_kit: 1.2.6
  media_kit_video: 2.0.1
  media_kit_libs_android_video:
    path: third_party/media_kit_libs_android_video
  media_kit_libs_windows_video:
    path: third_party/media_kit_libs_windows_video
```

Use the iOS/macOS package only when that application target is enabled. The
package names matter because `media_kit_video` and CocoaPods use them during
native configuration.

Android verifies the promotion archive in Gradle before exposing its `jniLibs`.
Windows uses CMake `EXPECTED_HASH`, restores MediaKit's libmpv/ANGLE layout, and
bundles the runtime beside the application. Apple pins both the aggregate
CocoaPods tarball and each SwiftPM binary-target checksum. Generated build files
derive SDK, deployment target, CMake, Swift, Gradle, and Flutter versions from
the same contract sealed into the validation plan.

Linux continues to use the official `media_kit_libs_linux`. Install the profile
declared in `contracts/runtime.toml` before building and running the Flutter
application. A binary linked against `libmpv.so.2` must run with SONAME 2.

The application still owns loudness policy. Keep user volume, mute/startup
gating, and normalization gain separate. This project proves runtime DSP and
filter behavior; it does not decide the target loudness or adaptation strategy.
