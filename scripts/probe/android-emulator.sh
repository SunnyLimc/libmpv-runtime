#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_STAGE:?required}"
: "${LIBMPV_RUNTIME_WORK:?required}"
: "${LIBMPV_RUNTIME_OUTPUT:?required}"
: "${LIBMPV_RUNTIME_BIN:?required}"
: "${LIBMPV_RUNTIME_PROBE_PLAN:?required}"
: "${LIBMPV_RUNTIME_HTTP_FILTER:?required}"
: "${LIBMPV_RUNTIME_ANDROID_MIN_SDK:?required}"

sdk="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$sdk" ]]; then
  printf 'ANDROID_SDK_ROOT or ANDROID_HOME is required\n' >&2
  exit 1
fi
ndk="${ANDROID_NDK_HOME:-}"
if [[ -z "$ndk" ]]; then
  ndk="$(find "$sdk/ndk" -mindepth 1 -maxdepth 1 -type d -print | sort -V | tail -n 1)"
fi
clang="$(find "$ndk/toolchains/llvm/prebuilt" \
  -path "*/bin/x86_64-linux-android${LIBMPV_RUNTIME_ANDROID_MIN_SDK}-clang" -print -quit)"
test -x "$clang"

probe="$LIBMPV_RUNTIME_BIN/mpv_dsp_probe.android"
"$clang" -std=c11 -O2 -Wall -Wextra -Werror \
  "$LIBMPV_RUNTIME_ROOT/probes/native/mpv_dsp_probe.c" -ldl -o "$probe"

local_dir="$LIBMPV_RUNTIME_OUTPUT"
python -m libmpv_runtime.pcm fixture --output "$local_dir/input.wav"

remote="/data/local/tmp/libmpv-runtime-${GITHUB_RUN_ID:-local}"
adb shell "rm -rf '$remote' && mkdir -p '$remote'"
adb push "$probe" "$remote/mpv_dsp_probe"
adb push "$LIBMPV_RUNTIME_STAGE/jniLibs/x86_64/." "$remote/"
adb push "$local_dir/input.wav" "$remote/input.wav"
adb shell "chmod 755 '$remote/mpv_dsp_probe'"

tail -n +2 "$LIBMPV_RUNTIME_PROBE_PLAN" | while IFS=$'\t' read -r filter expression; do
  adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' '$remote/input.wav' '$remote/$filter.wav' '$expression'"
  adb pull "$remote/$filter.wav" "$local_dir/$filter.wav" >/dev/null
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
http_expression="$(awk -F '\t' -v name="$LIBMPV_RUNTIME_HTTP_FILTER" '$1 == name { print $2 }' "$LIBMPV_RUNTIME_PROBE_PLAN")"
test -n "$http_expression"
adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' 'http://10.0.2.2:$port/input.wav' '$remote/volume-http.wav' '$http_expression' after-load"
adb pull "$remote/volume-http.wav" "$local_dir/volume-http.wav"
