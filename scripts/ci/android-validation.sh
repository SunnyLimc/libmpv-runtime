#!/usr/bin/env bash
set -euo pipefail

: "${PLAN:?required}"

uv run libmpv-runtime probe run \
  --plan "$PLAN" \
  --target android \
  --stage build/stage/android \
  --work work/probe-android \
  --report build/reports/behavior/android.json

for profile in minimum current; do
  uv run libmpv-runtime consumer run \
    --plan "$PLAN" \
    --group android \
    --profile "$profile" \
    --work "work/consumer-android-$profile" \
    --artifact android=validated/libmpv-runtime-android.zip \
    --report "android=build/reports/consumer/$profile/android.json"
done
