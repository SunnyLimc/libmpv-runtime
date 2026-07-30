#!/usr/bin/env bash
set -euo pipefail

source "$LIBMPV_RUNTIME_ROOT/scripts/build/common.sh"

case "$LIBMPV_RUNTIME_ARCH" in
  arm64-v8a) upstream_arch=arm64 ;;
  armeabi-v7a) upstream_arch=armv7l ;;
  x86_64) upstream_arch=x86_64 ;;
  x86) upstream_arch=x86 ;;
  *) printf 'unsupported Android ABI: %s\n' "$LIBMPV_RUNTIME_ARCH" >&2; exit 1 ;;
esac

host_android_home="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
builder_sdk="$LIBMPV_RUNTIME_BUILDER/buildscripts/sdk/android-sdk-linux"
if [[ -n "$host_android_home" && -d "$host_android_home" && ! -e "$builder_sdk" ]]; then
  mkdir -p "$(dirname "$builder_sdk")"
  ln -s "$host_android_home" "$builder_sdk"
fi

log "downloading Android SDK/NDK and exact native sources"
(
  cd "$LIBMPV_RUNTIME_BUILDER/buildscripts"
  IN_CI=1 ./download.sh
)
require_git_head "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/ffmpeg" \
  "$(python -m libmpv_runtime.query source ffmpeg revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/dav1d" \
  "$(python -m libmpv_runtime.query source dav1d revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/libass" \
  "$(python -m libmpv_runtime.query source libass revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/libplacebo" \
  "$(python -m libmpv_runtime.query source libplacebo revision)"
require_git_head "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/mpv" \
  "$(python -m libmpv_runtime.query source mpv revision)"

mpv_source="$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/mpv"
java_vm_patch="$LIBMPV_RUNTIME_ROOT/patches/android-source/mpv-java-vm.patch"
if ! grep -q 'mpv_lavc_set_java_vm' "$mpv_source/include/mpv/client.h"; then
  git -C "$mpv_source" apply --check --whitespace=error-all "$java_vm_patch"
  git -C "$mpv_source" apply --whitespace=error-all "$java_vm_patch"
fi

log "building Android $LIBMPV_RUNTIME_ARCH runtime"
(
  cd "$LIBMPV_RUNTIME_BUILDER/buildscripts"
  ./buildall.sh --arch "$upstream_arch" mpv
)

prefix="$LIBMPV_RUNTIME_BUILDER/buildscripts/prefix/$upstream_arch"
config_header="$(find_ffmpeg_config_header \
  "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps/ffmpeg/_build_$upstream_arch")"
require_ffmpeg_filters "$config_header"
require_file "$prefix/lib/libmpv.so"

ndk="$LIBMPV_RUNTIME_BUILDER/buildscripts/sdk/android-ndk-r29"
toolchain="$ndk/build/cmake/android.toolchain.cmake"
helper_source="$LIBMPV_RUNTIME_WORK/android-helper/app/src/main/cpp"
helper_build="$LIBMPV_RUNTIME_WORK/helper-build"
rm -rf "$helper_build"
cmake -S "$helper_source" -B "$helper_build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$toolchain" \
  -DANDROID_ABI="$LIBMPV_RUNTIME_ARCH" \
  -DANDROID_PLATFORM=android-23 \
  -DANDROID_STL=c++_static
cmake --build "$helper_build" --parallel

log "normalizing Gradle JAR layout"
rm -rf "$LIBMPV_RUNTIME_STAGE"
abi_dir="$LIBMPV_RUNTIME_STAGE/lib/$LIBMPV_RUNTIME_ARCH"
mkdir -p "$abi_dir"
find "$prefix/lib" -maxdepth 1 -type f -name '*.so*' -exec cp {} "$abi_dir/" \;
helper_library="$(find "$helper_build" -type f -name 'libmediakitandroidhelper.so' -print -quit)"
require_file "$helper_library"
cp "$helper_library" "$abi_dir/libmediakitandroidhelper.so"

android_jar="$builder_sdk/platforms/android-35/android.jar"
require_file "$android_jar"
helper_classes="$LIBMPV_RUNTIME_WORK/helper-classes"
rm -rf "$helper_classes"
mkdir -p "$helper_classes"
javac \
  -source 8 \
  -target 8 \
  -bootclasspath "$android_jar" \
  -d "$helper_classes" \
  "$LIBMPV_RUNTIME_WORK/android-helper/app/src/main/java/com/alexmercerind/mediakitandroidhelper/MediaKitAndroidHelper.java"
cp -R "$helper_classes/com" "$LIBMPV_RUNTIME_STAGE/"
require_file \
  "$LIBMPV_RUNTIME_STAGE/com/alexmercerind/mediakitandroidhelper/MediaKitAndroidHelper.class"

readelf="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
nm="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-nm"
if [[ ! -x "$readelf" ]]; then
  readelf="$(find "$ndk/toolchains/llvm/prebuilt" -path '*/bin/llvm-readelf' -print -quit)"
  nm="$(find "$ndk/toolchains/llvm/prebuilt" -path '*/bin/llvm-nm' -print -quit)"
fi
mpv_symbols="$LIBMPV_RUNTIME_WORK/libmpv.symbols.txt"
helper_symbols="$LIBMPV_RUNTIME_WORK/libmediakitandroidhelper.symbols.txt"
"$nm" -D "$abi_dir/libmpv.so" >"$mpv_symbols"
"$nm" -D "$abi_dir/libmediakitandroidhelper.so" >"$helper_symbols"
grep -q ' mpv_lavc_set_java_vm$' "$mpv_symbols"
grep -q ' MediaKitAndroidHelperGetJavaVM$' "$helper_symbols"
"$readelf" -d "$abi_dir/libmpv.so" >"$LIBMPV_RUNTIME_WORK/libmpv.dynamic.txt"
program_headers="$LIBMPV_RUNTIME_WORK/elf-program-headers.txt"
: >"$program_headers"
while IFS= read -r -d '' library; do
  printf '\n== %s ==\n' "$(basename "$library")" >>"$program_headers"
  "$readelf" -lW "$library" >>"$program_headers"
  require_elf_load_alignment "$readelf" "$library" 16384
done < <(find "$abi_dir" -maxdepth 1 -type f -name '*.so' -print0)

copy_source_tree_licenses \
  "$LIBMPV_RUNTIME_STAGE/LICENSES" \
  "$LIBMPV_RUNTIME_BUILDER/buildscripts/deps"
copy_source_licenses \
  "$LIBMPV_RUNTIME_STAGE/LICENSES" \
  "$LIBMPV_RUNTIME_WORK/android-helper"

behavior_reference=""
if [[ "$LIBMPV_RUNTIME_ARCH" == "x86_64" ]]; then
  if [[ -z "${ANDROID_SERIAL:-}" ]]; then
    printf 'Android x86_64 release evidence requires a running emulator\n' >&2
    exit 1
  fi
  "$LIBMPV_RUNTIME_ROOT/scripts/probe/android-emulator.sh"
else
  log "behavior is release-gated by the x86_64 emulator target from the same source graph"
  behavior_reference="android-x86_64"
fi

record_evidence "$behavior_reference"
