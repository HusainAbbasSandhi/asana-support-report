"""Pure report logic: counts and lists computed from tasks + their comments."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from digest_bot.models import Comment, Task

OPEN_LONG = timedelta(hours=96)
NO_REPLY_AFTER = timedelta(hours=48)
STALLED_AFTER = timedelta(hours=24)
SUPPORT_REPLY_AFTER = timedelta(hours=3)


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
    # A due date means Prod & Tech has committed to a timeline, so the task is not chased.
    no_reply = [t for t in tasks
                if not t.due_on and now - t.created_at > NO_REPLY_AFTER
                and not _tech_comments(comments.get(t.gid, []), team)]
    counts = Counter(team.get(t.created_by_gid, "Unknown") for t in tasks)
    return DailyReport(
        open=len(tasks),
        over_4d=sum(1 for t in tasks if now - t.created_at > OPEN_LONG),
        assigned_to_support=sum(1 for t in tasks if t.assignee_gid in team),
        no_reply=no_reply,
        raised_by=sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
    )


def stalled_report(tasks: list[Task], comments: dict[str, list[Comment]], team: dict,
                   now: datetime) -> list[tuple[Task, Comment | None]]:
    """Requests where Prod & Tech have gone quiet. Only Prod & Tech comments count: a support
    agent chasing for an update does not reset the clock.

    Nothing counts in a request's first 2 days. After that: no Prod & Tech reply at all -> stalled
    (returned with None); otherwise stalled when the latest Prod & Tech comment is older than 24h
    (returned with that comment).
    """
    out = []
    for t in tasks:
        if t.due_on or now - t.created_at <= NO_REPLY_AFTER:
            continue
        tech = _tech_comments(comments.get(t.gid, []), team)
        if not tech:
            out.append((t, None))
            continue
        last_tech = max(tech, key=lambda c: c.created_at)
        if now - last_tech.created_at > STALLED_AFTER:
            out.append((t, last_tech))
    return out


def support_pending(tasks: list[Task], comments: dict[str, list[Comment]], team: dict,
                    now: datetime) -> list[tuple[Task, Comment, list[str]]]:
    """Requests where Prod & Tech @-tagged a support agent who has not replied for 3h+ (Husain, 19 Nov).

    Prod & Tech chatting among themselves does not need support. What counts is the latest Prod & Tech
    comment that tags someone on the support team: if none of the tagged agents has commented since
    (any of their accounts) and it is older than 3 hours, the request is flagged. Returned as
    (task, tagging comment, tagged agent names), longest waiting first. Due dates do not exclude.
    """
    out = []
    for t in tasks:
        named = sorted((c for c in comments.get(t.gid, []) if c.author_gid), key=lambda c: c.created_at)
        tagging = [c for c in named if c.author_gid not in team and any(g in team for g in c.mentions)]
        if not tagging:
            continue
        ask = tagging[-1]
        tagged = list(dict.fromkeys(team[g] for g in ask.mentions if g in team))
        answered = any(c.created_at > ask.created_at and team.get(c.author_gid) in tagged for c in named)
        if not answered and now - ask.created_at > SUPPORT_REPLY_AFTER:
            out.append((t, ask, tagged))
    return sorted(out, key=lambda it: it[1].created_at)


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
