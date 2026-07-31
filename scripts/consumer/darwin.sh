#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_MACOS_ARTIFACTS:?required}"
: "${LIBMPV_RUNTIME_IOS_ARTIFACTS:?required}"
: "${LIBMPV_RUNTIME_MACOS_EVIDENCE:?required}"
: "${LIBMPV_RUNTIME_IOS_EVIDENCE:?required}"
serve="$LIBMPV_RUNTIME_ROOT/work/consumer-darwin/server"
generated="$LIBMPV_RUNTIME_ROOT/build/generated-packages-darwin"
fixture="$LIBMPV_RUNTIME_ROOT/work/consumer-darwin/app"
for target in "$(dirname "$serve")" "$generated"; do
  case "$target" in "$LIBMPV_RUNTIME_ROOT"/*) ;; *) exit 64 ;; esac
  rm -rf "$target"
done
mkdir -p "$serve"
cp -R "$LIBMPV_RUNTIME_ROOT/fixtures/media_kit_consumer" "$fixture"
read -r -a macos_artifacts <<< "$LIBMPV_RUNTIME_MACOS_ARTIFACTS"
read -r -a ios_artifacts <<< "$LIBMPV_RUNTIME_IOS_ARTIFACTS"
cp "${macos_artifacts[@]}" "${ios_artifacts[@]}" "$serve/"
python -m libmpv_runtime.pcm fixture --output "$serve/input.wav"
port_file="$serve/port.txt"
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$serve" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
port="$(cat "$port_file")"
args=()
for path in "${macos_artifacts[@]}"; do args+=(--artifact "macos=$path"); done
for path in "${ios_artifacts[@]}"; do args+=(--artifact "ios=$path"); done
manifest="$serve/candidate.json"
libmpv-runtime packages candidate-manifest --id runtime-20000101.1 \
  "${args[@]}" --base-url "http://127.0.0.1:$port" --output "$manifest"
libmpv-runtime packages generate --promotion "$manifest" --platform macos --platform ios \
  --output "$generated"
flutter create --platforms=macos,ios --project-name libmpv_runtime_consumer "$fixture"
dart pub add -C "$fixture" \
  "media_kit_libs_macos_video@{path: $generated/media_kit_libs_macos_video}" \
  "media_kit_libs_ios_video@{path: $generated/media_kit_libs_ios_video}"
(cd "$fixture" && flutter build macos --debug -t lib/consumer_main.dart \
  --dart-define="LIBMPV_RUNTIME_TEST_URL=http://127.0.0.1:$port/input.wav")
macos_executable="$fixture/build/macos/Build/Products/Debug/libmpv_runtime_consumer.app/Contents/MacOS/libmpv_runtime_consumer"
[[ -x "$macos_executable" ]]
"$macos_executable"
libmpv-runtime evidence consumer --path "$LIBMPV_RUNTIME_MACOS_EVIDENCE" \
  --detail platform=macos --detail onlinePlayback=passed --detail filterAfterLoad=passed
(cd "$fixture" && flutter build ios --simulator --no-codesign --debug)
libmpv-runtime evidence consumer --path "$LIBMPV_RUNTIME_IOS_EVIDENCE" \
  --detail platform=ios-simulator --detail compileLink=passed --detail pluginRegistration=passed
