#!/usr/bin/env python3
import os
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me-in-prod")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.json"
SCRIPT_PATH = BASE_DIR / "scripts" / "fetch_and_post.py"
ENV_FILE = BASE_DIR / ".env"

CONFIG_KEYS = (
    "github_repo", "github_branch", "groq_model", "custom_prompt",
    "schedule_enabled", "schedule_hour", "schedule_minute", "schedule_timezone",
)
DEFAULTS = {
    "github_repo": "odoo/odoo",
    "github_branch": "18.0",
    "groq_model": "llama-3.3-70b-versatile",
    "custom_prompt": "",
    "schedule_enabled": True,
    "schedule_hour": 0,
    "schedule_minute": 0,
    "schedule_timezone": "Asia/Bangkok",
}

history_lock = threading.Lock()
scheduler = BackgroundScheduler(daemon=True)


def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key, value)


def env_status():
    return {
        "groq_api_key": bool(os.environ.get("GROQ_API_KEY")),
        "discord_webhook_url": bool(os.environ.get("DISCORD_WEBHOOK_URL")),
        "github_token": bool(os.environ.get("GITHUB_TOKEN")),
    }


def load_history():
    with history_lock:
        if not HISTORY_FILE.exists():
            return []
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []


def save_history(history):
    with history_lock:
        history = history[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)


def append_history(entry):
    with history_lock:
        history = []
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE) as f:
                    history = json.load(f)
            except (json.JSONDecodeError, OSError):
                history = []
        history.append(entry)
        history = history[-100:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)


def load_config():
    if not CONFIG_FILE.exists():
        return DEFAULTS.copy()
    try:
        with open(CONFIG_FILE) as f:
            stored = json.load(f)
        return {k: stored.get(k, v) for k, v in DEFAULTS.items()}
    except (json.JSONDecodeError, OSError):
        return DEFAULTS.copy()


def save_config(cfg):
    clean = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(clean, f, indent=2)


def cleanup_legacy_secrets():
    if not CONFIG_FILE.exists():
        return
    try:
        with open(CONFIG_FILE) as f:
            stored = json.load(f)
        if any(k not in CONFIG_KEYS for k in stored):
            clean = {k: v for k, v in stored.items() if k in CONFIG_KEYS}
            with open(CONFIG_FILE, "w") as f:
                json.dump(clean, f, indent=2)
    except (json.JSONDecodeError, OSError):
        pass


