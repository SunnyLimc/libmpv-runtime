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
port=""
server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
  fi
  if [[ -n "$port" ]]; then
    adb reverse --remove "tcp:$port" >/dev/null 2>&1 || true
  fi
  adb shell "rm -rf '$remote'" >/dev/null 2>&1 || true
}
trap cleanup EXIT
adb shell "rm -rf '$remote' && mkdir -p '$remote'" </dev/null
adb push "$probe" "$remote/mpv_dsp_probe" </dev/null
adb push "$LIBMPV_RUNTIME_STAGE/jniLibs/x86_64/." "$remote/" </dev/null
adb push "$local_dir/input.wav" "$remote/input.wav" </dev/null
adb shell "chmod 755 '$remote/mpv_dsp_probe'" </dev/null

http_expression=""
while IFS=$'\t' read -r filter expression; do
  if [[ "$filter" == "name" && "$expression" == "expression" ]]; then
    continue
  fi
  if [[ "$filter" == "$LIBMPV_RUNTIME_HTTP_FILTER" ]]; then
    http_expression="$expression"
  fi
  adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' '$remote/input.wav' '$remote/$filter.wav' '$expression'" </dev/null
  adb pull "$remote/$filter.wav" "$local_dir/$filter.wav" </dev/null >/dev/null
done < "$LIBMPV_RUNTIME_PROBE_PLAN"
if [[ -z "$http_expression" ]]; then
  printf 'HTTP filter is missing from probe plan: %s\n' "$LIBMPV_RUNTIME_HTTP_FILTER" >&2
  exit 1
fi

port_file="$local_dir/http-port.txt"
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$local_dir" --port-file "$port_file" &
server_pid=$!
for _ in $(seq 1 100); do
  [[ -f "$port_file" ]] && break
  sleep 0.1
done
if [[ ! -f "$port_file" ]]; then
  printf 'HTTP fixture server did not publish its port\n' >&2
  exit 1
fi
port="$(cat "$port_file")"
adb reverse "tcp:$port" "tcp:$port" </dev/null
adb shell "cd '$remote' && LD_LIBRARY_PATH='$remote' ./mpv_dsp_probe '$remote/libmpv.so' 'http://127.0.0.1:$port/input.wav' '$remote/volume-http.wav' '$http_expression' after-load" </dev/null
adb pull "$remote/volume-http.wav" "$local_dir/volume-http.wav" </dev/null
