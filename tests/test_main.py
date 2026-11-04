import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from digest_bot import main as main_mod
from digest_bot.asana_client import AsanaError

FIX = Path(__file__).parent / "fixtures"
CONFIG = str(Path(__file__).parent.parent / "config.yaml")
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
BUG_GID = "1202029361021711"


@pytest.fixture
def stub_fetch(monkeypatch):
    bug = json.loads((FIX / "bug_task.json").read_text(encoding="utf-8"))
    req = json.loads((FIX / "request_task.json").read_text(encoding="utf-8"))
    seen = []

    def fake_fetch(project_gid, token):
        seen.append(project_gid)
        return [bug] if project_gid == BUG_GID else [req]

    monkeypatch.setattr(main_mod, "fetch_open_tasks", fake_fetch)
    return seen


@pytest.fixture
def no_post(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("post_message must not be called")

    monkeypatch.setattr(main_mod, "post_message", boom)


def test_run_dry_run_prints_and_does_not_post(monkeypatch, capsys, stub_fetch, no_post):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert main_mod.run(dry_run=True, config_path=CONFIG, now=NOW) == 0
    out = capsys.readouterr().out
    assert "BUG TRACKING — 1 open" in out
    assert "REQUESTS TO TECH TEAM — 1 open" in out
    assert len(stub_fetch) == 2


def test_run_only_includes_support_raised(monkeypatch, capsys, no_post):
    bug = json.loads((FIX / "bug_task.json").read_text(encoding="utf-8"))  # created by Haydar (support)
    outsider = {**bug, "gid": "333", "name": "Raised by tech", "created_by": {"gid": "999", "name": "X"}}
    monkeypatch.setattr(main_mod, "fetch_open_tasks",
                        lambda gid, token: [bug, outsider] if gid == BUG_GID else [])
    monkeypatch.setenv("ASANA_TOKEN", "a")
    assert main_mod.run(dry_run=True, config_path=CONFIG, now=NOW) == 0
    out = capsys.readouterr().out
    assert "BUG TRACKING — 1 open" in out
    assert "Raised by tech" not in out


def test_run_posts_to_configured_channel(monkeypatch, capsys, stub_fetch):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    posted = {}

    def fake_post(channel, payload, token):
        posted.update(channel=channel, payload=payload, token=token)
        return "99.1"

    monkeypatch.setattr(main_mod, "post_message", fake_post)
    assert main_mod.run(dry_run=False, config_path=CONFIG, now=NOW) == 0
    assert posted["channel"] == "C075PCA1NF7" and posted["token"] == "xoxb-secret"
    out = capsys.readouterr()
    assert "Posted ts=99.1" in out.out
    assert "xoxb-secret" not in out.out + out.err


def test_run_missing_slack_token_returns_2_when_not_dry_run(monkeypatch, stub_fetch, no_post):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    assert main_mod.run(dry_run=False, config_path=CONFIG, now=NOW) == 2


def test_run_missing_asana_token_returns_2(monkeypatch, no_post):
    monkeypatch.delenv("ASANA_TOKEN", raising=False)
    assert main_mod.run(dry_run=True, config_path=CONFIG, now=NOW) == 2


def test_run_asana_error_returns_1_and_posts_nothing(monkeypatch, capsys, no_post):
    monkeypatch.setenv("ASANA_TOKEN", "a")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")

    def fail(project_gid, token):
        raise AsanaError("Asana API error 500")

    monkeypatch.setattr(main_mod, "fetch_open_tasks", fail)
    assert main_mod.run(dry_run=False, config_path=CONFIG, now=NOW) == 1
    assert "500" in capsys.readouterr().err
