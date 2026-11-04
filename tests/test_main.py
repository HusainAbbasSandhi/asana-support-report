import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from digest_bot import main as main_mod
from digest_bot.asana_client import AsanaError
from digest_bot.slack_client import SlackError

FIX = Path(__file__).parent / "fixtures"
CONFIG = str(Path(__file__).parent.parent / "config.yaml")
NOW = datetime(2026, 11, 5, 4, 30, tzinfo=timezone.utc)
BUG_GID = "1202029361021711"


def _bug():
    raw = json.loads((FIX / "bug_task.json").read_text(encoding="utf-8"))  # created by Haydar (support), 2026-11-03
    raw["created_at"] = (NOW - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    raw["assignee"]["email"] = "joel.gnan@reelo.io"
    return raw


@pytest.fixture
def stub_asana(monkeypatch):
    bug = _bug()
    outsider = {**bug, "gid": "333", "name": "Raised by tech", "created_by": {"gid": "999"}}
    story_calls = []

    def fake_tasks(gid, token):
        return [bug, outsider] if gid == BUG_GID else []

    def fake_stories(task_gid, token):
        story_calls.append(task_gid)
        return []

    monkeypatch.setattr(main_mod, "fetch_open_tasks", fake_tasks)
    monkeypatch.setattr(main_mod, "fetch_stories", fake_stories)
    return story_calls


@pytest.fixture
def no_slack(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Slack must not be called")

    monkeypatch.setattr(main_mod, "post_message", boom)
    monkeypatch.setattr(main_mod, "lookup_user_id", boom)


def test_daily_dry_run_only_support_tasks_no_slack(monkeypatch, capsys, stub_asana, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(report="daily", dry_run=True, config_path=CONFIG, now=NOW) == 0
    out = capsys.readouterr().out
    assert "Raised by tech" not in out
    assert '"Open tickets raised by support"' in out
    assert stub_asana == ["111"]  # comments fetched only for in-scope tasks


def test_daily_posts_with_email_tag(monkeypatch, capsys, stub_asana):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    posted = []
    monkeypatch.setattr(main_mod, "lookup_user_id", lambda email, token: "UJOEL" if email == "joel.gnan@reelo.io" else None)
    monkeypatch.setattr(main_mod, "post_message", lambda ch, payload, token: posted.append(payload) or "1.1")
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 0
    blob = json.dumps(posted[0])
    assert "<@UJOEL> \\u2014 1 waiting" in blob or "<@UJOEL> — 1 waiting" in blob
    assert "xoxb-secret" not in capsys.readouterr().out


def test_unmatched_email_shows_bold_name(monkeypatch, stub_asana):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    posted = []
    monkeypatch.setattr(main_mod, "lookup_user_id", lambda email, token: None)
    monkeypatch.setattr(main_mod, "post_message", lambda ch, payload, token: posted.append(payload) or "1.1")
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 0
    assert "*Joel Gnan* — 1 waiting" in json.dumps(posted[0], ensure_ascii=False)


def test_invalid_blocks_falls_back_to_monospace_once(monkeypatch, stub_asana):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    monkeypatch.setattr(main_mod, "lookup_user_id", lambda email, token: None)
    posted = []

    def fake_post(ch, payload, token):
        posted.append(payload)
        if any(b["type"] == "table" for b in payload["blocks"]):
            raise SlackError("Slack API error: invalid_blocks", code="invalid_blocks")
        return "2.2"

    monkeypatch.setattr(main_mod, "post_message", fake_post)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 0
    assert len(posted) == 2 and not any(b["type"] == "table" for b in posted[1]["blocks"])


def test_stalled_report_dry_run(monkeypatch, capsys, stub_asana, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(report="stalled", dry_run=True, config_path=CONFIG, now=NOW) == 0
    assert "No stalled conversations today" in capsys.readouterr().out


def test_missing_tokens(monkeypatch, no_slack):
    monkeypatch.delenv("ASANA_TOKEN", raising=False)
    assert main_mod.run(report="daily", dry_run=True, config_path=CONFIG, now=NOW) == 2
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 2


def test_asana_error_returns_1_and_posts_nothing(monkeypatch, capsys, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")

    def fail(gid, token):
        raise AsanaError("Asana API error 500")

    monkeypatch.setattr(main_mod, "fetch_open_tasks", fail)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 1
    assert "500" in capsys.readouterr().err


def test_stories_error_fails_run(monkeypatch, stub_asana, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")

    def fail(task_gid, token):
        raise AsanaError("Asana API error 503")

    monkeypatch.setattr(main_mod, "fetch_stories", fail)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 1
