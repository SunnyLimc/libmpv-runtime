#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_WORK:?required}"
: "${LIBMPV_RUNTIME_PLAN:?required}"
: "${LIBMPV_RUNTIME_MACOS_ARTIFACTS:?required}"
: "${LIBMPV_RUNTIME_IOS_ARTIFACTS:?required}"
: "${LIBMPV_RUNTIME_MACOS_REPORT:?required}"
: "${LIBMPV_RUNTIME_IOS_REPORT:?required}"
serve="$LIBMPV_RUNTIME_WORK/server"
generated="$LIBMPV_RUNTIME_WORK/generated"
fixture="$LIBMPV_RUNTIME_WORK/app"
mkdir -p "$serve"
cp -R "$LIBMPV_RUNTIME_ROOT/fixtures/media_kit_consumer" "$fixture"
macos_artifacts=()
while IFS= read -r path; do
  [[ -n "$path" ]] && macos_artifacts+=("$path")
done <<< "$LIBMPV_RUNTIME_MACOS_ARTIFACTS"
ios_artifacts=()
while IFS= read -r path; do
  [[ -n "$path" ]] && ios_artifacts+=("$path")
done <<< "$LIBMPV_RUNTIME_IOS_ARTIFACTS"
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
macos_report_args=()
ios_report_args=()
for path in "${macos_artifacts[@]}"; do
  args+=(--artifact "macos=$path")
  macos_report_args+=(--artifact "$path")
done
for path in "${ios_artifacts[@]}"; do
  args+=(--artifact "ios=$path")
  ios_report_args+=(--artifact "$path")
done
manifest="$serve/candidate.json"
libmpv-runtime packages candidate-manifest --id runtime-20000101.1 \
  "${args[@]}" --base-url "http://127.0.0.1:$port" --output "$manifest"
libmpv-runtime packages generate --promotion "$manifest" --platform macos --platform ios \
  --output "$generated"
flutter create --platforms=macos,ios --project-name libmpv_runtime_consumer "$fixture"
dart pub add -C "$fixture" \
  "media_kit:$LIBMPV_RUNTIME_MEDIA_KIT" \
  "media_kit_video:$LIBMPV_RUNTIME_MEDIA_KIT_VIDEO"
dart pub add -C "$fixture" \
  "media_kit_libs_macos_video@{path: $generated/media_kit_libs_macos_video}" \
  "media_kit_libs_ios_video@{path: $generated/media_kit_libs_ios_video}"
(cd "$fixture" && flutter build macos --debug -t lib/consumer_main.dart \
  --dart-define="LIBMPV_RUNTIME_TEST_URL=http://127.0.0.1:$port/input.wav")
macos_executable="$fixture/build/macos/Build/Products/Debug/libmpv_runtime_consumer.app/Contents/MacOS/libmpv_runtime_consumer"
[[ -x "$macos_executable" ]]
"$macos_executable"
libmpv-runtime consumer report --plan "$LIBMPV_RUNTIME_PLAN" --target macos \
  --profile "$LIBMPV_RUNTIME_PROFILE" --app "$fixture" \
  "${macos_report_args[@]}" --output "$LIBMPV_RUNTIME_MACOS_REPORT" \
  --detail platform=macos --detail onlinePlayback=passed --detail filterAfterLoad=passed
(cd "$fixture" && flutter build ios --simulator --no-codesign --debug)
libmpv-runtime consumer report --plan "$LIBMPV_RUNTIME_PLAN" --target ios \
  --profile "$LIBMPV_RUNTIME_PROFILE" --app "$fixture" \
  "${ios_report_args[@]}" --output "$LIBMPV_RUNTIME_IOS_REPORT" \
  --detail platform=ios-simulator --detail compileLink=passed --detail pluginRegistration=passed
