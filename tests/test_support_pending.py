"""Prod & Tech replied last and support has not answered for 3h+."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from digest_bot.config import load_config
from digest_bot.digest import (
    build_support_pending,
    monospace_fallback,
    payload_problems,
)
from digest_bot.metrics import support_pending
from digest_bot.models import Comment, Task

NOW = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
TEAM = {"s1": "Haydar Abbas"}
CFG = load_config(str(Path(__file__).parent.parent / "config.yaml"))


def task(i, due_on=None):
    return Task(gid=str(i), name=f"T{i}", url=f"https://app.asana.com/0/1/{i}", created_at=NOW - timedelta(days=5),
                assignee_name="Pragati", section_name=None, priority=None, status=None, requester=None,
                module=None, created_by_gid="1213456649719771", due_on=due_on)


def c(hours, author):
    return Comment(NOW - timedelta(hours=hours), author, f"name-{author}")


def test_flags_only_when_tech_wrote_last_more_than_3h_ago():
    ts = [task(i) for i in range(6)]
    comments = {
        "0": [c(10, "s1"), c(4, "tech")],          # tech last, 4h -> flag
        "1": [c(10, "tech"), c(5, "s1")],          # support answered -> no
        "2": [c(2, "tech")],                       # only 2h -> no
        "3": [c(3, "tech")],                       # exactly 3h -> no
        "4": [],                                   # no comments -> no (stalled report covers it)
        "5": [c(30, "tech"), Comment(NOW - timedelta(hours=1), None, None)],  # unknown author ignored -> flag
    }
    got = support_pending(ts, comments, TEAM, NOW)
    assert [t.gid for t, _ in got] == ["5", "0"]  # longest waiting first
    assert got[1][1].author_gid == "tech"


def test_due_date_does_not_exclude():
    t = task(1, due_on="2026-11-30")
    assert support_pending([t], {"1": [c(5, "tech")]}, TEAM, NOW)


@pytest.mark.parametrize("count", [0, 1, 5, 99, 150])
def test_payload_is_slack_valid(count):
    items = [(task(i), c(4 + i, "tech")) for i in range(count)]
    p = build_support_pending({"bug_tracking": items}, CFG, NOW)
    assert payload_problems(p) == [] and payload_problems(monospace_fallback(p)) == []


def test_payload_wording():
    p = build_support_pending({"bug_tracking": [(task(1), c(5, "tech")), (task(2), c(50, "tech"))]}, CFG, NOW)
    flat = str(p)
    assert "Support reply pending" in flat and "2 waiting on support" in flat
    assert "5 hours ago" in flat and "2 days ago" in flat
    empty = str(build_support_pending({}, CFG, NOW))
    assert "Support has answered every Prod &amp; Tech reply" in empty
