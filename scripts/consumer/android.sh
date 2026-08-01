#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_ARTIFACT:?required}"
: "${LIBMPV_RUNTIME_WORK:?required}"
: "${LIBMPV_RUNTIME_PLAN:?required}"
: "${LIBMPV_RUNTIME_REPORT:?required}"
serve="$LIBMPV_RUNTIME_WORK/server"
generated="$LIBMPV_RUNTIME_WORK/generated"
fixture="$LIBMPV_RUNTIME_WORK/app"
mkdir -p "$serve"
cp -R "$LIBMPV_RUNTIME_ROOT/fixtures/media_kit_consumer" "$fixture"
cp "$LIBMPV_RUNTIME_ARTIFACT" "$serve/"
python -m libmpv_runtime.pcm fixture --output "$serve/input.wav"
port_file="$serve/port.txt"
port=""
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  if [[ -n "$port" ]]; then
    adb reverse --remove "tcp:$port" >/dev/null 2>&1 || true
  fi
}
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$serve" --port-file "$port_file" &
server_pid=$!
trap cleanup EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
port="$(cat "$port_file")"
adb reverse "tcp:$port" "tcp:$port"
manifest="$serve/candidate.json"
libmpv-runtime packages candidate-manifest --id runtime-20000101.1 \
  --artifact "android=$LIBMPV_RUNTIME_ARTIFACT" --base-url "http://127.0.0.1:$port" \
  --output "$manifest"
libmpv-runtime packages generate --promotion "$manifest" --platform android --output "$generated"
flutter create --platforms=android --project-name libmpv_runtime_consumer "$fixture"
dart pub add -C "$fixture" \
  "media_kit:$LIBMPV_RUNTIME_MEDIA_KIT" \
  "media_kit_video:$LIBMPV_RUNTIME_MEDIA_KIT_VIDEO"
cat >> "$fixture/android/gradle.properties" <<'EOF'
kotlin.incremental=false
kotlin.compiler.execution.strategy=in-process
EOF
dart pub add -C "$fixture" \
  "media_kit_libs_android_video@{path: $generated/media_kit_libs_android_video}"
sed -i 's/<application/<application android:usesCleartextTraffic="true"/' \
  "$fixture/android/app/src/main/AndroidManifest.xml"
(cd "$fixture" && flutter build apk --debug -t lib/consumer_main.dart \
  --dart-define="LIBMPV_RUNTIME_TEST_URL=http://127.0.0.1:$port/input.wav")
adb install -r "$fixture/build/app/outputs/flutter-apk/app-debug.apk"
adb logcat -c
adb shell am start -n com.example.libmpv_runtime_consumer/.MainActivity
passed=false
for _ in $(seq 1 120); do
  logs="$(adb logcat -d -v brief)"
  if grep -q 'LIBMPV_RUNTIME_CONSUMER_OK' <<< "$logs"; then passed=true; break; fi
  if grep -q 'LIBMPV_RUNTIME_CONSUMER_ERROR' <<< "$logs"; then
    grep 'LIBMPV_RUNTIME_CONSUMER_ERROR' <<< "$logs" >&2
    exit 1
  fi
  sleep 0.5
done
[[ "$passed" == true ]]
libmpv-runtime consumer report --plan "$LIBMPV_RUNTIME_PLAN" --target android \
  --profile "$LIBMPV_RUNTIME_PROFILE" --app "$fixture" \
  --artifact "$LIBMPV_RUNTIME_ARTIFACT" --output "$LIBMPV_RUNTIME_REPORT" \
  --detail platform=android --detail onlinePlayback=passed --detail filterAfterLoad=passed \
  --detail jniHelper=passed
