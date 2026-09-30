#!/usr/bin/env bash
# Build the single Memory application image from the repository Dockerfile.
set -euo pipefail

if (( $# > 1 )); then
  printf 'Usage: %s [image:tag]\n' "${0##*/}" >&2
  exit 2
fi

command -v docker >/dev/null 2>&1 || {
  printf 'Docker is required to build the image.\n' >&2
  exit 2
}

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
IMAGE="${1:-isekai-memory:local}"

docker build --file "$ROOT/Dockerfile" --tag "$IMAGE" "$ROOT"
docker image inspect --format 'Built {{.RepoTags}} ({{.Id}})' "$IMAGE"
