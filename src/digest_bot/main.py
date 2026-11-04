"""CLI: fetch open tasks, build the digest, post it (or print it with --dry-run)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from digest_bot.asana_client import AsanaError, fetch_open_tasks
from digest_bot.config import load_config
from digest_bot.digest import build_digest
from digest_bot.models import from_asana
from digest_bot.slack_client import SlackError, post_message


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def run(dry_run: bool, config_path: str = "config.yaml", now: datetime | None = None) -> int:
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
    bug_gid = config["asana"]["bug_tracking"]
    req_gid = config["asana"]["requests_to_tech"]
    try:
        bugs = [from_asana(r, bug_gid) for r in fetch_open_tasks(bug_gid, asana_token)]
        reqs = [from_asana(r, req_gid) for r in fetch_open_tasks(req_gid, asana_token)]
        payload = build_digest(bugs, reqs, config, now)
        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        ts = post_message(config["slack"]["channel"], payload, slack_token)
    except (AsanaError, SlackError) as exc:
        _err(str(exc))
        return 1
    print(f"Posted ts={ts}")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # emoji on Windows consoles
    parser = argparse.ArgumentParser(description="Post the daily Asana tech requests digest to Slack.")
    parser.add_argument("--dry-run", action="store_true", help="print the Slack payload instead of posting")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run, config_path=args.config))


if __name__ == "__main__":
    main()
