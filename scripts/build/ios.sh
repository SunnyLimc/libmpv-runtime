#!/usr/bin/env bash
set -euo pipefail

source "$LIBMPV_RUNTIME_ROOT/scripts/build/common.sh"

xcode_path="${XCODE_PATH:-}"
if [[ -z "$xcode_path" ]]; then
  developer_path="$(xcode-select -p)"
  xcode_path="${developer_path%/Contents/Developer}"
fi
require_file "$xcode_path/Contents/Developer/usr/bin/xcodebuild"
export DEVELOPER_DIR="$xcode_path/Contents/Developer"

python -m libmpv_runtime.cli lock verify-darwin \
  --path "$LIBMPV_RUNTIME_BUILDER/packages.lock.nix"

log "building iOS device and simulator XCFrameworks"
(
  cd "$LIBMPV_RUNTIME_BUILDER"
  rm -f result
  make \
    XCODE_PATH="$xcode_path" \
    VERSION="$LIBMPV_RUNTIME_VERSION" \
    TARGET=mk-out-xcframeworks-ios-universal-video-default
)

rm -rf "$LIBMPV_RUNTIME_STAGE"
mkdir -p "$LIBMPV_RUNTIME_STAGE"
for xcframework in "$LIBMPV_RUNTIME_BUILDER"/result/*.xcframework; do
  [[ -d "$xcframework" ]] || continue
  cp -R "$xcframework" "$LIBMPV_RUNTIME_STAGE/"
done
require_file "$LIBMPV_RUNTIME_STAGE/Mpv.xcframework/Info.plist"
cp "$LIBMPV_RUNTIME_BUILDER/LICENSE.txt" \
  "$LIBMPV_RUNTIME_STAGE/LICENSES-darwin-builder.txt"
if [[ ! -d "$LIBMPV_RUNTIME_BUILDER/result/LICENSES" ]]; then
  printf 'Darwin transitive license bundle is missing\n' >&2
  exit 1
fi
cp -R "$LIBMPV_RUNTIME_BUILDER/result/LICENSES" "$LIBMPV_RUNTIME_STAGE/"

log "linking a minimal iOS simulator consumer"
frameworks="$LIBMPV_RUNTIME_WORK/ios-frameworks"
rm -rf "$frameworks"
mkdir -p "$frameworks"
framework_flags=()
for xcframework in "$LIBMPV_RUNTIME_STAGE"/*.xcframework; do
  framework="$(find "$xcframework" -type d -path '*ios-arm64_*simulator*/*.framework' -print -quit)"
  if [[ -z "$framework" ]]; then
    framework="$(find "$xcframework" -type d -path '*ios-*-simulator*/*.framework' -print -quit)"
  fi
  if [[ -z "$framework" ]]; then
    printf 'iOS simulator framework slice is missing in %s\n' "$xcframework" >&2
    exit 1
  fi
  cp -R "$framework" "$frameworks/"
  name="$(basename "$framework" .framework)"
  framework_flags+=(-framework "$name")
done
require_file "$frameworks/Mpv.framework/Mpv"

host_arch="$(uname -m)"
case "$host_arch" in
  arm64) simulator_arch=arm64 ;;
  x86_64) simulator_arch=x86_64 ;;
  *) printf 'unsupported macOS host architecture: %s\n' "$host_arch" >&2; exit 1 ;;
esac
xcrun --sdk iphonesimulator clang \
  -arch "$simulator_arch" \
  -mios-simulator-version-min=13.0 \
  -F"$frameworks" \
  "$LIBMPV_RUNTIME_ROOT/probes/native/apple_consumer.c" \
  "${framework_flags[@]}" \
  -o "$LIBMPV_RUNTIME_WORK/ios-consumer"
require_file "$LIBMPV_RUNTIME_WORK/ios-consumer"

log "behavior is release-gated by the macOS target with the same locked DSP sources"
record_evidence "macos-universal"
