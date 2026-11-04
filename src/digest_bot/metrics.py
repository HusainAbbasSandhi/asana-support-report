"""Pure report logic: counts and lists computed from tasks + their comments."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from digest_bot.models import Comment, Task

OPEN_LONG = timedelta(hours=96)
NO_REPLY_AFTER = timedelta(hours=48)
STALLED_AFTER = timedelta(hours=24)


@dataclass
class DailyReport:
    open: int
    over_4d: int
    assigned_to_support: int
    no_reply: list[Task] = field(default_factory=list)
    raised_by: list[tuple[str, int]] = field(default_factory=list)


def _tech_comments(comments: list[Comment], team: dict) -> list[Comment]:
    """Product & Tech = any identified author who is not on the support team."""
    return [c for c in comments if c.author_gid and c.author_gid not in team]


def daily_report(tasks: list[Task], comments: dict[str, list[Comment]], team: dict, now: datetime) -> DailyReport:
    no_reply = [t for t in tasks
                if now - t.created_at > NO_REPLY_AFTER and not _tech_comments(comments.get(t.gid, []), team)]
    counts = Counter(team.get(t.created_by_gid, "Unknown") for t in tasks)
    return DailyReport(
        open=len(tasks),
        over_4d=sum(1 for t in tasks if now - t.created_at > OPEN_LONG),
        assigned_to_support=sum(1 for t in tasks if t.assignee_gid in team),
        no_reply=no_reply,
        raised_by=sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
    )


def stalled_report(tasks: list[Task], comments: dict[str, list[Comment]], team: dict,
                   now: datetime) -> list[tuple[Task, Comment]]:
    """Tasks with a first Product & Tech response whose latest comment is older than 24h."""
    out = []
    for t in tasks:
        cs = comments.get(t.gid, [])
        if not _tech_comments(cs, team):
            continue
        last = max(cs, key=lambda c: c.created_at)
        if now - last.created_at > STALLED_AFTER:
            out.append((t, last))
    return out


def group_by_assignee(items: list, key=lambda x: x) -> list[tuple[str | None, str | None, list]]:
    """(assignee name, email, items) — biggest group first, Unassigned last, oldest task first."""
    groups: dict[str | None, list] = {}
    emails: dict[str | None, str | None] = {}
    for it in items:
        t = key(it)
        groups.setdefault(t.assignee_name, []).append(it)
        emails.setdefault(t.assignee_name, t.assignee_email)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] is None, -len(kv[1]), kv[0] or ""))
    return [(name, emails[name], sorted(its, key=lambda x: key(x).created_at)) for name, its in ordered]
