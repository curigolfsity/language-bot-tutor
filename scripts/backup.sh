#!/bin/sh
# Daily database backup on the server (keeps the last 14). Install with:
#   crontab -e   and add:   30 3 * * * cd /root/language-bot-tutor && sh scripts/backup.sh
set -e
mkdir -p backups
name="backups/tutor-$(date +%Y%m%d-%H%M).dump"
docker compose exec -T db pg_dump -U tutor -d spanish_tutor -Fc > "$name"
ls -1t backups/tutor-*.dump | tail -n +15 | xargs -r rm --
echo "backup: $name"
