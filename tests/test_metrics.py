from datetime import datetime, timedelta, timezone

from digest_bot.metrics import daily_report, group_by_assignee, stalled_report
from digest_bot.models import Comment, Task

UTC = timezone.utc
NOW = datetime(2026, 11, 5, 4, 30, tzinfo=UTC)
TEAM = {"s1": "Haydar Abbas", "s2": "Ishika Batra", "s3": "Haydar Abbas"}
_n = 0


def task(age_h, creator="s1", assignee=None, email=None, assignee_gid=None, due_on=None):
    global _n
    _n += 1
    return Task(gid=str(_n), name=f"T{_n}", url=f"https://x/{_n}", created_at=NOW - timedelta(hours=age_h),
                assignee_name=assignee, section_name=None, priority=None, status=None, requester=None,
                module=None, created_by_gid=creator, assignee_gid=assignee_gid, assignee_email=email,
                due_on=due_on)


def test_due_date_excludes_from_no_reply_but_still_counted_open():
    with_due = task(72, due_on="2026-11-20")
    without = task(72)
    r = daily_report([with_due, without], {}, TEAM, NOW)
    assert r.no_reply == [without]
    assert r.open == 2 and r.over_4d == 0


def test_due_date_excludes_from_stalled():
    with_due = task(100, due_on="2026-11-01")
    without = task(100)
    comments = {t.gid: [c(80, "tech1"), c(30, "s1")] for t in (with_due, without)}
    assert [t for t, _ in stalled_report([with_due, without], comments, TEAM, NOW)] == [without]


def c(age_h, author):
    return Comment(NOW - timedelta(hours=age_h), author, author)


def test_open_count_and_over_4_days_strict():
    ts = [task(97), task(96), task(10)]
    r = daily_report(ts, {}, TEAM, NOW)
    assert r.open == 3
    assert r.over_4d == 1  # exactly 96h is not "more than 4 days"


def test_assigned_to_support_member():
    ts = [task(5, assignee_gid="s2"), task(5, assignee_gid="tech1"), task(5)]
    assert daily_report(ts, {}, TEAM, NOW).assigned_to_support == 1


def test_no_reply_requires_over_48h_and_no_non_support_comment():
    old_silent = task(49)
    exactly_48 = task(48)
    young = task(10)
    only_support_commented = task(72)
    tech_replied = task(72)
    comments = {only_support_commented.gid: [c(60, "s2"), c(50, "s1")],
                tech_replied.gid: [c(60, "tech1")]}
    r = daily_report([old_silent, exactly_48, young, only_support_commented, tech_replied], comments, TEAM, NOW)
    assert {t.gid for t in r.no_reply} == {old_silent.gid, only_support_commented.gid}


def test_anonymous_comment_does_not_count_as_tech_reply():
    t = task(72)
    r = daily_report([t], {t.gid: [Comment(NOW - timedelta(hours=60), None, None)]}, TEAM, NOW)
    assert r.no_reply == [t]


def test_raised_by_merges_accounts_by_name_highest_first():
    ts = [task(5, creator="s1"), task(5, creator="s3"), task(5, creator="s2")]
    assert daily_report(ts, {}, TEAM, NOW).raised_by == [("Haydar Abbas", 2), ("Ishika Batra", 1)]


def test_stalled_needs_tech_reply_and_last_comment_over_24h():
    no_tech = task(100)
    active = task(100)
    stalled = task(100)
    comments = {
        no_tech.gid: [c(50, "s1")],
        active.gid: [c(50, "tech1"), c(3, "s1")],
        stalled.gid: [c(80, "tech1"), c(30, "s1")],
    }
    out = stalled_report([no_tech, active, stalled], comments, TEAM, NOW)
    assert [(t.gid, last.author_gid) for t, last in out] == [(stalled.gid, "s1")]


def test_stalled_empty_when_nothing_matches():
    assert stalled_report([task(5)], {}, TEAM, NOW) == []


def test_group_by_assignee_largest_first_unassigned_last_oldest_first():
    a1, a2 = task(10, assignee="Priyank", email="p@x"), task(90, assignee="Priyank", email="p@x")
    b1 = task(20, assignee="Joel", email="j@x")
    u1, u2, u3 = task(5), task(6), task(7)
    groups = group_by_assignee([a1, b1, u1, a2, u2, u3])
    assert [g[0] for g in groups] == ["Priyank", "Joel", None]
    assert groups[0][1] == "p@x"
    assert groups[0][2] == [a2, a1]


def test_group_by_assignee_with_key_for_tuples():
    t = task(30, assignee="Joel")
    groups = group_by_assignee([(t, "last")], key=lambda x: x[0])
    assert groups == [("Joel", None, [(t, "last")])]
