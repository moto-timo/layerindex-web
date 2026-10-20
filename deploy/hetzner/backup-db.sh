#!/bin/sh
# Dump the layerindex database to a gzipped file. Run from the repo root.
#
#   deploy/hetzner/backup-db.sh /var/backups/layerindex
#
# The git clone cache (layersmeta) is deliberately NOT backed up -- it is fully
# reconstructible by re-running the update task, and it is the bulk of the disk.
#
# Suggested cron (host, daily 03:17 UTC):
#   17 3 * * * cd /srv/layerindex-web && deploy/hetzner/backup-db.sh /var/backups/layerindex >>/var/log/layerindex-backup.log 2>&1
#
# Note: Hetzner's automatic backups and snapshots do NOT include attached
# Volumes. If anything here lives on a Volume, copy the dumps off-box as well
# (Hetzner Storage Box / Object Storage).
#
# SPDX-License-Identifier: MIT
set -eu

DEST="${1:-/var/backups/layerindex}"
KEEP="${KEEP:-14}"
COMPOSE="docker compose -f deploy/hetzner/docker-compose.yml --env-file .env"

mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DEST/layersdb-$STAMP.sql.gz"

# shellcheck disable=SC2086
$COMPOSE exec -T layersdb sh -c \
	'exec mariadb-dump --single-transaction --quick --max-allowed-packet=512M \
	  -u root -p"$MARIADB_ROOT_PASSWORD" layersdb' \
	| gzip -9 > "$OUT.tmp"

mv "$OUT.tmp" "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Prune
ls -1t "$DEST"/layersdb-*.sql.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
	echo "pruning $old"
	rm -f "$old"
done
