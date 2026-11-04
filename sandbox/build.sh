#!/usr/bin/env bash
#
# build.sh builds the vora/arc sandbox image with Docker and imports it into
# the rootless containerd image store where the Vora runner resolves images
# (Vora ADR 009). It follows Vora's scripts/build-images.sh (build) and
# scripts/pull-images.sh (import).
#
# Set VORA_ARC_SKIP_IMPORT=1 to build without importing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="vora/arc:latest"
NAMESPACE="${VORA_CONTAINERD_NAMESPACE:-vora}"
SOCK="${VORA_CONTAINERD_ADDRESS:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/containerd/containerd.sock}"

command -v docker >/dev/null 2>&1 || { echo "error: docker not found" >&2; exit 1; }

echo "==> building $TAG"
# --network=host: the default bridge resolves IPv6-only for some CDNs and
# cannot route it, which breaks pip during the build.
docker build --network=host --quiet -t "$TAG" "$HERE" >/dev/null
echo "    built $(docker image inspect --format '{{.Id}}' "$TAG")"

if [[ "${VORA_ARC_SKIP_IMPORT:-}" == "1" ]]; then
  exit 0
fi

command -v ctr >/dev/null 2>&1 || { echo "error: ctr not found" >&2; exit 1; }
if [ ! -S "$SOCK" ]; then
  echo "error: containerd socket not found at $SOCK (run Vora's scripts/setup-containerd.sh)" >&2
  exit 1
fi
CTR=(ctr --address "$SOCK" --namespace "$NAMESPACE")

echo "==> importing $TAG into containerd ($NAMESPACE)"
tmp="$(mktemp -t vora-arc-image-XXXXXX.tar)"
trap 'rm -f "$tmp"' EXIT
docker save "$TAG" -o "$tmp"
"${CTR[@]}" images import "$tmp" >/dev/null
echo "    imported $TAG"
