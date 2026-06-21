#!/usr/bin/env python3
"""Core module for Odoo Daily News.

Fetch GitHub commits for a given date → summarize with Groq LLM → post to Discord.

Importable from CLI, Flask app, or any other Python code. No sys.exit() here —
functions raise or return result dicts so callers can handle errors themselves.

Example:
    from news import run
    result = run(repo="odoo/odoo", branch="18.0", date="2026-06-20")
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

GITHUB_API = "https://api.github.com"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
USER_AGENT = "odoo-daily-news/2.0"
ICT = ZoneInfo("Asia/Bangkok")

log = logging.getLogger("odoo_news")

DEFAULT_PROMPT_TEMPLATE = """\
You are summarizing {repo}@{branch} commits for {date}.
Total commits: {count}

Each commit: name (first line of message) - PR_URL.

{commits}

Output a Discord digest (max 2000 chars) in this compact format:

📰 **{repo}@{branch} Daily News** — {date}
{count} commits

**Overview:** [1-2 sentences in Thai]

For each commit, use exactly 2 lines with a blank line between commits:

• **[TAG] module**: short commit name — สรุปสั้นๆ (1 ประโยค)
  <PR_URL>

Group by category. Skip empty categories:
🐛 **Bug Fixes**
✨ **New Features**
⚡ **Performance**
🔧 **Refactor**
📝 **Docs/Tests**
⚠️ **Breaking Changes**

**สรุป:** [2-3 sentences in Thai]

