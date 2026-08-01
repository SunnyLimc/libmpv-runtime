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
library="$(find "$LIBMPV_RUNTIME_STAGE/Mpv.xcframework" -path '*macos*' -path '*/Mpv.framework/Mpv' -type f -print -quit)"
test -f "$library"
framework_paths="$(find "$LIBMPV_RUNTIME_STAGE" -path '*macos*' -name '*.framework' -type d -exec dirname {} \; | sort -u | paste -sd: -)"

output="$LIBMPV_RUNTIME_OUTPUT"
python -m libmpv_runtime.pcm fixture --output "$output/input.wav"
tail -n +2 "$LIBMPV_RUNTIME_PROBE_PLAN" | while IFS=$'\t' read -r filter expression; do
  DYLD_FRAMEWORK_PATH="$framework_paths" "$probe" "$library" "$output/input.wav" \
    "$output/$filter.wav" "$expression"
done

port_file="$output/http-port.txt"
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$output" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
test -f "$port_file"
port="$(cat "$port_file")"
http_expression="$(awk -F '\t' -v name="$LIBMPV_RUNTIME_HTTP_FILTER" '$1 == name { print $2 }' "$LIBMPV_RUNTIME_PROBE_PLAN")"
test -n "$http_expression"
DYLD_FRAMEWORK_PATH="$framework_paths" "$probe" "$library" \
  "http://127.0.0.1:$port/input.wav" "$output/volume-http.wav" "$http_expression" after-load
