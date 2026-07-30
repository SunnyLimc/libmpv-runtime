#!/usr/bin/env bash
set -euo pipefail

source "$LIBMPV_RUNTIME_ROOT/scripts/build/common.sh"

log "pinning upstream source revisions"
mkdir -p "$LIBMPV_RUNTIME_BUILDER/config"
printf '@%s\n' "$(python -m libmpv_runtime.query source ffmpeg revision)" \
  >"$LIBMPV_RUNTIME_BUILDER/config/branch-ffmpeg"
printf '@%s\n' "$(python -m libmpv_runtime.query source libass revision)" \
  >"$LIBMPV_RUNTIME_BUILDER/config/branch-libass"
printf '@%s\n' "$(python -m libmpv_runtime.query source libplacebo revision)" \
  >"$LIBMPV_RUNTIME_BUILDER/config/branch-libplacebo"
printf '@%s\n' "$(python -m libmpv_runtime.query source mpv revision)" \
  >"$LIBMPV_RUNTIME_BUILDER/config/branch-mpv"

cat >"$LIBMPV_RUNTIME_BUILDER/ffmpeg_options" <<'EOF'
--disable-gpl
--disable-nonfree
--enable-version3
--enable-filter=loudnorm
--enable-filter=dynaudnorm
--enable-filter=acompressor
--enable-filter=alimiter
--enable-filter=volume
--enable-filter=aresample
--enable-filter=ebur128
--enable-filter=astats
EOF

cat >"$LIBMPV_RUNTIME_BUILDER/mpv_options" <<'EOF'
-Dgpl=false
-Dbuild-date=false
-Dcplayer=false
-Dlibmpv=true
-Dtests=false
-Dmanpage-build=disabled
-Dhtml-build=disabled
-Dpdf-build=disabled
EOF

cat >"$LIBMPV_RUNTIME_BUILDER/libplacebo_options" <<'EOF'
-Ddefault_library=static
-Dopengl=enabled
-Dvulkan=disabled
-Dglslang=disabled
-Dshaderc=disabled
-Dlcms=disabled
-Ddovi=disabled
-Dlibdovi=disabled
-Dtests=false
-Ddemos=false
-Dbench=false
-Dfuzz=false
EOF

log "fetching exact sources"
(
  cd "$LIBMPV_RUNTIME_BUILDER"
  ./update --skip-selfupdate
)
require_git_head "$LIBMPV_RUNTIME_BUILDER/ffmpeg" \
  "$(python -m libmpv_runtime.query source ffmpeg revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/libass" \
  "$(python -m libmpv_runtime.query source libass revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/libplacebo" \
  "$(python -m libmpv_runtime.query source libplacebo revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/mpv" \
  "$(python -m libmpv_runtime.query source mpv revision)"

log "building static dependencies and shared libmpv"
(
  cd "$LIBMPV_RUNTIME_BUILDER"
  ./build "-j${LIBMPV_RUNTIME_JOBS:-$(getconf _NPROCESSORS_ONLN)}"
)

require_ffmpeg_filters "$LIBMPV_RUNTIME_BUILDER/ffmpeg_build/ffbuild/config.h"

log "normalizing Linux runtime layout"
rm -rf "$LIBMPV_RUNTIME_STAGE"
mkdir -p "$LIBMPV_RUNTIME_STAGE/lib" "$LIBMPV_RUNTIME_STAGE/include"
runtime_binary="$(find "$LIBMPV_RUNTIME_BUILDER/mpv/build" -maxdepth 1 \
  -type f -name 'libmpv.so*' -print -quit)"
require_file "$runtime_binary"
cp -L "$runtime_binary" "$LIBMPV_RUNTIME_STAGE/lib/libmpv.so.2"
ln -s libmpv.so.2 "$LIBMPV_RUNTIME_STAGE/lib/libmpv.so.1"
ln -s libmpv.so.2 "$LIBMPV_RUNTIME_STAGE/lib/libmpv.so"
cp -R "$LIBMPV_RUNTIME_BUILDER/mpv/include/mpv" "$LIBMPV_RUNTIME_STAGE/include/"
copy_source_licenses "$LIBMPV_RUNTIME_STAGE/LICENSES" \
  "$LIBMPV_RUNTIME_BUILDER/mpv" \
  "$LIBMPV_RUNTIME_BUILDER/ffmpeg" \
  "$LIBMPV_RUNTIME_BUILDER/libass" \
  "$LIBMPV_RUNTIME_BUILDER/libplacebo"

log "running decoded PCM filter probes"
probe_build="$LIBMPV_RUNTIME_WORK/probe-build"
rm -rf "$probe_build"
compile_native_probe "$LIBMPV_RUNTIME_STAGE/include" "$probe_build" \
  -DCMAKE_BUILD_TYPE=Release
probe="$probe_build/mpv_dsp_probe"
require_file "$probe"
LD_LIBRARY_PATH="$LIBMPV_RUNTIME_STAGE/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  run_native_filter_probes \
    "$probe" \
    "$LIBMPV_RUNTIME_STAGE/lib/libmpv.so.2" \
    "$LIBMPV_RUNTIME_WORK/probe-output"

record_evidence
