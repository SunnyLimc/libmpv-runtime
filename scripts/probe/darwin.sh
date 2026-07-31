#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_STAGE:?required}"
: "${LIBMPV_RUNTIME_WORK:?required}"
: "${LIBMPV_RUNTIME_EVIDENCE:?required}"

probe="$LIBMPV_RUNTIME_WORK/mpv_dsp_probe"
cc -std=c11 -O2 -Wall -Wextra -Werror \
  "$LIBMPV_RUNTIME_ROOT/probes/native/mpv_dsp_probe.c" -o "$probe"
library="$(find "$LIBMPV_RUNTIME_STAGE/Mpv.xcframework" -path '*macos*' -path '*/Mpv.framework/Mpv' -type f -print -quit)"
test -f "$library"
framework_paths="$(find "$LIBMPV_RUNTIME_STAGE" -path '*macos*' -name '*.framework' -type d -exec dirname {} \; | sort -u | paste -sd: -)"

output="$LIBMPV_RUNTIME_WORK/darwin-probe"
rm -rf "$output"
mkdir -p "$output"
python -m libmpv_runtime.pcm fixture --output "$output/input.wav"
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
  DYLD_FRAMEWORK_PATH="$framework_paths" "$probe" "$library" "$output/input.wav" \
    "$output/${filters[$index]}.wav" "${expressions[$index]}"
done

port_file="$output/http-port.txt"
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$output" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
test -f "$port_file"
port="$(cat "$port_file")"
DYLD_FRAMEWORK_PATH="$framework_paths" "$probe" "$library" \
  "http://127.0.0.1:$port/input.wav" "$output/volume-http.wav" 'volume=0.5' after-load
python -m libmpv_runtime.pcm verify-gain --original "$output/input.wav" \
  --processed "$output/volume-http.wav" --expected-db -6.0206 --tolerance-db 0.35
python -m libmpv_runtime.cli evidence behavior --path "$LIBMPV_RUNTIME_EVIDENCE" \
  --filters "${filters[@]}" --measured-gain-db -6.0206
