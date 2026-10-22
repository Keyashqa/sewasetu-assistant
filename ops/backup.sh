#!/bin/sh
# Nightly Postgres dump of the Sewa Setu database to the VM disk; keeps the newest 7.
# Installed by DEPLOY.md as a root cron job. Usage: ops/backup.sh [repo dir] [backup dir]
set -eu

REPO=${1:-/opt/sewasetu-assistant}
DEST=${2:-/var/backups/sewasetu}
KEEP=7

mkdir -p "$DEST"
cd "$REPO"
out="$DEST/sewasetu-$(date -u +%Y%m%dT%H%M%SZ).dump"

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  pg_dump -U sewasetu -d sewasetu -Fc > "$out.part"
mv "$out.part" "$out"

ls -1t "$DEST"/sewasetu-*.dump | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date -u +%FT%TZ) backup ok: $out ($(du -h "$out" | cut -f1))"
