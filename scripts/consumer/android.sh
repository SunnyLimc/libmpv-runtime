#!/usr/bin/env bash
set -euo pipefail

: "${LIBMPV_RUNTIME_ROOT:?required}"
: "${LIBMPV_RUNTIME_ARTIFACT:?required}"
: "${LIBMPV_RUNTIME_EVIDENCE:?required}"
serve="$LIBMPV_RUNTIME_ROOT/work/consumer-android/server"
generated="$LIBMPV_RUNTIME_ROOT/build/generated-packages-android"
fixture="$LIBMPV_RUNTIME_ROOT/work/consumer-android/app"
for target in "$(dirname "$serve")" "$generated"; do
  case "$target" in "$LIBMPV_RUNTIME_ROOT"/*) ;; *) exit 64 ;; esac
  rm -rf "$target"
done
mkdir -p "$serve"
cp -R "$LIBMPV_RUNTIME_ROOT/fixtures/media_kit_consumer" "$fixture"
cp "$LIBMPV_RUNTIME_ARTIFACT" "$serve/"
python -m libmpv_runtime.pcm fixture --output "$serve/input.wav"
port_file="$serve/port.txt"
python "$LIBMPV_RUNTIME_ROOT/scripts/probe/http_media_server.py" \
  --root "$serve" --port-file "$port_file" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do [[ -f "$port_file" ]] && break; sleep 0.1; done
port="$(cat "$port_file")"
manifest="$serve/candidate.json"
libmpv-runtime packages candidate-manifest --id runtime-20000101.1 \
  --artifact "android=$LIBMPV_RUNTIME_ARTIFACT" --base-url "http://127.0.0.1:$port" \
  --output "$manifest"
libmpv-runtime packages generate --promotion "$manifest" --platform android --output "$generated"
flutter create --platforms=android --project-name libmpv_runtime_consumer "$fixture"
cat >> "$fixture/android/gradle.properties" <<'EOF'
kotlin.incremental=false
kotlin.compiler.execution.strategy=in-process
EOF
dart pub add -C "$fixture" \
  "media_kit_libs_android_video@{path: $generated/media_kit_libs_android_video}"
sed -i 's/<application/<application android:usesCleartextTraffic="true"/' \
  "$fixture/android/app/src/main/AndroidManifest.xml"
(cd "$fixture" && flutter build apk --debug -t lib/consumer_main.dart \
  --dart-define="LIBMPV_RUNTIME_TEST_URL=http://10.0.2.2:$port/input.wav")
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
libmpv-runtime evidence consumer --path "$LIBMPV_RUNTIME_EVIDENCE" \
  --detail platform=android --detail onlinePlayback=passed --detail filterAfterLoad=passed \
  --detail jniHelper=passed
