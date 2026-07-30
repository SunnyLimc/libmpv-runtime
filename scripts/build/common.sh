#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?}"
: "${LIBMPV_RUNTIME_TARGET:?}"
: "${LIBMPV_RUNTIME_ARCH:?}"
: "${LIBMPV_RUNTIME_BUILDER:?}"
: "${LIBMPV_RUNTIME_WORK:?}"
: "${LIBMPV_RUNTIME_STAGE:?}"
: "${LIBMPV_RUNTIME_EVIDENCE:?}"

readonly REQUIRED_FILTERS=(
  loudnorm
  dynaudnorm
  acompressor
  alimiter
  volume
  aresample
  ebur128
  astats
)

log() {
  printf '\n[%s] %s\n' "$LIBMPV_RUNTIME_TARGET" "$*"
}

require_file() {
  if [[ ! -s "$1" ]]; then
    printf 'required file is missing or empty: %s\n' "$1" >&2
    exit 1
  fi
}

require_git_head() {
  local repository="$1"
  local expected="$2"
  local actual
  actual="$(git -C "$repository" rev-parse HEAD)"
  if [[ "$actual" != "$expected" ]]; then
    printf 'source revision mismatch for %s: expected %s, got %s\n' \
      "$repository" "$expected" "$actual" >&2
    exit 1
  fi
}

require_ffmpeg_filters() {
  local config_header="$1"
  require_file "$config_header"
  local filter macro
  for filter in "${REQUIRED_FILTERS[@]}"; do
    macro="CONFIG_${filter^^}_FILTER"
    if ! grep -Eq "^#define ${macro} 1$" "$config_header"; then
      printf 'required FFmpeg filter is disabled: %s (%s)\n' "$filter" "$macro" >&2
      exit 1
    fi
  done
}

find_ffmpeg_config_header() {
  local root="$1"
  local candidate
  while IFS= read -r candidate; do
    if grep -q '^#define CONFIG_LOUDNORM_FILTER ' "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(find "$root" -type f -name config.h -print)
  printf 'FFmpeg config.h with filter declarations was not found under %s\n' \
    "$root" >&2
  return 1
}

require_elf_load_alignment() {
  local readelf="$1"
  local library="$2"
  local minimum="$3"
  local alignment value
  local seen=0
  while IFS= read -r alignment; do
    seen=1
    value=$((16#${alignment#0x}))
    if (( value < minimum )); then
      printf 'ELF LOAD alignment is too small in %s: %s < 0x%x\n' \
        "$library" "$alignment" "$minimum" >&2
      return 1
    fi
  done < <("$readelf" -lW "$library" | awk '$1 == "LOAD" { print $NF }')
  if (( seen == 0 )); then
    printf 'ELF LOAD segments were not found in %s\n' "$library" >&2
    return 1
  fi
}

copy_source_licenses() {
  local destination="$1"
  shift
  mkdir -p "$destination"
  local source name candidate
  for source in "$@"; do
    name="$(basename "$source")"
    for candidate in \
      "$source/Copyright" \
      "$source/COPYING.LGPLv3" \
      "$source/COPYING.LGPLv2.1" \
      "$source/COPYING" \
      "$source/LICENSE" \
      "$source/LICENSE.md"; do
      if [[ -s "$candidate" ]]; then
        cp "$candidate" "$destination/${name}-$(basename "$candidate").txt"
      fi
    done
  done
}

compile_native_probe() {
  local include_dir="$1"
  local output_dir="$2"
  shift 2
  cmake -S "$LIBMPV_RUNTIME_ROOT/probes/native" -B "$output_dir" \
    -DMPV_INCLUDE_DIR="$include_dir" "$@"
  cmake --build "$output_dir" --config Release --parallel
}

run_native_filter_probes() {
  local probe="$1"
  local library="$2"
  local output_dir="$3"
  mkdir -p "$output_dir"
  local fixture="$output_dir/input.wav"
  python -m libmpv_runtime.pcm fixture --output "$fixture"

  local filter expression output
  for filter in "${REQUIRED_FILTERS[@]}"; do
    case "$filter" in
      loudnorm) expression='loudnorm=I=-16:TP=-1.5:LRA=11' ;;
      dynaudnorm) expression='dynaudnorm=f=250:g=9:p=0.9:m=10' ;;
      acompressor) expression='acompressor=threshold=0.25:ratio=2:attack=20:release=250' ;;
      alimiter) expression='alimiter=limit=0.95:attack=5:release=50' ;;
      volume) expression='volume=0.5' ;;
      aresample) expression='aresample=48000' ;;
      ebur128) expression='ebur128=metadata=1' ;;
      astats) expression='astats=metadata=1:reset=1' ;;
      *) printf 'no probe expression for %s\n' "$filter" >&2; exit 1 ;;
    esac
    output="$output_dir/${filter}.wav"
    "$probe" "$library" "$fixture" "$output" "$expression"
    require_file "$output"
  done

  python -m libmpv_runtime.pcm verify-gain \
    --original "$fixture" \
    --processed "$output_dir/volume.wav" \
    --expected-db -6.0206 \
    --tolerance-db 0.35
}

record_evidence() {
  python -m libmpv_runtime.cli evidence record \
    --target "$LIBMPV_RUNTIME_TARGET" \
    --output "$LIBMPV_RUNTIME_EVIDENCE" \
    --filters "${REQUIRED_FILTERS[@]}"
}
