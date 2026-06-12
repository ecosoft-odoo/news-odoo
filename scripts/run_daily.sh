#!/usr/bin/env bash
set -e
cd /path/to/daily-news
set -a
source .env
set +a
python3 scripts/fetch_and_post.py >> logs/daily.log 2>&1
