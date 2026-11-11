import json
import re
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

    def fake_tasks(gid, token, **kw):
        return [bug, outsider] if gid == BUG_GID else []

    def fake_stories(task_gid, token, **kw):
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


def test_daily_dry_run_only_support_tasks_no_slack(monkeypatch, capsys, stub_asana, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(report="daily", dry_run=True, config_path=CONFIG, now=NOW) == 0
    out = capsys.readouterr().out
    assert "Raised by tech" not in out
    assert '"Open requests pending on Prod & Tech"' in out
    assert stub_asana == ["111"]  # comments fetched only for in-scope tasks


def test_assignees_shown_as_bold_names_only_leads_mentioned(monkeypatch, capsys, stub_asana):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    posted = []
    monkeypatch.setattr(main_mod, "post_message", lambda ch, payload, token: posted.append(payload) or "1.1")
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 0
    blob = json.dumps(posted[0], ensure_ascii=False)
    assert "Joel Gnan" in blob and "\"Raised by\"" in blob
    assert set(re.findall(r"<@(U\w+)>", blob)) == {"U04H2DR5JJ1", "U01NJ4W5RLL", "U01GGKD7468"}
    assert "xoxb-secret" not in capsys.readouterr().out


def test_test_flag_posts_to_test_channel(monkeypatch, stub_asana):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    channels = []
    monkeypatch.setattr(main_mod, "post_message", lambda ch, payload, token: channels.append(ch) or "1.1")
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW, test=True) == 0
    assert main_mod.run(report="stalled", dry_run=False, config_path=CONFIG, now=NOW, test=True) == 0
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 0
    assert channels[:2] == ["C0CF6BY6KHS", "C0CF6BY6KHS"] and len(channels) == 3


def test_invalid_blocks_falls_back_to_monospace_once(monkeypatch, stub_asana):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    posted = []

    def fake_post(ch, payload, token):
        posted.append(payload)
        if any(b["type"] == "table" for b in payload["blocks"]):
            raise SlackError("Slack API error: invalid_blocks", code="invalid_blocks")
        return "2.2"

    monkeypatch.setattr(main_mod, "post_message", fake_post)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 0
    assert len(posted) == 2 and not any(b["type"] == "table" for b in posted[1]["blocks"])


def test_task_in_both_projects_counted_once(monkeypatch, capsys, no_slack):
    bug = _bug()
    calls = []
    monkeypatch.setattr(main_mod, "fetch_open_tasks", lambda gid, token, **kw: [bug])
    monkeypatch.setattr(main_mod, "fetch_stories", lambda gid, token, **kw: calls.append(gid) or [])
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(report="daily", dry_run=True, config_path=CONFIG, now=NOW) == 0
    out = json.loads(capsys.readouterr().out)
    rows = next(b for b in out["blocks"] if b["type"] == "table")["rows"]
    assert rows[1][1]["text"] == "1"
    assert calls == ["111"]


def test_stalled_report_dry_run(monkeypatch, capsys, stub_asana, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(report="stalled", dry_run=True, config_path=CONFIG, now=NOW) == 0
    assert "No reply yet (raised" in capsys.readouterr().out  # 5-day-old request, no comments


def test_missing_tokens(monkeypatch, no_slack):
    monkeypatch.delenv("ASANA_TOKEN", raising=False)
    assert main_mod.run(report="daily", dry_run=True, config_path=CONFIG, now=NOW) == 2
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 2


def test_asana_error_returns_1_and_posts_nothing(monkeypatch, capsys, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")

    def fail(gid, token, **kw):
        raise AsanaError("Asana API error 500")

    monkeypatch.setattr(main_mod, "fetch_open_tasks", fail)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 1
    assert "500" in capsys.readouterr().err


def test_stories_error_fails_run(monkeypatch, stub_asana, no_slack):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")

    def fail(task_gid, token, **kw):
        raise AsanaError("Asana API error 503")

    monkeypatch.setattr(main_mod, "fetch_stories", fail)
    assert main_mod.run(report="daily", dry_run=False, config_path=CONFIG, now=NOW) == 1


def test_ignored_commenters_do_not_count_as_prod_tech_reply(monkeypatch, capsys, no_slack):
    bug = _bug()
    bolddesk = {"resource_subtype": "comment_added", "created_at": (NOW - timedelta(hours=5)).isoformat().replace("+00:00", "Z"),
                "created_by": {"gid": "1206307213098057", "name": "Support Team"}}
    monkeypatch.setattr(main_mod, "fetch_open_tasks", lambda gid, token, **kw: [bug] if gid == BUG_GID else [])
    monkeypatch.setattr(main_mod, "fetch_stories", lambda gid, token, **kw: [bolddesk])
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(report="stalled", dry_run=True, config_path=CONFIG, now=NOW) == 0
    assert "No reply yet (raised" in capsys.readouterr().out
