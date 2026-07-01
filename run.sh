#!/usr/bin/env bash
# Convenience wrapper for the Dockerized CLI. Passes all args straight through:
#
#   ./run.sh ingest samples/acme-2026-01-15.json samples/acme-2026-04-20.json
#   ./run.sh diff
#   ./run.sh timeline "Acme Robotics"
#   ./run.sh graph
#
# The store (chronicle.db) and rendered graphs (output/) persist on the host.
set -euo pipefail

mkdir -p output

docker compose build
docker compose run --rm chronicle "$@"
