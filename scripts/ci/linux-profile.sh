#!/usr/bin/env bash
set -euo pipefail

: "${PROFILE:?required}"
: "${PYTHON_VERSION:?required}"

case "$PROFILE" in
  debian-12|debian-13|ubuntu-24.04)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates gcc libc6-dev libmpv2
    rm -rf /var/lib/apt/lists/*
    ;;
  fedora)
    dnf install -y ca-certificates gcc glibc-devel mpv-libs
    dnf clean all
    ;;
  arch)
    pacman -Syu --noconfirm ca-certificates gcc glibc mpv
    pacman -Scc --noconfirm
    ;;
  *)
    echo "unsupported Linux profile: $PROFILE" >&2
    exit 2
    ;;
esac

uv venv /tmp/libmpv-runtime-venv --python "$PYTHON_VERSION"
uv pip install --python /tmp/libmpv-runtime-venv/bin/python --no-cache -e /workspace
export PATH="/tmp/libmpv-runtime-venv/bin:$PATH"
plan=/workspace/work/plan/validation-plan.json
mkdir -p /workspace/build/reports/linux /workspace/validated
libmpv-runtime linux validate --plan "$plan" --profile "$PROFILE" \
  --report "/workspace/build/reports/linux/$PROFILE-structure.json"
libmpv-runtime probe run --plan "$plan" --target linux-system \
  --work "/workspace/work/probe-linux-$PROFILE" \
  --report "/workspace/build/reports/linux/$PROFILE-behavior.json"
libmpv-runtime evidence seal-linux --plan "$plan" --profile "$PROFILE" \
  --structure "/workspace/build/reports/linux/$PROFILE-structure.json" \
  --behavior "/workspace/build/reports/linux/$PROFILE-behavior.json" \
  --output "/workspace/validated/linux-system-$PROFILE.json"
