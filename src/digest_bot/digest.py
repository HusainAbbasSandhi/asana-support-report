"""Build Slack payloads for the daily digest and the stalled-conversations report. Pure: no I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from digest_bot.metrics import DailyReport, group_by_assignee
from digest_bot.models import Comment, Task

TITLE_MAX = 90
BLOCK_TEXT_MAX = 3000
GROUP_MAX = 10
PROJECT_URL = "https://app.asana.com/1/{workspace}/project/{gid}"

Tag = Callable[[str | None, str | None], str]  # (assignee name, email) -> "<@U…>" or "*Name*"


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _title(task: Task) -> str:
    name = task.name if len(task.name) <= TITLE_MAX else task.name[: TITLE_MAX - 1] + "…"
    return escape(name)


def _link(task: Task) -> str:
    return f"<{task.url}|{_title(task)}>" if task.url else _title(task)


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:BLOCK_TEXT_MAX]}}


def _date(now: datetime, config: dict) -> str:
    local = now.astimezone(ZoneInfo(config["timezone"]))
    return f"{local:%A}, {local.day} {local:%b}"


# Only Bug Tracking is reported (Husain, 10 Nov). To bring Requests to Tech Team back, add:
# ("requests_to_tech", "📨", "Requests to Tech Team")
PROJECTS = (("bug_tracking", "🐞", "Bug Tracking"),)


def _project_link(key: str, label: str, config: dict) -> dict:
    url = PROJECT_URL.format(workspace=config["asana"]["workspace"], gid=config["asana"][key])
    return _section(f"🔗 <{url}|Open {label}>")


def _group_block(heading: str, bullets: list[str]) -> dict:
    """Heading + up to GROUP_MAX bullets + '+N more', kept under Slack's per-block limit."""
    shown = bullets[:GROUP_MAX]
    while True:
        hidden = len(bullets) - len(shown)
        text = "\n".join([heading, *shown, *([f"_+{hidden} more_"] if hidden else [])])
        if len(text) <= BLOCK_TEXT_MAX or not shown:
            return _section(text)
        shown = shown[:-1]


def _groups(items: list, key, noun: str, bullet: Callable, tag: Tag) -> list[dict]:
    return [_group_block(f"{tag(name, email)} — {len(its)} {noun}", [bullet(it) for it in its])
            for name, email, its in group_by_assignee(items, key=key)]


def _cell(text: str) -> dict:
    return {"type": "raw_text", "text": text}


NO_REPLY_LABEL = "First response pending by Prod & Tech (2+ days)"
TABLE_ROWS = [
    ("Open requests pending on Prod & Tech", "open"),
    ("Open for more than 4 days", "over_4d"),
    ("Assigned to a support team member", "assigned_to_support"),
]


def _daily_section(key: str, emoji: str, label: str, report: DailyReport, config: dict,
                   now: datetime, tag: Tag) -> list[dict]:
    rows = [("Metric", "Count")] + [(name, str(getattr(report, attr))) for name, attr in TABLE_ROWS]
    rows.append((NO_REPLY_LABEL, str(len(report.no_reply))))
    blocks = [
        {"type": "divider"},
        _section(f"*{emoji} {label.upper()}*"),
        {"type": "table", "column_settings": [{"is_wrapped": True}, {"align": "right"}],
         "rows": [[_cell(a), _cell(b)] for a, b in rows]},
    ]
    if report.raised_by:
        blocks.append(_section("Raised by: " + " · ".join(f"{escape(n)} {c}" for n, c in report.raised_by)))
    blocks.append(_section(f"*⏳ {escape(NO_REPLY_LABEL)} — {len(report.no_reply)}*\n"
                           f"_Requests with a due date are not included_"))
    if report.no_reply:
        blocks += _groups(report.no_reply, lambda t: t, "waiting",
                          lambda t: f"• {_link(t)} — {_days(max(0, (now - t.created_at).days))}", tag)
    else:
        blocks.append(_section("✅ Every request older than 2 days has a first response from Prod &amp; Tech"))
    blocks.append(_project_link(key, label, config))
    return blocks


def build_daily(reports: dict[str, DailyReport], config: dict, now: datetime, tag: Tag) -> dict:
    """One message, one section per project: Bug Tracking first, then Requests to Tech Team."""
    mentions = " ".join(f"<@{u}>" for u in config["slack"]["mention_user_ids"])
    header = f"🛠️ Tech Requests — Daily Digest · {_date(now, config)}"
    blocks = [_section(f"*{header}*\ncc {mentions}\n_Open requests raised by the support team_")]
    for key, emoji, label in PROJECTS:
        blocks += _daily_section(key, emoji, label, reports.get(key) or DailyReport(0, 0, 0), config, now, tag)
    return {"text": f"{header} — cc {mentions}", "blocks": blocks[:50]}


def build_stalled(items: dict[str, list[tuple[Task, Comment | None]]], config: dict, now: datetime, tag: Tag) -> dict:
    header = f"⏰ Stalled conversations · {_date(now, config)}"
    blocks = [_section(f"*{header}*\n_Open support requests where Prod &amp; Tech have not replied for 24h+, or not at all "
                       f"after 2 days · support follow-ups don't count · requests with a due date are not included_")]

    def bullet(item):
        task, last = item
        if last is None:
            raised = _days(max(0, (now - task.created_at).days))
            return f"• {_link(task)} — no reply from Prod &amp; Tech yet · raised {raised} ago"
        ago = _days(max(1, (now - last.created_at).days))
        who = f" by {escape(last.author_name)}" if last.author_name else ""
        return f"• {_link(task)} — last Prod &amp; Tech reply {ago} ago{who}"

    for key, emoji, label in PROJECTS:
        its = items.get(key) or []
        blocks += [{"type": "divider"}, _section(f"*{emoji} {label.upper()} — {len(its)} stalled*")]
        if its:
            blocks += _groups(its, lambda it: it[0], "stalled", bullet, tag)
        else:
            blocks.append(_section("✅ No stalled conversations"))
        blocks.append(_project_link(key, label, config))
    return {"text": header, "blocks": blocks[:50]}


def monospace_fallback(payload: dict) -> dict:
    """Same message with the table block rendered as a monospace code block."""
    blocks = []
    for b in payload["blocks"]:
        if b["type"] != "table":
            blocks.append(b)
            continue
        rows = [[c["text"] for c in row] for row in b["rows"]]
        width = max(len(r[0]) for r in rows)
        lines = [f"{rows[0][0]:<{width}}  {rows[0][1]:>5}", f"{'-' * width}  -----"]
        lines += [f"{a:<{width}}  {n:>5}" for a, n in rows[1:]]
        blocks.append(_section("```\n" + "\n".join(lines) + "\n```"))
    return {**payload, "blocks": blocks}