def run_script(cfg, date_str=""):
    env = os.environ.copy()
    env.update({
        "GITHUB_REPO": cfg["github_repo"],
        "GITHUB_BRANCH": cfg["github_branch"],
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", ""),
        "GROQ_MODEL": cfg["groq_model"],
        "DISCORD_WEBHOOK_URL": os.environ.get("DISCORD_WEBHOOK_URL", ""),
        "DATE": date_str,
    })
    if cfg.get("custom_prompt"):
        env["CUSTOM_PROMPT"] = cfg["custom_prompt"]

    start = datetime.now()
    try:
        result = subprocess.run(
            ["python3", str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(BASE_DIR),
        )
        return {
            "timestamp": start.isoformat(timespec="seconds"),
            "status": "success" if result.returncode == 0 else "error",
            "stdout": (result.stdout or "")[-1500:],
            "stderr": (result.stderr or "")[-1500:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "timestamp": start.isoformat(timespec="seconds"),
            "status": "error",
            "stdout": "",
            "stderr": "Script timed out (300s)",
            "returncode": -1,
        }
    except Exception as e:
        return {
            "timestamp": start.isoformat(timespec="seconds"),
            "status": "error",
            "stdout": "",
            "stderr": f"Failed to run: {e}",
            "returncode": -1,
        }


@app.route("/")
def index():
    cfg = load_config()
    return render_template(
        "index.html",
        config=cfg,
        env=env_status(),
        history=list(reversed(load_history()[-10:])),
        next_run=next_run_time(cfg),
    )


@app.route("/save", methods=["POST"])
def save():
    cfg = load_config()
    for key in CONFIG_KEYS:
        if key in request.form:
            cfg[key] = request.form[key].strip()
    save_config(cfg)
    flash("Config saved ✓", "success")
    return redirect(url_for("index"))


@app.route("/run", methods=["POST"])
def run():
    cfg = load_config()
    if not os.environ.get("GROQ_API_KEY"):
        flash("GROQ_API_KEY ไม่ได้ตั้งใน .env", "error")
        return redirect(url_for("index"))
    if not os.environ.get("DISCORD_WEBHOOK_URL"):
        flash("DISCORD_WEBHOOK_URL ไม่ได้ตั้งใน .env", "error")
        return redirect(url_for("index"))

    date_str = request.form.get("date", "").strip()
    result = run_script(cfg, date_str)
    append_history(result)

    if result["status"] == "success":
        flash("Run สำเร็จ — ส่งเข้า Discord แล้ว", "success")
    else:
        flash(f"Run ล้มเหลว: {result['stderr'][:200]}", "error")
    return redirect(url_for("index"))


@app.route("/history/clear", methods=["POST"])
def clear_history():
    save_history([])
    flash("ลบ history แล้ว", "success")
    return redirect(url_for("index"))


SCHEDULE_JOB_ID = "daily_news"


def scheduled_run():
    cfg = load_config()
    if not (os.environ.get("GROQ_API_KEY") and os.environ.get("DISCORD_WEBHOOK_URL")):
        append_history({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": "error",
            "stdout": "",
            "stderr": "Scheduled run skipped — missing GROQ_API_KEY or DISCORD_WEBHOOK_URL",
            "returncode": -1,
        })
        return
    result = run_script(cfg, "")
    append_history(result)


def scheduler_listener(event):
    if event.exception:
        append_history({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": "error",
            "stdout": "",
            "stderr": f"Scheduler error: {event.exception}",
            "returncode": -1,
        })


def apply_schedule(cfg):
    scheduler.remove_job(SCHEDULE_JOB_ID) if scheduler.get_job(SCHEDULE_JOB_ID) else None
    if not cfg.get("schedule_enabled", True):
        return
    try:
        hour = int(cfg.get("schedule_hour", 0))
        minute = int(cfg.get("schedule_minute", 0))
    except (TypeError, ValueError):
        hour, minute = 0, 0
    tz = cfg.get("schedule_timezone", "Asia/Bangkok") or "Asia/Bangkok"
    scheduler.add_job(
        scheduled_run,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id=SCHEDULE_JOB_ID,
        replace_existing=True,
        misfire_grace_time=300,
    )


def next_run_time(cfg):
    if not cfg.get("schedule_enabled", True):
        return None
    job = scheduler.get_job(SCHEDULE_JOB_ID)
    return job.next_run_time.isoformat(timespec="seconds") if job else None


@app.route("/schedule", methods=["POST"])
def save_schedule():
    cfg = load_config()
    cfg["schedule_enabled"] = request.form.get("schedule_enabled") == "on"
    try:
        cfg["schedule_hour"] = max(0, min(23, int(request.form.get("schedule_hour", 0))))
        cfg["schedule_minute"] = max(0, min(59, int(request.form.get("schedule_minute", 0))))
    except (TypeError, ValueError):
        cfg["schedule_hour"] = 0
        cfg["schedule_minute"] = 0
    cfg["schedule_timezone"] = request.form.get("schedule_timezone", "Asia/Bangkok").strip() or "Asia/Bangkok"
    save_config(cfg)
    apply_schedule(cfg)
    flash(
        f"Schedule updated ✓ — รันทุกวัน {cfg['schedule_hour']:02d}:{cfg['schedule_minute']:02d} {cfg['schedule_timezone']}"
        if cfg["schedule_enabled"] else "Schedule ปิดแล้ว",
        "success",
    )
    return redirect(url_for("index"))


if __name__ == "__main__":
    load_env_file(ENV_FILE)
    cleanup_legacy_secrets()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    scheduler.add_listener(scheduler_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    apply_schedule(load_config())
    scheduler.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
