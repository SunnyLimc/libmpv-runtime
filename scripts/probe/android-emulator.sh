#!/usr/bin/env bash
set -euo pipefail

source "$LIBMPV_RUNTIME_ROOT/scripts/build/common.sh"

if [[ "$LIBMPV_RUNTIME_ARCH" != "x86_64" ]]; then
  printf 'Android emulator probe requires x86_64, got %s\n' "$LIBMPV_RUNTIME_ARCH" >&2
  exit 1
fi

builder="$LIBMPV_RUNTIME_BUILDER"
ndk="$builder/buildscripts/sdk/android-ndk-r29"
clang="$(find "$ndk/toolchains/llvm/prebuilt" -path '*/bin/x86_64-linux-android23-clang' -print -quit)"
require_file "$clang"
probe="$LIBMPV_RUNTIME_WORK/mpv_dsp_probe.android"
"$clang" -std=c11 -O2 -Wall -Wextra -Werror \
  -I"$builder/buildscripts/deps/mpv/include" \
  "$LIBMPV_RUNTIME_ROOT/probes/native/mpv_dsp_probe.c" \
  -ldl -o "$probe"

local_dir="$LIBMPV_RUNTIME_WORK/android-probe"
rm -rf "$local_dir"
mkdir -p "$local_dir"
python -m libmpv_runtime.pcm fixture --output "$local_dir/input.wav"

remote="/data/local/tmp/libmpv-runtime-${GITHUB_RUN_ID:-local}"
adb shell "rm -rf '$remote' && mkdir -p '$remote'"
adb push "$probe" "$remote/mpv_dsp_probe"
adb push "$LIBMPV_RUNTIME_STAGE/lib/x86_64/." "$remote/"
adb push "$local_dir/input.wav" "$remote/input.wav"
adb shell "chmod 755 '$remote/mpv_dsp_probe'"

declare -A expressions=(
  [loudnorm]='loudnorm=I=-16:TP=-1.5:LRA=11'
  [dynaudnorm]='dynaudnorm=f=250:g=9:p=0.9:m=10'
  [acompressor]='acompressor=threshold=0.25:ratio=2:attack=20:release=250'
  [alimiter]='alimiter=limit=0.95:attack=5:release=50'
  [volume]='volume=0.5'
  [aresample]='aresample=48000'
  [ebur128]='ebur128=metadata=1'
  [astats]='astats=metadata=1:reset=1'
)
for filter in "${REQUIRED_FILTERS[@]}"; do
  adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' '$remote/input.wav' '$remote/$filter.wav' '${expressions[$filter]}'"
done
adb pull "$remote/volume.wav" "$local_dir/volume.wav"
python -m libmpv_runtime.pcm verify-gain \
  --original "$local_dir/input.wav" \
  --processed "$local_dir/volume.wav" \
  --expected-db -6.0206 \
  --tolerance-db 0.35
adb shell "rm -rf '$remote'"
