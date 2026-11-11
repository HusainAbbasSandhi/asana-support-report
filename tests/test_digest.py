from datetime import datetime, timedelta, timezone
from pathlib import Path

from digest_bot.config import load_config
from digest_bot.digest import build_daily, build_stalled, escape, monospace_fallback
from digest_bot.metrics import DailyReport
from digest_bot.models import Comment, Task

UTC = timezone.utc
NOW = datetime(2026, 11, 5, 4, 30, tzinfo=UTC)  # 10:00 IST Thursday
CFG = load_config(str(Path(__file__).parent.parent / "config.yaml"))
HAYDAR = "1213456649719771"
_n = 0


def make_task(age_days=3, assignee="Priyank", name=None, url=None, creator=HAYDAR):
    global _n
    _n += 1
    return Task(gid=str(_n), name=name or f"Task {_n}", url=url or f"https://x/{_n}",
                created_at=NOW - timedelta(days=age_days), assignee_name=assignee, section_name=None,
                priority=None, status=None, requester=None, module=None, created_by_gid=creator)


def report(no_reply=(), **kw):
    base = dict(open=71, over_4d=50, assigned_to_support=6, no_reply=list(no_reply),
                raised_by=[("Haydar Abbas", 23), ("Ishika Batra", 17)])
    base.update(kw)
    return DailyReport(**base)


def daily(bug=None, req=None):
    return build_daily({"bug_tracking": bug or report(), "requests_to_tech": req or report(open=4)}, CFG, NOW)


def stalled(bug=(), req=()):
    return build_stalled({"bug_tracking": list(bug), "requests_to_tech": list(req)}, CFG, NOW)


def texts(payload):
    return "\n".join(b["text"]["text"] for b in payload["blocks"] if b["type"] == "section")


def cell_text(cell):
    if cell["type"] == "raw_text":
        return cell["text"]
    return "".join(e["text"] for s in cell["elements"] for e in s["elements"])


def tables(payload):
    return [[[cell_text(c) for c in row] for row in b["rows"]] for b in payload["blocks"] if b["type"] == "table"]


def test_escape():
    assert escape("a & <b>") == "a &amp; &lt;b&gt;"


def test_daily_header_date_ist_and_cc():
    t = texts(daily())
    assert "Daily Digest · Thursday, 5 Nov" in t
    assert "<@U04H2DR5JJ1> <@U01NJ4W5RLL> <@U01GGKD7468>" in t


def test_daily_metrics_and_raised_by_tables():
    metrics, raised = tables(daily(report(no_reply=[make_task()] * 30)))[:2]
    assert metrics == [
        ["Metric", "Count"],
        ["Open requests pending on Prod & Tech", "71"],
        ["Open for more than 4 days", "50"],
        ["Assigned to a support team member", "6"],
        ["First response pending by Prod & Tech (2+ days)", "30"],
    ]
    assert raised == [["Support agent", "Open requests"], ["Haydar Abbas", "23"], ["Ishika Batra", "17"]]


def test_daily_pending_table_has_raised_by_assignee_and_age():
    p1 = make_task(age_days=5, assignee="Priyank", name="Old one")
    p2 = make_task(age_days=3, assignee="Priyank", name="Newer one")
    j1 = make_task(age_days=2.5, assignee="akash.mathur@reelo.io", creator="nobody")
    u1 = make_task(age_days=4, assignee=None)
    pending = tables(daily(report(no_reply=[j1, p2, u1, p1])))[2]
    assert pending[0] == ["#", "Request", "Raised by", "Assigned to", "Waiting since raised"]
    assert pending[1:] == [
        ["1", "Old one", "Haydar Abbas", "Priyank", "5 days"],
        ["2", "Newer one", "Haydar Abbas", "Priyank", "3 days"],
        ["3", j1.name, "—", "Akash Mathur", "2 days"],
        ["4", u1.name, "Haydar Abbas", "Unassigned", "4 days"],
    ]


def test_request_cell_is_a_link_and_long_names_shortened():
    t = make_task(name="x" * 80, url="https://app.asana.com/t/1")
    cell = next(b for b in daily(report(no_reply=[t]))["blocks"] if b["type"] == "table" and len(b["rows"][0]) == 5)["rows"][1][1]
    link = cell["elements"][0]["elements"][0]
    assert cell["type"] == "rich_text" and link["type"] == "link" and link["url"] == "https://app.asana.com/t/1"
    assert len(link["text"]) == 55 and link["text"].endswith("…")


def test_no_reply_empty_state():
    p = daily(report(no_reply=[]))
    assert "✅" in texts(p) and len(tables(p)) == 2


def test_footer_link_bug_tracking_only():
    t = texts(daily())
    assert "project/1202029361021711|Open Bug Tracking" in t and "1208716124012867" not in t


def test_table_capped_at_slack_row_limit():
    tasks = [make_task(assignee=f"Person {i % 12}") for i in range(150)]
    p = daily(report(no_reply=tasks))
    assert max(len(b["rows"]) for b in p["blocks"] if b["type"] == "table") == 100
    assert "+51 more in Asana" in texts(p)
    assert len(p["blocks"]) <= 50


def test_monospace_fallback_replaces_every_table():
    p = monospace_fallback(daily(report(no_reply=[make_task(name="Fallback one")])))
    assert not any(b["type"] == "table" for b in p["blocks"])
    t = texts(p)
    assert t.count("```") == 6 and "Open for more than 4 days" in t and "Fallback one" in t


def test_stalled_table_columns_and_values():
    t1 = make_task(assignee="Joel", name="Yuki mismatch")
    t2 = make_task(age_days=4, assignee="Joel", name="Silent one")
    last = Comment(NOW - timedelta(days=2, hours=1), "tech", "akash.mathur@reelo.io")
    p = stalled(bug=[(t1, last), (t2, None)])
    assert "Stalled conversations · Thursday, 5 Nov" in texts(p)
    assert "🐞 BUG TRACKING — 2 stalled" in texts(p)
    (table,) = tables(p)
    assert table[0] == ["#", "Request", "Raised by", "Assigned to", "Since last Prod & Tech reply", "Replied by"]
    assert table[1:] == [
        ["1", "Silent one", "Haydar Abbas", "Joel", "No reply yet (raised 4 days ago)", "—"],
        ["2", "Yuki mismatch", "Haydar Abbas", "Joel", "2 days", "Akash Mathur"],
    ]


def test_stalled_bug_tracking_only_and_empty_state():
    t1 = make_task(name="Bug stalled")
    t2 = make_task(name="Req stalled")
    p = stalled(bug=[(t1, None)], req=[(t2, None)])
    flat = str(tables(p))
    assert "Bug stalled" in flat and "Req stalled" not in flat and "REQUESTS TO TECH" not in texts(p)
    assert "✅ No stalled conversations" in texts(stalled())
