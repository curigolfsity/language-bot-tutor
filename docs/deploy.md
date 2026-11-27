# Deploying to a cloud server

Runs the whole tutor (Postgres + API + Telegram bot) with Docker on one small Linux server,
so it works while your PC is off. Recommended: **Hetzner Cloud CX22** (2 vCPU, 4 GB RAM,
~€4.5/month), location **Singapore**, image **Ubuntu 24.04**. Any 4 GB VPS works the same way.

> Telegram allows only **one** running copy of a bot. Stop the local one (step 6) as soon as
> the server copy is running, or they will fight over messages.

## 1. Create an SSH key (on your PC, once)
In PowerShell:
```
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub
```
Press Enter at every question. Copy the line that starts with `ssh-ed25519`.

## 2. Create the server
Hetzner Cloud console → **Add Server**: Singapore, Ubuntu 24.04, CX22, paste the SSH key from
step 1, create. Note the server's **IP address**.

## 3. Install Docker on the server
```
ssh root@SERVER_IP
curl -fsSL https://get.docker.com | sh
git clone https://github.com/curigolfsity/language-bot-tutor.git
cd language-bot-tutor
```

## 4. Copy your secrets and data (from your PC, in a second PowerShell window)
Export the local database first:
```
cd D:\spanish-tutor
uv run python scripts/export_db.py
scp .env root@SERVER_IP:/root/language-bot-tutor/.env
scp backups\tutor.dump root@SERVER_IP:/root/language-bot-tutor/backups/tutor.dump
```
(Create the folder first if scp complains: `ssh root@SERVER_IP mkdir -p /root/language-bot-tutor/backups`.)

Then, on the server, add a database password to `.env` (any long random text):
```
echo "DB_PASSWORD=$(openssl rand -hex 24)" >> .env
```
`DATABASE_URL`, `TUTOR_API_URL` and the model folder from `.env` are overridden by
`docker-compose.yml`, so they can stay as they are.

## 5. Start it, with your data
On the server:
```
docker compose up -d db
docker compose exec -T db pg_restore -U tutor -d spanish_tutor --no-owner < backups/tutor.dump
docker compose up -d --build
docker compose ps
docker compose logs -f bot        # Ctrl+C to stop watching
```
The first start downloads the speech model (~460 MB) and takes a few minutes; voice messages
work once the API shows as healthy. Skip the `pg_restore` line to start with an empty database.

## 6. Stop the copy on your PC
```
tutor stop
tutor autostart off
```
Send the bot a message in Telegram: it now answers from the server.

## 7. Daily backups (on the server, once)
```
crontab -e
```
Add this line (backup at 03:30 every night, keeps the last 14):
```
30 3 * * * cd /root/language-bot-tutor && sh scripts/backup.sh >> backups/backup.log 2>&1
```
To copy the latest backup to your PC: `scp root@SERVER_IP:/root/language-bot-tutor/backups/tutor-*.dump .`

## Everyday commands (on the server, in /root/language-bot-tutor)
| What | Command |
|---|---|
| Update after a push to GitHub | `git pull && docker compose up -d --build` |
| Status | `docker compose ps` |
| Logs | `docker compose logs -f api` / `docker compose logs -f bot` |
| Restart | `docker compose restart` |
| Stop everything | `docker compose down` (data is kept in Docker volumes) |
| Usage report | `docker compose exec api python scripts/usage_report.py` |
| Change a setting | edit `.env`, then `docker compose up -d` |

## Notes
- The API is not exposed to the internet; only the bot (inside Docker) talks to it. No ports
  need opening besides SSH.
- Secrets live only in `.env` on the server, never in GitHub.
- Hetzner's firewall: allowing only SSH (port 22) inbound is enough.
