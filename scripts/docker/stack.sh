#!/bin/sh
# Full platform in one command: control-plane (OPA bundled in the image) +
# the DataHub quickstart stack (mysql, opensearch, kafka, datahub-gms,
# datahub-actions, frontend UI).
#
#   ./scripts/docker/stack.sh up        # build + start everything
#   ./scripts/docker/stack.sh down      # stop (add -v to also drop volumes)
#   ./scripts/docker/stack.sh logs      # tail all logs
#   ./scripts/docker/stack.sh ps        # service status
#
# After `up`: console on http://localhost:8080, DataHub UI on
# http://localhost:9002, DataHub GMS on http://localhost:18080.
# Requires ~8 GB of RAM (DataHub: JVM GMS + OpenSearch + Kafka + MySQL).
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

case "${1:-up}" in
  up)
    docker compose up -d --build
    echo
    echo "Console:   http://localhost:8080"
    echo "DataHub:   http://localhost:9002   GMS: http://localhost:18080"
    ;;
  down)
    shift
    docker compose down "$@"
    ;;
  logs)
    shift
    docker compose logs -f --tail=100 "$@"
    ;;
  ps)
    docker compose ps
    ;;
  *)
    echo "usage: $0 {up|down|logs|ps}" >&2
    exit 1
    ;;
esac
