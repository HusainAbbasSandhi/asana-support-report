"""CLI: fetch support-raised tasks + comments, build a report, post it (or print it with --dry-run)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from digest_bot.asana_client import AsanaError, fetch_open_tasks, fetch_stories
from digest_bot.config import load_config
from digest_bot.digest import PROJECTS, build_daily, build_stalled, escape, monospace_fallback
from digest_bot.metrics import daily_report, stalled_report
from digest_bot.models import comments_from_stories, from_asana, raised_by
from digest_bot.slack_client import SlackError, post_message

REPORTS = ("daily", "stalled")
STORY_WORKERS = 6  # parallel comment fetches; well under Asana's concurrency limits


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _label(name: str | None, email: str | None) -> str:
    """Assignee group heading: a bold name, never an @mention (the leads follow up themselves)."""
    return f"*{escape(name)}*" if name else "*Unassigned*"


def _post(channel: str, payload: dict, token: str) -> str:
    try:
        return post_message(channel, payload, token)
    except SlackError as exc:
        if exc.code != "invalid_blocks":
            raise
        return post_message(channel, monospace_fallback(payload), token)


def run(report: str = "daily", dry_run: bool = False, config_path: str = "config.yaml",
        now: datetime | None = None, test: bool = False) -> int:
    asana_token = os.environ.get("ASANA_TOKEN")
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    if not asana_token:
        _err("ASANA_TOKEN is not set")
        return 2
    if not dry_run and not slack_token:
        _err("SLACK_BOT_TOKEN is not set (use --dry-run to preview without posting)")
        return 2

    config = load_config(config_path)
    now = now or datetime.now(timezone.utc)
    team = config["asana"].get("support_team") or {}
    session = requests.Session()  # one connection pool for every Asana call
    try:
        by_gid: dict[str, object] = {}
        project_of: dict[str, str] = {}
        for key, _, _ in PROJECTS:  # Bug Tracking first, so a task in both projects counts there once
            gid = config["asana"][key]
            for t in raised_by([from_asana(r, gid) for r in fetch_open_tasks(gid, asana_token, session=session)], team):
                if t.gid not in by_gid:
                    by_gid[t.gid] = t
                    project_of[t.gid] = key
        tasks = list(by_gid.values())
        with ThreadPoolExecutor(max_workers=STORY_WORKERS) as pool:
            stories = pool.map(lambda t: fetch_stories(t.gid, asana_token, session=session), tasks)
            comments = {t.gid: comments_from_stories(s) for t, s in zip(tasks, stories)}
        tag = _label
        split = {key: [t for t in tasks if project_of[t.gid] == key] for key, _, _ in PROJECTS}
        if report == "stalled":
            payload = build_stalled({k: stalled_report(ts, comments, team, now) for k, ts in split.items()},
                                    config, now, tag)
        else:
            payload = build_daily({k: daily_report(ts, comments, team, now) for k, ts in split.items()},
                                  config, now, tag)
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        channel = config["slack"]["test_channel"] if test else config["slack"]["channel"]
        ts = _post(channel, payload, slack_token)
    except (AsanaError, SlackError) as exc:
        _err(str(exc))
        return 1
    print(f"Posted {report} ts={ts}")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Post an Asana tech requests report to Slack.")
    parser.add_argument("--report", choices=REPORTS, default="daily")
    parser.add_argument("--dry-run", action="store_true", help="print the Slack payload instead of posting")
    parser.add_argument("--test", action="store_true", help="post to slack.test_channel instead of the real channel")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    sys.exit(run(report=args.report, dry_run=args.dry_run, config_path=args.config, test=args.test))


if __name__ == "__main__":
    main()
