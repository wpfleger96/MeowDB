#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="meowdb_backup.tar.gz"
FLY_APP="meowdb"
REMOTE_HOST="${MEOWDB_REMOTE_HOST:?Set MEOWDB_REMOTE_HOST to the LXC container IP or hostname}"
REMOTE_DATA_DIR="${MEOWDB_REMOTE_DATA_DIR:-/opt/meowdb/data}"

echo "=== Step 1: Checkpoint SQLite WAL ==="
fly ssh console -a "$FLY_APP" -C "python -c \"import sqlite3; c = sqlite3.connect('/data/meowdb.sqlite'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close(); print('WAL checkpoint complete')\""

echo "=== Step 2: Tar and download data from Fly.io ==="
fly ssh console -a "$FLY_APP" -C "tar czf - -C / data/meowdb.sqlite data/audio data/photos" > "$BACKUP_FILE"
echo "Downloaded $(du -h "$BACKUP_FILE" | cut -f1) to $BACKUP_FILE"

echo "=== Step 3: Copy archive to LXC container ==="
scp -i ~/.ssh/id_rsa_homelab "$BACKUP_FILE" "root@${REMOTE_HOST}:/tmp/${BACKUP_FILE}"

echo "=== Step 4: Extract on LXC container ==="
ssh -i ~/.ssh/id_rsa_homelab "root@${REMOTE_HOST}" \
  "mkdir -p ${REMOTE_DATA_DIR} && tar xzf /tmp/${BACKUP_FILE} -C ${REMOTE_DATA_DIR} --strip-components=1 && rm /tmp/${BACKUP_FILE}"

echo "=== Step 5: Verify ==="
DB_COUNT=$(ssh -i ~/.ssh/id_rsa_homelab "root@${REMOTE_HOST}" \
  "docker exec meowdb python -c \"import sqlite3; c = sqlite3.connect('/data/meowdb.sqlite'); print(c.execute('SELECT COUNT(*) FROM meows').fetchone()[0]); c.close()\"")
MP3_COUNT=$(ssh -i ~/.ssh/id_rsa_homelab "root@${REMOTE_HOST}" \
  "ls -1 ${REMOTE_DATA_DIR}/audio/mp3/ | wc -l")
PHOTO_COUNT=$(ssh -i ~/.ssh/id_rsa_homelab "root@${REMOTE_HOST}" \
  "ls -1 ${REMOTE_DATA_DIR}/photos/ 2>/dev/null | wc -l")

echo "  DB meow rows:  $DB_COUNT"
echo "  MP3 files:     $MP3_COUNT"
echo "  Photo files:   $PHOTO_COUNT"

if [ "$DB_COUNT" -eq "$MP3_COUNT" ]; then
  echo "  Counts match!"
else
  echo "  WARNING: DB row count ($DB_COUNT) != MP3 file count ($MP3_COUNT)"
fi

echo ""
echo "Done. Data is at ${REMOTE_HOST}:${REMOTE_DATA_DIR}/"
echo "Start the stack: ssh root@${REMOTE_HOST} 'cd /opt/meowdb && docker compose up -d'"
