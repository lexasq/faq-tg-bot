#!/usr/bin/env bash
# Idempotent deploy: pull latest, rebuild, restart, prune old images.
# Run from anywhere: cd's to the repo root itself.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> git pull"
git pull --ff-only

echo "==> docker compose build"
docker compose -f docker-compose.prod.yml build

echo "==> docker compose up -d"
docker compose -f docker-compose.prod.yml up -d

echo "==> pruning dangling images"
docker image prune -f

echo "==> done"
docker compose -f docker-compose.prod.yml ps
