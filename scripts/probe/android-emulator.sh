#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_STAGE:?required}"
: "${LIBMPV_RUNTIME_WORK:?required}"
: "${LIBMPV_RUNTIME_EVIDENCE:?required}"

sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$sdk" ]]; then
  printf 'ANDROID_SDK_ROOT or ANDROID_HOME is required\n' >&2
  exit 1
fi
ndk="${ANDROID_NDK_HOME:-}"
if [[ -z "$ndk" ]]; then
  ndk="$(find "$sdk/ndk" -mindepth 1 -maxdepth 1 -type d -print | sort -V | tail -n 1)"
fi
clang="$(find "$ndk/toolchains/llvm/prebuilt" -path '*/bin/x86_64-linux-android23-clang' -print -quit)"
test -x "$clang"

probe="$LIBMPV_RUNTIME_WORK/mpv_dsp_probe.android"
"$clang" -std=c11 -O2 -Wall -Wextra -Werror \
  "$LIBMPV_RUNTIME_ROOT/probes/native/mpv_dsp_probe.c" -ldl -o "$probe"

local_dir="$LIBMPV_RUNTIME_WORK/android-probe"
rm -rf "$local_dir"
mkdir -p "$local_dir"
python -m libmpv_runtime.pcm fixture --output "$local_dir/input.wav"

remote="/data/local/tmp/libmpv-runtime-${GITHUB_RUN_ID:-local}"
adb shell "rm -rf '$remote' && mkdir -p '$remote'"
adb push "$probe" "$remote/mpv_dsp_probe"
adb push "$LIBMPV_RUNTIME_STAGE/jniLibs/x86_64/." "$remote/"
adb push "$local_dir/input.wav" "$remote/input.wav"
adb shell "chmod 755 '$remote/mpv_dsp_probe'"

filters=(loudnorm dynaudnorm acompressor alimiter volume aresample ebur128 astats)
expressions=(
  'loudnorm=I=-16:TP=-1.5:LRA=11'
  'dynaudnorm=f=250:g=9:p=0.9:m=10'
  'acompressor=threshold=0.25:ratio=2:attack=20:release=250'
  'alimiter=limit=0.95:attack=5:release=50'
  'volume=0.5'
  'aresample=48000'
  'ebur128=metadata=1'
  'astats=metadata=1:reset=1'
)
for index in "${!filters[@]}"; do
  filter="${filters[$index]}"
  expression="${expressions[$index]}"
  adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' '$remote/input.wav' '$remote/$filter.wav' '$expression'"
done

port_file="$local_dir/http-port.txt"
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$local_dir" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; adb shell "rm -rf '\''$remote'\''" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 100); do
  [[ -f "$port_file" ]] && break
  sleep 0.1
done
test -f "$port_file"
port="$(cat "$port_file")"
adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' 'http://10.0.2.2:$port/input.wav' '$remote/volume-http.wav' 'volume=0.5' after-load"
adb pull "$remote/volume-http.wav" "$local_dir/volume-http.wav"
python -m libmpv_runtime.pcm verify-gain \
  --original "$local_dir/input.wav" --processed "$local_dir/volume-http.wav" \
  --expected-db -6.0206 --tolerance-db 0.35
python -m libmpv_runtime.cli evidence behavior --path "$LIBMPV_RUNTIME_EVIDENCE" \
  --filters "${filters[@]}" --measured-gain-db -6.0206