If >20 commits, prioritize the most impactful and add "(+X more)" in each category.
"""


@dataclass
class NewsResult:
    """Outcome of a run() call. Always serialisable for JSON history."""

    repo: str
    branch: str
    date: str
    status: str = "error"  # "success" | "error" | "skipped"; default until set
    commit_count: int = 0
    summary: str = ""
    dry_run: bool = False
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(ICT).isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "repo": self.repo,
            "branch": self.branch,
            "date": self.date,
            "commit_count": self.commit_count,
            "summary": self.summary,
            "error": self.error,
            "dry_run": self.dry_run,
        }


class NewsError(Exception):
    """Raised for any recoverable error in the pipeline."""


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def resolve_date(date_str: str = "") -> str:
    """Return a YYYY-MM-DD string in ICT.

    Empty input → yesterday in ICT (so a 00:00 ICT run covers the prior day).
    Validates strict YYYY-MM-DD format.
    """
    if not date_str:
        return (datetime.now(ICT) - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as e:
        raise NewsError(f"DATE must be YYYY-MM-DD, got {date_str!r}: {e}") from e


def _date_window_utc(date_str: str) -> tuple[str, str]:
    """Return (since, until) UTC timestamps covering the full ICT day."""
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ICT)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=0)
    return (
        start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_json(url: str, *, method: str = "GET", headers: dict | None = None,
               payload: dict | None = None, timeout: int = 60, label: str = "") -> Any:
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise NewsError(f"{label or 'HTTP'} error {e.code}: {body[:400]}") from e
    except urllib.error.URLError as e:
        raise NewsError(f"{label or 'HTTP'} network error: {e}") from e


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def extract_pr_url(commit: dict, repo: str) -> str:
    """Best-effort: derive a PR URL from the commit message, else the commit URL."""
    msg = commit.get("commit", {}).get("message", "")
    match = re.search(r"#(\d+)", msg)
    if match:
        return f"https://github.com/{repo}/pull/{match.group(1)}"
    return commit.get("html_url", "")


def fetch_commits(repo: str, branch: str, date_str: str,
                  token: str = "", max_pages: int = 10) -> list[dict]:
    """Fetch all commits on `branch` of `repo` within the ICT day `date_str`."""
    since, until = _date_window_utc(date_str)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    commits: list[dict] = []
    for page in range(1, max_pages + 1):
        url = (
            f"{GITHUB_API}/repos/{repo}/commits"
            f"?sha={branch}&since={since}&until={until}&per_page=100&page={page}"
        )
        data = _http_json(url, headers=headers, timeout=30, label="GitHub")
        if not data:
            break
        commits.extend(data)
        if len(data) < 100:
            break
    return commits


def _format_commit_lines(commits: list[dict], repo: str, limit: int = 60) -> str:
    lines = []
    for c in commits[:limit]:
        msg = c.get("commit", {}).get("message", "").split("\n")[0][:120]
        lines.append(f"- {msg} - {extract_pr_url(c, repo)}")
    if len(commits) > limit:
        lines.append(f"- ... and {len(commits) - limit} more commits")
    return "\n".join(lines)


def build_prompt(commits: list[dict], repo: str, branch: str,
                 date_str: str, custom_prompt: str = "") -> str:
    commits_text = _format_commit_lines(commits, repo)
    template = custom_prompt or DEFAULT_PROMPT_TEMPLATE
    return template.format(
        repo=repo,
        branch=branch,
        date=date_str,
        count=len(commits),
        commits=commits_text,
    )


def summarize(commits: list[dict], repo: str, branch: str, date_str: str,
              api_key: str, model: str, custom_prompt: str = "") -> str:
    if not commits:
        return f"_ไม่มี commit ในวันที่ {date_str} ({repo}@{branch})_"

    prompt = build_prompt(commits, repo, branch, date_str, custom_prompt)
    result = _http_json(
        GROQ_API,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2000,
            "temperature": 0.3,
        },
        timeout=90,
        label="Groq",
    )
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise NewsError(f"Unexpected Groq response shape: {result!r}") from e


def post_discord(webhook: str, content: str) -> int:
    """Post content to a Discord incoming webhook. Returns HTTP status."""
    result = _http_json(
        webhook,
        method="POST",
        payload={"content": content[:2000]},
        timeout=30,
        label="Discord",
    )
    # Discord returns 204 No Content with empty body → _http_json returns None.
    # Anything not raising is success here.
    return 204


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(
    *,
    repo: str,
    branch: str,
    date: str = "",
    groq_api_key: str = "",
    discord_webhook: str = "",
    github_token: str = "",
    model: str = "llama-3.3-70b-versatile",
    custom_prompt: str = "",
    dry_run: bool = False,
) -> NewsResult:
    """Run the full pipeline. Always returns a NewsResult, never sys.exit().

    date: "" → yesterday in ICT.
    dry_run: fetch commits + (optionally) summarise, but never post to Discord.
    """
    result = NewsResult(repo=repo, branch=branch, date=date or "(yesterday)", dry_run=dry_run)

    try:
        resolved = resolve_date(date)
        result.date = resolved
        log.info("[1/3] Fetching commits for %s@%s on %s", repo, branch, resolved)
        commits = fetch_commits(repo, branch, resolved, github_token)
        result.commit_count = len(commits)
        log.info("      Found %d commits", len(commits))

        if dry_run:
            result.summary = _format_commit_lines(commits, repo)
            result.status = "success"
            return result

        if not commits:
            # Nothing to summarise — still post a short note so the channel knows.
            summary = f"_ไม่มี commit ในวันที่ {resolved} ({repo}@{branch})_"
        else:
            if not groq_api_key:
                raise NewsError("GROQ_API_KEY not set")
            log.info("[2/3] Summarising with Groq (%s)...", model)
            summary = summarize(commits, repo, branch, resolved,
                                groq_api_key, model, custom_prompt)

        if not discord_webhook:
            raise NewsError("DISCORD_WEBHOOK_URL not set")
        log.info("[3/3] Posting to Discord...")
        post_discord(discord_webhook, summary)
        result.summary = summary
        result.status = "success"
        return result

    except NewsError as e:
        log.error("Run failed: %s", e)
        result.status = "error"
        result.error = str(e)
        return result
    except Exception as e:  # pragma: no cover - defensive
        log.exception("Unexpected error during run")
        result.status = "error"
        result.error = f"Unexpected error: {e}"
        return result
