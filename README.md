# Odoo Daily News

Fetch GitHub commits → summarize with Groq LLM → post to Discord.

**Zero dependencies.** Runs entirely on GitHub Actions — no server, no database, no build step.

## Setup (2 minutes)

### 1. Fork or push this repo to GitHub

### 2. Add secrets

`Settings → Secrets and variables → Actions → New repository secret`

| Name | Required | Where to get |
|---|---|---|
| `GROQ_API_KEY` | ✅ | https://console.groq.com/keys |
| `DISCORD_WEBHOOK_URL` | ✅ | Discord → Channel Settings → Integrations → Webhooks → New |

> `GITHUB_TOKEN` is auto-provided by GitHub (raises API rate limit 60 → 5000 req/hr).

### 3. Run it

Go to **Actions → Odoo Daily News → Run workflow**

- **First time:** tick `dry_run` to test without posting to Discord
- **After that:** leave unticked → posts daily at 00:00 ICT automatically

## Configure

### Change repo / branch / schedule

Edit `.github/workflows/daily-news.yml`:

```yaml
# Change schedule time (cron UTC — 17:00 UTC = 00:00 ICT)
schedule:
  - cron: '0 17 * * *'

# Subscribe to more repos — edit the TARGETS line:
TARGETS='[{"repo":"odoo/odoo","branch":"18.0"}]'
```

### Override per manual run

When clicking **Run workflow** in GitHub Actions:

| Input | Description | Default |
|---|---|---|
| `date` | `YYYY-MM-DD` — empty = yesterday ICT | yesterday |
| `repo` | Override with single repo (`owner/name`) | matrix repos |
| `branch` | Branch for single-repo override | `18.0` |
| `dry_run` | Fetch only, no Groq/Discord | off |

## Test locally (optional)

No install needed — Python 3.9+ stdlib only.

```bash
# Dry-run (no API keys needed)
python3 scripts/fetch_and_post.py --dry-run
python3 scripts/fetch_and_post.py 2026-06-12 --dry-run
python3 scripts/fetch_and_post.py --repo OCA/l10n-thailand --branch 18.0 --dry-run

# Full run (needs GROQ_API_KEY + DISCORD_WEBHOOK_URL in env)
GROQ_API_KEY=gsk_... DISCORD_WEBHOOK_URL=https://... python3 scripts/fetch_and_post.py
```

## Project structure

```
odoo-daily-news/
├── .env.example                 # secrets template (copy → .env for local)
├── .gitignore
├── news.py                      # core logic: fetch → summarize → post
├── scripts/
│   └── fetch_and_post.py        # CLI wrapper (for local testing)
└── .github/
    └── workflows/
        └── daily-news.yml       # GitHub Actions (this is the real runner)
```

## How it works

1. **GitHub Actions** triggers daily at 00:00 ICT (or manual)
2. **`news.py`** fetches commits from GitHub API for the given date (ICT timezone)
3. **Groq LLM** summarizes commits into a Thai digest
4. **Discord webhook** posts the summary to your channel

All logic lives in `news.py` (~250 lines). No third-party packages.
