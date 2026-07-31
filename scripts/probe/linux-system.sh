#!/usr/bin/env bash
set -euo pipefail

root="${LIBMPV_RUNTIME_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
work="${LIBMPV_RUNTIME_WORK:-$root/work/linux-system-probe}"
mkdir -p "$work"
library="$(ldconfig -p | awk '/libmpv\.so\.2 / { print $NF; exit }')"
test -f "$library"
cc -std=c11 -O2 -Wall -Wextra -Werror "$root/probes/native/mpv_dsp_probe.c" \
  -ldl -o "$work/mpv_dsp_probe"
python -m libmpv_runtime.pcm fixture --output "$work/input.wav"
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
  "$work/mpv_dsp_probe" "$library" "$work/input.wav" \
    "$work/${filters[$index]}.wav" "${expressions[$index]}"
done
port_file="$work/port.txt"
python "$root/scripts/probe/http_media_server.py" --root "$work" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
port="$(cat "$port_file")"
"$work/mpv_dsp_probe" "$library" "http://127.0.0.1:$port/input.wav" \
  "$work/volume-http.wav" 'volume=0.5' after-load
python -m libmpv_runtime.pcm verify-gain --original "$work/input.wav" \
  --processed "$work/volume-http.wav" --expected-db -6.0206 --tolerance-db 0.35
