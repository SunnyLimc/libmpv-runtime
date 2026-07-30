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

log "building universal macOS XCFrameworks"
(
  cd "$LIBMPV_RUNTIME_BUILDER"
  rm -f result
  make \
    XCODE_PATH="$xcode_path" \
    VERSION="$LIBMPV_RUNTIME_VERSION" \
    TARGET=mk-out-xcframeworks-macos-universal-video-default
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

log "flattening macOS framework slices for runtime probing"
frameworks="$LIBMPV_RUNTIME_WORK/macos-frameworks"
rm -rf "$frameworks"
mkdir -p "$frameworks"
for xcframework in "$LIBMPV_RUNTIME_STAGE"/*.xcframework; do
  framework="$(find "$xcframework" -type d -path '*/macos-*/*.framework' -print -quit)"
  if [[ -z "$framework" ]]; then
    printf 'macOS framework slice is missing in %s\n' "$xcframework" >&2
    exit 1
  fi
  cp -R "$framework" "$frameworks/"
done
require_file "$frameworks/Mpv.framework/Mpv"

probe_include="$LIBMPV_RUNTIME_WORK/probe-include"
rm -rf "$probe_include"
mkdir -p "$probe_include/mpv"
cp "$frameworks/Mpv.framework/Headers/"*.h "$probe_include/mpv/"
require_file "$probe_include/mpv/client.h"

probe_build="$LIBMPV_RUNTIME_WORK/probe-build"
rm -rf "$probe_build"
compile_native_probe "$probe_include" "$probe_build" \
  -DCMAKE_BUILD_TYPE=Release
probe="$probe_build/mpv_dsp_probe"
require_file "$probe"
DYLD_FRAMEWORK_PATH="$frameworks${DYLD_FRAMEWORK_PATH:+:$DYLD_FRAMEWORK_PATH}" \
  run_native_filter_probes \
    "$probe" \
    "$frameworks/Mpv.framework/Mpv" \
    "$LIBMPV_RUNTIME_WORK/probe-output"

record_evidence
