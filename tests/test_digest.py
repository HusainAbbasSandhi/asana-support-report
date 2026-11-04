from datetime import datetime, timedelta, timezone
from pathlib import Path

from digest_bot.config import load_config
from digest_bot.digest import build_daily, build_stalled, escape, monospace_fallback
from digest_bot.metrics import DailyReport
from digest_bot.models import Comment, Task

UTC = timezone.utc
NOW = datetime(2026, 11, 5, 4, 30, tzinfo=UTC)  # 10:00 IST Thursday
CFG = load_config(str(Path(__file__).parent.parent / "config.yaml"))
_n = 0


def tag(name, email):
    return f"<@{name}>" if name else "*Unassigned*"


def make_task(age_days=3, assignee="Priyank", email="p@x", name=None, url=None):
    global _n
    _n += 1
    return Task(gid=str(_n), name=name or f"Task {_n}", url=url or f"https://x/{_n}",
                created_at=NOW - timedelta(days=age_days), assignee_name=assignee, section_name=None,
                priority=None, status=None, requester=None, module=None, assignee_email=email)


def report(no_reply=(), **kw):
    base = dict(open=71, over_4d=50, assigned_to_support=6, no_reply=list(no_reply),
                raised_by=[("Haydar Abbas", 23), ("Ishika Batra", 17)])
    base.update(kw)
    return DailyReport(**base)


def texts(payload):
    return "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")


def table(payload):
    return next(b for b in payload["blocks"] if b["type"] == "table")


def test_escape():
    assert escape("a & <b>") == "a &amp; &lt;b&gt;"


def test_daily_header_date_ist_and_cc():
    p = build_daily(report(), CFG, NOW, tag)
    t = texts(p)
    assert "Daily Digest · Thursday, 5 Nov" in t
    assert "<@U04H2DR5JJ1> <@U01NJ4W5RLL> <@U01GGKD7468>" in t


def test_daily_table_rows_and_values():
    rows = table(build_daily(report(no_reply=[make_task()] * 30), CFG, NOW, tag))["rows"]
    flat = [[cell["text"] for cell in row] for row in rows]
    assert flat == [
        ["Metric", "Count"],
        ["Open tickets pending on Prod & Tech", "71"],
        ["Open for more than 4 days", "50"],
        ["Assigned to a support team member", "6"],
        ["First response pending by Prod & Tech (2+ days)", "30"],
    ]
    assert all(cell["type"] == "raw_text" for row in rows for cell in row)


def test_daily_raised_by_line():
    assert "Raised by: Haydar Abbas 23 · Ishika Batra 17" in texts(build_daily(report(), CFG, NOW, tag))


def test_no_reply_grouped_with_tags_counts_and_ages():
    p1 = make_task(age_days=5, assignee="Priyank", name="Old one")
    p2 = make_task(age_days=3, assignee="Priyank", name="Newer one")
    j1 = make_task(age_days=2.5, assignee="Joel")
    u1 = make_task(age_days=4, assignee=None, email=None)
    t = texts(build_daily(report(no_reply=[j1, p2, u1, p1]), CFG, NOW, tag))
    assert "First response pending by Prod &amp; Tech (2+ days) — 4" in t
    assert t.index("<@Priyank> — 2 waiting") < t.index("<@Joel> — 1 waiting") < t.index("*Unassigned* — 1 waiting")
    assert t.index("Old one") < t.index("Newer one")
    assert "• <https://x/" in t and "— 5 days" in t


def test_no_reply_group_capped_at_ten():
    tasks = [make_task(assignee="Priyank") for _ in range(13)]
    block = next(b["text"]["text"] for b in build_daily(report(no_reply=tasks), CFG, NOW, tag)["blocks"]
                 if b["type"] == "section" and "<@Priyank> — 13 waiting" in b["text"]["text"])
    assert block.count("• ") == 10 and "+3 more" in block


def test_no_reply_empty_state():
    assert "✅" in texts(build_daily(report(no_reply=[]), CFG, NOW, tag))


def test_titles_escaped():
    t = texts(build_daily(report(no_reply=[make_task(name="A <b> & c")]), CFG, NOW, tag))
    assert "A &lt;b&gt; &amp; c" in t


def test_footer_links():
    t = texts(build_daily(report(), CFG, NOW, tag))
    assert "project/1202029361021711|" in t and "project/1208716124012867|" in t


def test_blocks_within_limits():
    tasks = [make_task(assignee=f"Person {i % 12}", name="y" * 200, url="https://x/" + "z" * 120) for i in range(300)]
    p = build_daily(report(no_reply=tasks), CFG, NOW, tag)
    assert len(p["blocks"]) <= 50
    assert all(len(b["text"]["text"]) <= 3000 for b in p["blocks"] if b["type"] == "section")


def test_monospace_fallback_replaces_table_with_code_block():
    p = monospace_fallback(build_daily(report(), CFG, NOW, tag))
    assert not any(b["type"] == "table" for b in p["blocks"])
    t = texts(p)
    assert "```" in t and "Open for more than 4 days" in t and "50" in t


def test_stalled_lists_last_comment_and_tags():
    t1 = make_task(assignee="Joel", name="Yuki mismatch")
    last = Comment(NOW - timedelta(days=2, hours=1), "s1", "Haydar Abbas")
    t = texts(build_stalled([(t1, last)], CFG, NOW, tag))
    assert "Stalled conversations · Thursday, 5 Nov" in t
    assert "<@Joel> — 1 stalled" in t
    assert "Yuki mismatch" in t and "last comment 2 days ago by Haydar Abbas" in t


def test_stalled_empty_state_still_posts():
    p = build_stalled([], CFG, NOW, tag)
    assert "✅ No stalled conversations today" in texts(p)
