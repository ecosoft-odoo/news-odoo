#!/usr/bin/env python3
"""CLI entry point for Odoo Daily News.

Thin wrapper around the `news` module. All flags are optional — env vars and
config are the fallback so this can be driven by GitHub Actions, cron, or
manual invocation.

Usage:
    python scripts/fetch_and_post.py                      # yesterday ICT
    python scripts/fetch_and_post.py 2026-06-20           # specific date
    python scripts/fetch_and_post.py --repo odoo/odoo --branch 18.0
    python scripts/fetch_and_post.py --dry-run            # fetch only, no post
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow `python scripts/fetch_and_post.py` from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news import run  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch GitHub commits → summarize → post to Discord.")
    p.add_argument("date", nargs="?", default="",
                   help="Date YYYY-MM-DD (default: yesterday ICT)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPO", "odoo/odoo"),
                   help="GitHub repo owner/name (env: GITHUB_REPO)")
    p.add_argument("--branch", default=os.environ.get("GITHUB_BRANCH", "18.0"),
                   help="Branch (env: GITHUB_BRANCH)")
    p.add_argument("--model", default=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                   help="Groq model (env: GROQ_MODEL)")
    p.add_argument("--custom-prompt", default=os.environ.get("CUSTOM_PROMPT", ""),
                   help="Override prompt template (env: CUSTOM_PROMPT)")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch + summarise without posting to Discord")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    result = run(
        repo=args.repo,
        branch=args.branch,
        date=args.date,
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        discord_webhook=os.environ.get("DISCORD_WEBHOOK_URL", ""),
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        model=args.model,
        custom_prompt=args.custom_prompt,
        dry_run=args.dry_run,
    )

    # Human-readable summary on stdout (CI logs / Web UI history).
    print(f"\n=== Result: {result.status.upper()} ===")
    print(f"Repo:  {result.repo}@{result.branch}")
    print(f"Date:  {result.date}")
    print(f"Commits: {result.commit_count}")
    if result.dry_run and result.summary:
        print("\n--- commits (dry-run) ---")
        print(result.summary)
    elif result.summary:
        print("\n--- summary preview ---")
        print(result.summary[:500] + ("..." if len(result.summary) > 500 else ""))
    if result.error:
        print(f"\nERROR: {result.error}", file=sys.stderr)

    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
