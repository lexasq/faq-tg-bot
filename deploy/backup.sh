#!/usr/bin/env bash
# Nightly cron entry point — see README "Deploying to a DigitalOcean
# droplet" for the crontab line. Runs scripts/backup.py inside the
# already-running bot container so it reuses the same Firestore creds.
set -euo pipefail

cd "$(dirname "$0")/.."

docker compose -f docker-compose.prod.yml exec -T bot python scripts/backup.py /opt/faq-bot/backups
