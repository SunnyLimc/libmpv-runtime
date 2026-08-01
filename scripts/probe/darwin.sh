#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_STAGE:?required}"
: "${LIBMPV_RUNTIME_WORK:?required}"
: "${LIBMPV_RUNTIME_OUTPUT:?required}"
: "${LIBMPV_RUNTIME_BIN:?required}"
: "${LIBMPV_RUNTIME_PROBE_PLAN:?required}"
: "${LIBMPV_RUNTIME_HTTP_FILTER:?required}"

probe="$LIBMPV_RUNTIME_BIN/mpv_dsp_probe"
cc -std=c11 -O2 -Wall -Wextra -Werror \
  "$LIBMPV_RUNTIME_ROOT/probes/native/mpv_dsp_probe.c" -o "$probe"
library="$(find "$LIBMPV_RUNTIME_STAGE/Mpv.xcframework" -path '*macos*' -path '*/Mpv.framework/Mpv' -print -quit)"
if [[ -z "$library" || ! -f "$library" ]]; then
  echo "Mpv.framework binary is missing or has a broken symlink" >&2
  exit 2
fi
framework_paths="$(find "$LIBMPV_RUNTIME_STAGE" -path '*macos*' -name '*.framework' -type d -exec dirname {} \; | sort -u | paste -sd: -)"

output="$LIBMPV_RUNTIME_OUTPUT"
python -m libmpv_runtime.pcm fixture --output "$output/input.wav"
http_expression=""
while IFS=$'\t' read -r filter expression; do
  if [[ "$filter" == "name" && "$expression" == "expression" ]]; then
    continue
  fi
  if [[ "$filter" == "$LIBMPV_RUNTIME_HTTP_FILTER" ]]; then
    http_expression="$expression"
  fi
  DYLD_FRAMEWORK_PATH="$framework_paths" "$probe" "$library" "$output/input.wav" \
    "$output/$filter.wav" "$expression" </dev/null
done < "$LIBMPV_RUNTIME_PROBE_PLAN"
if [[ -z "$http_expression" ]]; then
  printf 'HTTP filter is missing from probe plan: %s\n' "$LIBMPV_RUNTIME_HTTP_FILTER" >&2
  exit 1
fi

port_file="$output/http-port.txt"
server_log="$output/http-server.log"
rm -f "$port_file" "$server_log"
python -u "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$output" --port-file "$port_file" >"$server_log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  [[ -f "$port_file" ]] && break
  if ! kill -0 "$server_pid" 2>/dev/null; then
    printf 'HTTP fixture server exited before publishing its port\n' >&2
    cat "$server_log" >&2
    exit 1
  fi
  sleep 0.1
done
if [[ ! -f "$port_file" ]]; then
  printf 'HTTP fixture server did not publish its port\n' >&2
  cat "$server_log" >&2
  exit 1
fi
port="$(cat "$port_file")"
url="http://127.0.0.1:$port/input.wav"
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  curl --fail --silent --show-error --range 0-31 "$url" --output /dev/null
if ! NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  DYLD_FRAMEWORK_PATH="$framework_paths" "$probe" "$library" \
  "$url" "$output/volume-http.wav" "$http_expression" after-load </dev/null; then
  echo "macOS libmpv HTTP after-load probe failed after the Range server passed" >&2
  exit 1
fi
