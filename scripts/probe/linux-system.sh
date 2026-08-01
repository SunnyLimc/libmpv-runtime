#!/usr/bin/env bash
set -euo pipefail

root="${LIBMPV_RUNTIME_ROOT:?required}"
output="${LIBMPV_RUNTIME_OUTPUT:?required}"
bin="${LIBMPV_RUNTIME_BIN:?required}"
plan="${LIBMPV_RUNTIME_PROBE_PLAN:?required}"
http_filter="${LIBMPV_RUNTIME_HTTP_FILTER:?required}"
library="$(ldconfig -p | awk '/libmpv\.so\.2 / { print $NF; exit }')"
test -f "$library"
cc -std=c11 -O2 -Wall -Wextra -Werror "$root/probes/native/mpv_dsp_probe.c" \
  -ldl -o "$bin/mpv_dsp_probe"
python -m libmpv_runtime.pcm fixture --output "$output/input.wav"
tail -n +2 "$plan" | while IFS=$'\t' read -r filter expression; do
  "$bin/mpv_dsp_probe" "$library" "$output/input.wav" \
    "$output/$filter.wav" "$expression"
done
port_file="$output/port.txt"
python "$root/scripts/probe/http_media_server.py" --root "$output" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
port="$(cat "$port_file")"
http_expression="$(awk -F '\t' -v name="$http_filter" '$1 == name { print $2 }' "$plan")"
test -n "$http_expression"
"$bin/mpv_dsp_probe" "$library" "http://127.0.0.1:$port/input.wav" \
  "$output/volume-http.wav" "$http_expression" after-load
