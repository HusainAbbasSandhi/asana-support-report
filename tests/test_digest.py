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


def daily(bug=None, req=None):
    return build_daily({"bug_tracking": bug or report(), "requests_to_tech": req or report(open=4)}, CFG, NOW, tag)


def stalled(bug=(), req=()):
    return build_stalled({"bug_tracking": list(bug), "requests_to_tech": list(req)}, CFG, NOW, tag)


def texts(payload):
    return "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")


def table(payload):
    return next(b for b in payload["blocks"] if b["type"] == "table")


def test_escape():
    assert escape("a & <b>") == "a &amp; &lt;b&gt;"


def test_daily_header_date_ist_and_cc():
    p = daily(report())
    t = texts(p)
    assert "Daily Digest · Thursday, 5 Nov" in t
    assert "<@U04H2DR5JJ1> <@U01NJ4W5RLL> <@U01GGKD7468>" in t


def test_daily_table_rows_and_values():
    rows = table(daily(report(no_reply=[make_task()] * 30)))["rows"]
    flat = [[cell["text"] for cell in row] for row in rows]
    assert flat == [
        ["Metric", "Count"],
        ["Open requests pending on Prod & Tech", "71"],
        ["Open for more than 4 days", "50"],
        ["Assigned to a support team member", "6"],
        ["First response pending by Prod & Tech (2+ days)", "30"],
    ]
    assert all(cell["type"] == "raw_text" for row in rows for cell in row)


def test_daily_raised_by_line():
    assert "Raised by: Haydar Abbas 23 · Ishika Batra 17" in texts(daily(report()))


def test_no_reply_grouped_with_tags_counts_and_ages():
    p1 = make_task(age_days=5, assignee="Priyank", name="Old one")
    p2 = make_task(age_days=3, assignee="Priyank", name="Newer one")
    j1 = make_task(age_days=2.5, assignee="Joel")
    u1 = make_task(age_days=4, assignee=None, email=None)
    t = texts(daily(report(no_reply=[j1, p2, u1, p1])))
    assert "First response pending by Prod &amp; Tech (2+ days) — 4" in t
    assert t.index("<@Priyank> — 2 waiting") < t.index("<@Joel> — 1 waiting") < t.index("*Unassigned* — 1 waiting")
    assert t.index("Old one") < t.index("Newer one")
    assert "• <https://x/" in t and "— 5 days" in t


def test_no_reply_group_capped_at_ten():
    tasks = [make_task(assignee="Priyank") for _ in range(13)]
    block = next(b["text"]["text"] for b in daily(report(no_reply=tasks))["blocks"]
                 if b["type"] == "section" and "<@Priyank> — 13 waiting" in b["text"]["text"])
    assert block.count("• ") == 10 and "+3 more" in block


def test_no_reply_empty_state():
    assert "✅" in texts(daily(report(no_reply=[])))


def test_titles_escaped():
    t = texts(daily(report(no_reply=[make_task(name="A <b> & c")])))
    assert "A &lt;b&gt; &amp; c" in t


def test_footer_links():
    t = texts(daily(report()))
    assert "project/1202029361021711|" in t


def test_blocks_within_limits():
    tasks = [make_task(assignee=f"Person {i % 12}", name="y" * 200, url="https://x/" + "z" * 120) for i in range(300)]
    p = daily(report(no_reply=tasks))
    assert len(p["blocks"]) <= 50
    assert all(len(b["text"]["text"]) <= 3000 for b in p["blocks"] if b["type"] == "section")


def test_monospace_fallback_replaces_table_with_code_block():
    p = monospace_fallback(daily(report()))
    assert not any(b["type"] == "table" for b in p["blocks"])
    t = texts(p)
    assert "```" in t and "Open for more than 4 days" in t and "50" in t


def test_stalled_lists_last_comment_and_tags():
    t1 = make_task(assignee="Joel", name="Yuki mismatch")
    last = Comment(NOW - timedelta(days=2, hours=1), "s1", "Haydar Abbas")
    t = texts(stalled([(t1, last)]))
    assert "Stalled conversations · Thursday, 5 Nov" in t
    assert "<@Joel> — 1 stalled" in t
    assert "Yuki mismatch" in t and "last comment 2 days ago by Haydar Abbas" in t


def test_stalled_empty_state_still_posts():
    p = stalled()
    assert "✅ No stalled conversations" in texts(p)


def test_daily_reports_bug_tracking_only():
    p = daily(report(no_reply=[make_task(name="Bug one")]), report(open=4, no_reply=[make_task(name="Req one")]))
    t = texts(p)
    assert "🐞 BUG TRACKING" in t and "Bug one" in t
    assert "REQUESTS TO TECH" not in t and "Req one" not in t and "1208716124012867" not in t
    assert len([b for b in p["blocks"] if b["type"] == "table"]) == 1
    assert "ticket" not in t.lower()


def test_stalled_bug_tracking_only():
    t1 = make_task(assignee="Joel", name="Bug stalled")
    t2 = make_task(assignee="Joel", name="Req stalled")
    last = Comment(NOW - timedelta(days=2), "s1", "Haydar")
    t = texts(stalled(bug=[(t1, last)], req=[(t2, last)]))
    assert "🐞 BUG TRACKING — 1 stalled" in t and "Bug stalled" in t
    assert "Req stalled" not in t and "REQUESTS TO TECH" not in t
    assert "✅ No stalled conversations" in texts(stalled())


def test_stalled_no_reply_bullet():
    t1 = make_task(age_days=5, assignee="Joel", name="Silent one")
    t = texts(stalled(bug=[(t1, None)]))
    assert "Silent one" in t and "no reply from Prod &amp; Tech yet · raised 5 days ago" in t
