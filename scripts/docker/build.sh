#!/bin/sh
# Builds both container images:
#   controlplane:latest  — persistent-host / Render image (Dockerfile)
#   controlplane:vercel  — Vercel image (Dockerfile.vercel)
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

docker build -f Dockerfile -t controlplane:latest .
echo "built controlplane:latest"

docker build -f Dockerfile.vercel -t controlplane:vercel .
echo "built controlplane:vercel"

echo
echo "Run locally (single container):  ./scripts/docker/run-local.sh"
echo "Run full platform (+ DataHub):   ./scripts/docker/stack.sh up"
echo "Deploy Render:                   ./scripts/render/deploy.sh"
echo "Deploy Vercel:                   ./scripts/vercel/deploy.sh"
