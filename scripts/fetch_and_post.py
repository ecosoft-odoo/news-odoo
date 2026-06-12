#!/usr/bin/env python3
import os
import re
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

GITHUB_API = "https://api.github.com"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
REPO = os.environ.get("GITHUB_REPO", "odoo/odoo")
BRANCH = os.environ.get("GITHUB_BRANCH", "18.0")
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
CUSTOM_PROMPT = os.environ.get("CUSTOM_PROMPT", "")


def extract_pr_url(commit, repo):
    """Extract PR URL from commit message, or return commit URL as fallback."""
    msg = commit["commit"]["message"]
    match = re.search(r'#(\d+)', msg)
    if match:
        return f"https://github.com/{repo}/pull/{match.group(1)}"
    return commit["html_url"]


def http_get(url, headers=None):
    headers = dict(headers or {})
    headers.setdefault("Accept", "application/vnd.github+json")
    headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
    headers.setdefault("User-Agent", "odoo-daily-news/1.0")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"GitHub API error {e.code}: {body[:300]}")


def fetch_commits(date_str, token):
    if not date_str:
        ict = ZoneInfo("Asia/Bangkok")
        yest = datetime.now(ict) - timedelta(days=1)
        start = yest.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yest.replace(hour=23, minute=59, second=59)
        since = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_str = yest.strftime("%Y-%m-%d")
    else:
        since = f"{date_str}T00:00:00Z"
        until = f"{date_str}T23:59:59Z"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    commits = []
    for page in range(1, 11):
        url = (
            f"{GITHUB_API}/repos/{REPO}/commits"
            f"?sha={BRANCH}&since={since}&until={until}&per_page=100&page={page}"
        )
        data = http_get(url, headers)
        if not data:
            break
        commits.extend(data)
        if len(data) < 100:
            break

    return date_str, commits


def build_prompt(commits, date_str):
    lines = []
    for c in commits:
        msg = c["commit"]["message"].split("\n")[0][:120]
        pr_url = extract_pr_url(c, REPO)
        lines.append(f"- {msg} - {pr_url}")
    commits_text = "\n".join(lines)

    if CUSTOM_PROMPT:
        return CUSTOM_PROMPT.format(
            repo=REPO,
            branch=BRANCH,
            date=date_str,
            count=len(commits),
            commits=commits_text,
        )

    return (
        f"You are summarizing {REPO}@{BRANCH} commits for {date_str}.\n"
        f"Total commits: {len(commits)}\n"
        "\n"
        "Each commit: name (first line of message) - PR_URL.\n"
        "\n"
        f"{commits_text}\n"
        "\n"
        "Output a Discord digest (max 2000 chars) in this compact format:\n"
        "\n"
        f"📰 **{REPO}@{BRANCH} Daily News** — {date_str}\n"
        f"{len(commits)} commits\n"
        "\n"
        "**Overview:** [1-2 sentences in Thai]\n"
        "\n"
"[For each commit, use exactly 2 lines with a blank line between commits:]\n"
"\n"
"• **[TAG] module**: short commit name — สรุปสั้นๆ (1 ประโยค)\n"
"  <PR_URL>\n"
"\n"
        "[Group by category. Skip empty categories:]\n"
        "🐛 **Bug Fixes**\n"
        "✨ **New Features**\n"
        "⚡ **Performance**\n"
        "🔧 **Refactor**\n"
        "📝 **Docs/Tests**\n"
        "⚠️ **Breaking Changes**\n"
        "\n"
        "**สรุป:** [2-3 sentences in Thai]\n"
        "\n"
        'If >20 commits, prioritize the most impactful and add "(+X more)" in each category.\n'
    )


def summarize(commits, date_str, api_key):
    if not commits:
        return f"_ไม่มี commit ในวันที่ {date_str}_"

    prompt = build_prompt(commits, date_str)
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        GROQ_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "odoo-daily-news/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"Groq API error {e.code}: {body[:300]}")


def post_discord(webhook, content):
    payload = {
        "content": content[:2000],
        "flags": 4,
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "odoo-daily-news/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    dry_run = "--dry-run" in flags

    github_token = os.environ.get("GITHUB_TOKEN", "")
    groq_key = os.environ.get("GROQ_API_KEY")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    date_str = os.environ.get("DATE", "").strip()
    if not date_str and args:
        date_str = args[0]

    if date_str:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            sys.exit(f"DATE must be YYYY-MM-DD format, got: {date_str!r} ({e})")

    if not dry_run:
        if not groq_key:
            sys.exit("GROQ_API_KEY not set")
        if not discord_webhook:
            sys.exit("DISCORD_WEBHOOK_URL not set")

    print(f"[1/3] Fetching commits for {REPO}@{BRANCH} on {date_str or 'yesterday'}...")
    date_str, commits = fetch_commits(date_str, github_token)
    print(f"      Found {len(commits)} commits")

    if dry_run:
        print(f"\nDate: {date_str}")
        print(f"Total commits: {len(commits)}\n")
        for c in commits[:20]:
            msg = c["commit"]["message"].split("\n")[0]
            pr_url = extract_pr_url(c, REPO)
            print(f"  {msg} - {pr_url}")
        return

    print(f"[2/3] Summarizing with Groq ({MODEL})...")
    summary = summarize(commits, date_str, groq_key)

    print("[3/3] Posting to Discord...")
    post_discord(discord_webhook, summary)
    print("Done")


if __name__ == "__main__":
    main()
