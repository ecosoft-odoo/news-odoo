# Odoo Daily News

Fetch GitHub commits → post commit name + PR link to Discord.

**Zero dependencies, zero LLM.** Runs entirely on GitHub Actions — no server, no database, no build step, no API keys for summarisation.

## Setup (2 minutes)

### 1. Fork or push this repo to GitHub

### 2. Add secrets

`Settings → Secrets and variables → Actions → New repository secret`

| Name | Required | Where to get |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | ✅ | Discord → Channel Settings → Integrations → Webhooks → New |

> `GITHUB_TOKEN` is auto-provided by GitHub (raises API rate limit 60 → 5000 req/hr). No Groq / LLM key needed.

### 3. Run it

Go to **Actions → Odoo Daily News → Run workflow**

- **First time:** tick `dry_run` to test without posting to Discord
- **After that:** leave unticked → posts daily at 00:00 UTC automatically

## Output format

Each run posts a plain-text message (no embeds) listing every commit as one line:

```
📰 **odoo/odoo Daily News** — 3 commit(s)

• [FIX] account: fix rounding error on invoice — https://github.com/odoo/odoo/pull/12345
• [IMP] sale: improve quotation performance — https://github.com/odoo/odoo/pull/12346
• [REF] web: simplify calendar widget — https://github.com/odoo/odoo/pull/12347
```

The link is the PR URL (derived from `#123` in the commit message) or the commit URL if no PR is referenced.

## Configure

### Change repo / branch / schedule

Edit `.github/workflows/daily-news.yml`:

```yaml
# Change schedule time (cron UTC — 20:00 UTC = 03:00 ICT)
schedule:
  - cron: '0 20 * * *'

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
| `dry_run` | Fetch only, no Discord post | off |

## Test locally (optional)

No install needed — Python 3.9+ stdlib only.

```bash
# Dry-run (no API keys needed)
python3 scripts/fetch_and_post.py --dry-run
python3 scripts/fetch_and_post.py 2026-06-12 --dry-run
python3 scripts/fetch_and_post.py --repo OCA/l10n-thailand --branch 18.0 --dry-run

# Full run (needs DISCORD_WEBHOOK_URL in env)
DISCORD_WEBHOOK_URL=https://... python3 scripts/fetch_and_post.py
```

## Project structure

```
odoo-daily-news/
├── .env.example                 # secrets template (copy → .env for local)
├── .gitignore
├── news.py                      # core logic: fetch → format → post
├── scripts/
│   └── fetch_and_post.py        # CLI wrapper (for local testing)
└── .github/
    └── workflows/
        └── daily-news.yml       # GitHub Actions (this is the real runner)
```

## How it works

1. **GitHub Actions** triggers daily (or manual)
2. **`news.py`** fetches commits from GitHub API for the given date (ICT timezone)
3. Each commit is formatted as `• <subject> — <PR/commit URL>`
4. **Discord webhook** posts the plain-text list to your channel

All logic lives in `news.py`. No third-party packages, no LLM step.
