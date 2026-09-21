#!/usr/bin/env sh
set -eu
STAMP="$(date +%Y%m%d-%H%M%S)"
docker compose exec -T relaydesk tar czf - -C /data . > "relaydesk-backup-$STAMP.tar.gz"
echo "Backup created: relaydesk-backup-$STAMP.tar.gz"
