# Odoo Daily News

Fetch GitHub commits → summarize with Groq LLM → post to Discord webhook.
Includes a Flask web UI for config + manual run + auto-schedule.

## Quick Start (Local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with real GROQ_API_KEY, DISCORD_WEBHOOK_URL
python3 app.py
# open http://localhost:5000
```

## Production (Server with systemd)

```bash
# 1. setup
cd /srv/daily-news  # or wherever
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # fill in GROQ_API_KEY, DISCORD_WEBHOOK_URL

# 2. install systemd service
sudo cp scripts/daily-news-web.service /etc/systemd/system/
sudo sed -i 's|/path/to/daily-news|/srv/daily-news|g' /etc/systemd/system/daily-news-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now daily-news-web
sudo systemctl status daily-news-web

# 3. logs
journalctl -u daily-news-web -f
```

## Auto Schedule

The Flask app uses **APScheduler** to run the job in-process.
Configure via the web UI (`⏰ Auto Schedule` section) — no crontab needed.

Default: every day at **00:00 Asia/Bangkok**.

## Manual Run

Use the web UI (`▶️ Manual Run` section) to run with a specific date.

## Required GitHub Secrets (for GitHub Actions only)

If you also want GitHub Actions to run the cron (optional, no need if using systemd):

- `GROQ_API_KEY`
- `DISCORD_WEBHOOK_URL`
- `GITHUB_TOKEN` (auto-provided)

Set at: `Settings → Secrets and variables → Actions`
