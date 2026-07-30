#!/usr/bin/env bash
set -euo pipefail

source "$LIBMPV_RUNTIME_ROOT/scripts/build/common.sh"

if [[ "$LIBMPV_RUNTIME_ARCH" != "x86_64" ]]; then
  printf 'unsupported Windows architecture: %s\n' "$LIBMPV_RUNTIME_ARCH" >&2
  exit 1
fi

build_dir="$LIBMPV_RUNTIME_BUILDER/build_x86_64"
toolchain_root="$LIBMPV_RUNTIME_WORK/clang-root"
source_cache="$LIBMPV_RUNTIME_WORK/source-cache"
mingw_prefix="$LIBMPV_RUNTIME_WORK/mingw/x86_64-w64-mingw32"
mkdir -p "$toolchain_root" "$source_cache" "$mingw_prefix"

log "configuring pinned MinGW/LLVM cross-build"
cmake \
  -DTARGET_ARCH=x86_64-w64-mingw32 \
  -DCOMPILER_TOOLCHAIN=clang \
  -DCMAKE_INSTALL_PREFIX="$toolchain_root" \
  -DMINGW_INSTALL_PREFIX="$mingw_prefix" \
  -DSINGLE_SOURCE_LOCATION="$source_cache" \
  -DRUSTUP_LOCATION="$toolchain_root/install_rustup" \
  -DENABLE_CCACHE=ON \
  -DCLANG_PACKAGES_LTO=ON \
  -G Ninja \
  --fresh \
  -B "$build_dir" \
  -S "$LIBMPV_RUNTIME_BUILDER"

log "building the Windows libmpv dependency closure"
cmake --build "$build_dir" --target mpv --parallel

require_git_head "$source_cache/mpv" \
  "$(python -m libmpv_runtime.query source mpv revision)"
require_git_head "$source_cache/ffmpeg" \
  "$(python -m libmpv_runtime.query source ffmpeg revision)"
require_git_head "$source_cache/libass" \
  "$(python -m libmpv_runtime.query source libass revision)"
require_git_head "$source_cache/libplacebo" \
  "$(python -m libmpv_runtime.query source libplacebo revision)"
require_git_head "$source_cache/dav1d" \
  "$(python -m libmpv_runtime.query source dav1d revision)"

config_header="$(find "$build_dir" -path '*/ffbuild/config.h' -print -quit)"
require_ffmpeg_filters "$config_header"

log "normalizing Windows runtime layout"
runtime_dll="$(find "$build_dir" -type f -name 'libmpv-2.dll' -print -quit)"
import_library="$(find "$build_dir" -type f -name 'libmpv.dll.a' -print -quit)"
headers="$(find "$build_dir" -type d -path '*/mpv-dev*/include/mpv' -print -quit)"
if [[ -z "$headers" ]]; then
  headers="$source_cache/mpv/include/mpv"
fi
require_file "$runtime_dll"
require_file "$import_library"
require_file "$headers/client.h"

rm -rf "$LIBMPV_RUNTIME_STAGE"
mkdir -p "$LIBMPV_RUNTIME_STAGE/include" "$LIBMPV_RUNTIME_STAGE/lib"
cp "$runtime_dll" "$LIBMPV_RUNTIME_STAGE/libmpv-2.dll"
cp "$import_library" "$LIBMPV_RUNTIME_STAGE/lib/libmpv.dll.a"
cp -R "$headers" "$LIBMPV_RUNTIME_STAGE/include/"
copy_source_licenses "$LIBMPV_RUNTIME_STAGE/LICENSES" \
  "$source_cache/mpv" \
  "$source_cache/ffmpeg" \
  "$source_cache/libass" \
  "$source_cache/libplacebo"

log "raw Windows stage is ready; native behavioral probe runs on windows-2025"
