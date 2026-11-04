from datetime import datetime, timedelta, timezone
from pathlib import Path

from digest_bot.config import load_config
from digest_bot.digest import build_digest, escape
from digest_bot.models import Task

UTC = timezone.utc
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)  # 10:30 IST, Wednesday
CFG = load_config(str(Path(__file__).parent.parent / "config.yaml"))
_n = 0


def make_task(**kw) -> Task:
    global _n
    _n += 1
    base = dict(
        gid=str(_n),
        name=f"Task {_n}",
        url=f"https://app.asana.com/1/w/project/p/task/{_n}",
        created_at=NOW - timedelta(days=3),
        assignee_name="Joel Gnan",
        section_name="Open",
        priority=None,
        status=None,
        requester=None,
        module=None,
    )
    base.update(kw)
    return Task(**base)


def text_of(payload) -> str:
    return "\n".join(b["text"]["text"] for b in payload["blocks"] if b.get("type") == "section")


def test_header_has_ist_date_and_mentions():
    p = build_digest([], [], CFG, NOW)
    t = text_of(p)
    assert "Tech Requests — Daily Digest · Wednesday, 4 Nov" in t
    assert "<@U04H2DR5JJ1> <@U01NJ4W5RLL> <@U01GGKD7468>" in t
    assert "<@U04H2DR5JJ1>" in p["text"]


def test_header_date_uses_ist_not_utc():
    late_utc = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)  # 01:30 IST on 5 Nov
    assert "Thursday, 5 Nov" in text_of(build_digest([], [], CFG, late_utc))


def test_bug_summary_counts():
    bugs = [
        make_task(created_at=NOW - timedelta(hours=2), priority="Critical"),
        make_task(created_at=NOW - timedelta(hours=5), priority="High", assignee_name=None),
        make_task(section_name="Blocked"),
        make_task(status="Blocked"),
        make_task(priority="Low"),
    ]
    t = text_of(build_digest(bugs, [], CFG, NOW))
    assert "BUG TRACKING — 5 open" in t
    assert "🆕 2 new" in t
    assert "🔴 1 Critical" in t
    assert "Critical/High" not in t
    assert "🚫 2 Blocked" in t
    assert "👤 1 unassigned" in t


def test_new_means_created_within_24h():
    bugs = [
        make_task(name="Fresh one", created_at=NOW - timedelta(hours=23)),
        make_task(name="Stale one", created_at=NOW - timedelta(hours=25)),
    ]
    p = build_digest(bugs, [], CFG, NOW)
    new_block = next(b["text"]["text"] for b in p["blocks"] if "New since yesterday" in b.get("text", {}).get("text", ""))
    assert "Fresh one" in new_block and "Stale one" not in new_block


def test_critical_list_is_critical_only_newest_first():
    bugs = [
        make_task(name="High one", priority="High", created_at=NOW - timedelta(days=1)),
        make_task(name="Crit old", priority="Critical", created_at=NOW - timedelta(days=30)),
        make_task(name="Crit new", priority="Critical", created_at=NOW - timedelta(days=2)),
    ]
    p = build_digest(bugs, [], CFG, NOW)
    block = next(b["text"]["text"] for b in p["blocks"] if "Critical still open" in b.get("text", {}).get("text", ""))
    assert "High one" not in block
    assert block.index("Crit new") < block.index("Crit old")


def test_new_list_still_sorts_critical_first():
    bugs = [
        make_task(name="Low fresh", priority="Low", created_at=NOW - timedelta(hours=1)),
        make_task(name="Crit fresh", priority="Critical", created_at=NOW - timedelta(hours=5)),
    ]
    p = build_digest(bugs, [], CFG, NOW)
    block = next(b["text"]["text"] for b in p["blocks"] if "New since yesterday" in b.get("text", {}).get("text", ""))
    assert block.index("Crit fresh") < block.index("Low fresh")


def test_bullet_format():
    bugs = [make_task(name="OTP stuck", priority="Critical", module="Loyalty", requester="Dimple Manglani",
                      assignee_name=None, created_at=NOW - timedelta(hours=1), url="https://x/1")]
    t = text_of(build_digest(bugs, [], CFG, NOW))
    assert "• <https://x/1|OTP stuck> — Critical · Loyalty · by Dimple Manglani · → unassigned" in t


def test_list_truncates_with_more_line():
    bugs = [make_task(created_at=NOW - timedelta(hours=1)) for _ in range(13)]
    p = build_digest(bugs, [], CFG, NOW)
    block = next(b["text"]["text"] for b in p["blocks"] if "New since yesterday" in b.get("text", {}).get("text", ""))
    assert block.count("• ") == 10
    assert "+3 more" in block


def test_oldest_list_max_five_with_age_days():
    bugs = [make_task(created_at=NOW - timedelta(days=d)) for d in (21, 15, 12, 10, 8, 4, 2)]
    p = build_digest(bugs, [], CFG, NOW)
    block = next(b["text"]["text"] for b in p["blocks"] if "Oldest open" in b.get("text", {}).get("text", ""))
    assert block.count("• ") == 5
    assert "21 days" in block
    assert block.index("21 days") < block.index("15 days")


def test_requests_section_counts_by_section():
    reqs = [make_task(section_name="Other requests"), make_task(section_name="Other requests"),
            make_task(section_name="Feature Requests")]
    t = text_of(build_digest([], reqs, CFG, NOW))
    assert "REQUESTS TO TECH TEAM — 3 open" in t
    assert "Other requests 2" in t and "Feature Requests 1" in t


def test_empty_project_shows_nothing_open():
    t = text_of(build_digest([], [make_task()], CFG, NOW))
    assert "BUG TRACKING — 0 open" in t
    assert "✅ Nothing open" in t


def test_escape():
    assert escape("a & <b>") == "a &amp; &lt;b&gt;"


def test_title_escaped_and_truncated():
    bugs = [make_task(name="OTP <fails> & SMS", created_at=NOW - timedelta(hours=1)),
            make_task(name="x" * 200, created_at=NOW - timedelta(hours=1))]
    t = text_of(build_digest(bugs, [], CFG, NOW))
    assert "OTP &lt;fails&gt; &amp; SMS" in t
    assert "x" * 91 not in t
    assert "x" * 89 + "…" in t


def test_blocks_within_slack_limits():
    bugs = [make_task(name="y" * 200, priority="Critical", module="A/B/C/D", requester="Somebody Long Name",
                      url="https://app.asana.com/" + "z" * 120, created_at=NOW - timedelta(hours=1))
            for _ in range(200)]
    p = build_digest(bugs, bugs, CFG, NOW)
    assert len(p["blocks"]) <= 50
    for b in p["blocks"]:
        if b.get("type") == "section":
            assert len(b["text"]["text"]) <= 3000


def test_header_says_support_raised_when_filtered():
    cfg = {**CFG, "asana": {**CFG["asana"], "support_team": ["1"]}}
    assert "raised by the support team" in text_of(build_digest([], [], cfg, NOW))


def test_header_has_no_support_note_when_unfiltered():
    cfg = {**CFG, "asana": {**CFG["asana"], "support_team": []}}
    assert "raised by the support team" not in text_of(build_digest([], [], cfg, NOW))


def test_footer_links_both_projects():
    t = text_of(build_digest([], [], CFG, NOW))
    assert "https://app.asana.com/1/463982800396267/project/1202029361021711" in t
    assert "https://app.asana.com/1/463982800396267/project/1208716124012867" in t
