"""Every report we can build must pass Slack's block rules, so neither message falls back to plain text."""
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path

import pytest

from digest_bot.config import load_config
from digest_bot.digest import (
    build_daily,
    build_stalled,
    monospace_fallback,
    payload_problems,
)
from digest_bot.metrics import DailyReport
from digest_bot.models import Comment, Task

NOW = datetime(2026, 11, 12, 4, 30, tzinfo=UTC)
CFG = load_config(str(Path(__file__).parent.parent / "config.yaml"))
HAYDAR = "1213456649719771"
UNKNOWN = "999"

# Names Asana can really hand us: empty, blank, markup, pipes, emoji, very long, missing.
NAMES = ["", "   ", "<!channel> & co", "A | B | C", "```code```", "🔥 Urgent", "x" * 300, "Normal request"]
PEOPLE = [None, "", "  ", "akash.mathur@reelo.io", "Pragati", "<@U123>"]
URLS = [None, "", "https://app.asana.com/0/1/2"]


def task(i, name="Request", assignee="Pragati", url="https://app.asana.com/0/1/2", creator=HAYDAR, age=5):
    return Task(gid=str(i), name=name, url=url, created_at=NOW - timedelta(days=age), assignee_name=assignee,
                section_name=None, priority=None, status=None, requester=None, module=None,
                created_by_gid=creator)


def odd_tasks():
    return [task(i, name=n, assignee=a, url=u, creator=c, age=i % 20)
            for i, (n, a, u, c) in enumerate(product(NAMES, PEOPLE, URLS, [HAYDAR, UNKNOWN]))]


def daily(**kw):
    base = {"open": 26, "over_4d": 24, "assigned_to_support": 4, "no_reply": [], "raised_by": []}
    base.update(kw)
    return build_daily({"bug_tracking": DailyReport(**base)}, CFG, NOW)


def check(payload):
    assert payload_problems(payload) == []
    assert payload_problems(monospace_fallback(payload)) == []


@pytest.mark.parametrize("raisers", [0, 1, 3, 4, 5, 7, 12])
@pytest.mark.parametrize("pending", [0, 1, 4, 99, 100, 250])
def test_daily_is_slack_valid_for_any_number_of_raisers_and_pending(raisers, pending):
    raised = [(f"Agent {i}", i + 1) for i in range(raisers)]
    check(daily(raised_by=raised, no_reply=[task(i) for i in range(pending)]))


def test_daily_is_slack_valid_with_odd_names_people_and_links():
    raised = [(n, 1) for n in NAMES]
    check(daily(raised_by=raised, no_reply=odd_tasks()))


@pytest.mark.parametrize("count", [0, 1, 19, 99, 100, 250])
def test_stalled_is_slack_valid_for_any_count(count):
    items = [(task(i), None if i % 2 else Comment(NOW - timedelta(days=3), "1", "Pragati")) for i in range(count)]
    check(build_stalled({"bug_tracking": items}, CFG, NOW))


def test_stalled_is_slack_valid_with_odd_names_people_and_links():
    items = [(t, Comment(NOW - timedelta(hours=30), "1", p)) for t, p in zip(odd_tasks(), PEOPLE * 200)]
    check(build_stalled({"bug_tracking": items}, CFG, NOW))


def test_checker_catches_the_12_nov_bug():
    bad = {"text": "x", "blocks": [{"type": "table", "column_settings": [{}, {}],
                                    "rows": [[{"type": "raw_text", "text": "a"}, {"type": "raw_text", "text": "b"}],
                                             [{"type": "raw_text", "text": ""}, {"type": "raw_text", "text": "1"}]]}]}
    assert payload_problems(bad)
