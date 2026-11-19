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
from digest_bot.models import Comment, Task, comments_from_stories, mentions_in

NOW = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
TEAM = {"s1": "Ishika Batra", "s1b": "Ishika Batra", "s2": "Haydar Abbas"}
CFG = load_config(str(Path(__file__).parent.parent / "config.yaml"))


def task(i, due_on=None):
    return Task(gid=str(i), name=f"T{i}", url=f"https://app.asana.com/0/1/{i}", created_at=NOW - timedelta(days=5),
                assignee_name="Pragati", section_name=None, priority=None, status=None, requester=None,
                module=None, created_by_gid="1213456649719771", due_on=due_on)


def c(hours, author, *tags):
    return Comment(NOW - timedelta(hours=hours), author, f"name-{author}", tuple(tags))


def flagged(comments, tasks=None):
    tasks = tasks or [task(k) for k in comments]
    return [(t.gid, tagged) for t, _, tagged in support_pending(tasks, comments, TEAM, NOW)]


def test_untagged_tech_chatter_is_not_flagged():
    assert flagged({"0": [c(10, "s1"), c(8, "tech"), c(5, "tech2", "tech")]}) == []


def test_tagged_agent_who_has_not_replied_for_3h_is_flagged():
    assert flagged({"0": [c(10, "s1"), c(4, "tech", "s1")]}) == [("0", ["Ishika Batra"])]


def test_under_or_exactly_3h_is_not_flagged():
    assert flagged({"0": [c(2, "tech", "s1")], "1": [c(3, "tech", "s1")]}) == []


def test_reply_by_tagged_agent_from_any_account_clears_it():
    assert flagged({"0": [c(6, "tech", "s1"), c(5, "s1b")]}) == []


def test_reply_by_a_different_agent_does_not_clear_it():
    assert flagged({"0": [c(6, "tech", "s1"), c(5, "s2")]}) == [("0", ["Ishika Batra"])]


def test_tech_chatting_after_the_tag_keeps_it_flagged():
    assert flagged({"0": [c(6, "tech", "s1"), c(5, "tech2"), c(1, "tech")]}) == [("0", ["Ishika Batra"])]


def test_latest_tag_counts_and_old_answered_tags_do_not():
    # Ishika answered the first tag; a newer tag of Haydar is still open.
    assert flagged({"0": [c(20, "tech", "s1"), c(19, "s1"), c(4, "tech", "s2")]}) == [("0", ["Haydar Abbas"])]
    # Support tagging each other does not count as a Prod & Tech tag.
    assert flagged({"1": [c(6, "s2", "s1")]}) == []


def test_several_tagged_any_one_reply_clears_and_order_is_longest_wait_first():
    assert flagged({"0": [c(6, "tech", "s1", "s2"), c(5, "s2")]}) == []
    got = flagged({"a": [c(4, "tech", "s1")], "b": [c(9, "tech", "s2", "s1")]})
    assert got == [("b", ["Haydar Abbas", "Ishika Batra"]), ("a", ["Ishika Batra"])]


def test_due_date_does_not_exclude():
    assert flagged({"1": [c(5, "tech", "s1")]}, [task(1, due_on="2026-11-30")])


@pytest.mark.parametrize("count", [0, 1, 5, 99, 150])
def test_payload_is_slack_valid(count):
    items = [(task(i), c(4 + i, "tech", "s1"), ["Ishika Batra"]) for i in range(count)]
    p = build_support_pending({"bug_tracking": items}, CFG, NOW)
    assert payload_problems(p) == [] and payload_problems(monospace_fallback(p)) == []


def test_payload_wording():
    items = [(task(1), c(5, "tech", "s1"), ["Ishika Batra"]), (task(2), c(50, "tech", "s2"), ["Haydar Abbas"])]
    flat = str(build_support_pending({"bug_tracking": items}, CFG, NOW))
    assert "Support reply pending" in flat and "2 waiting on support" in flat and "Tagged (needs to reply)" in flat
    assert "5 hours ago" in flat and "2 days ago" in flat and "Ishika Batra" in flat
    empty = build_support_pending({"bug_tracking": []}, CFG, NOW)
    assert "Support is all caught up" in str(empty) and not any(b["type"] == "table" for b in empty["blocks"])
    assert payload_problems(empty) == []


def test_praise_line_rotates_across_slots():
    lines = {build_support_pending({}, CFG, NOW.replace(hour=h))["blocks"][0]["text"]["text"].split("\n")[1]
             for h in (7, 10, 13)}  # 1, 4, 7 PM IST
    assert len(lines) == 3


def test_mentions_are_read_from_asana_html():
    html = ('<body>hi <a href="https://app.asana.com/1/4/profile/9" data-asana-gid="4242" '
            'data-asana-accessible="true" data-asana-type="user" data-asana-dynamic="true">@Haydar Abbas</a> see '
            '<a href="x" data-asana-gid="555" data-asana-type="task">a task</a> '
            '<a data-asana-type="user" data-asana-gid="4242">@Haydar Abbas</a></body>')
    assert mentions_in(html) == ("4242",)
    assert mentions_in(None) == ()
    (cm,) = comments_from_stories([{"resource_subtype": "comment_added", "created_at": "2026-11-17T05:17:00.000Z",
                                    "created_by": {"gid": "7", "name": "akash"}, "html_text": html}])
    assert cm.mentions == ("4242",)
