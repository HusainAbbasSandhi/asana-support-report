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


def _footer(config: dict) -> dict:
    ws = config["asana"]["workspace"]
    bug = PROJECT_URL.format(workspace=ws, gid=config["asana"]["bug_tracking"])
    req = PROJECT_URL.format(workspace=ws, gid=config["asana"]["requests_to_tech"])
    return _section(f"🔗 <{bug}|Open Bug Tracking> · <{req}|Open Requests to Tech Team>")


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


TABLE_ROWS = [
    ("Open tickets raised by support", "open"),
    ("Open for more than 4 days", "over_4d"),
    ("Assigned to a support team member", "assigned_to_support"),
]


def build_daily(report: DailyReport, config: dict, now: datetime, tag: Tag) -> dict:
    mentions = " ".join(f"<@{u}>" for u in config["slack"]["mention_user_ids"])
    header = f"🛠️ Tech Requests — Daily Digest · {_date(now, config)}"
    rows = [("Metric", "Count")] + [(label, str(getattr(report, attr))) for label, attr in TABLE_ROWS]
    rows.append(("No Product & Tech reply in 2+ days", str(len(report.no_reply))))
    table = {
        "type": "table",
        "column_settings": [{"is_wrapped": True}, {"align": "right"}],
        "rows": [[_cell(a), _cell(b)] for a, b in rows],
    }
    blocks = [
        _section(f"*{header}*\ncc {mentions}\n_Open tickets raised by the support team · "
                 f"Bug Tracking + Requests to Tech Team_"),
        table,
    ]
    if report.raised_by:
        blocks.append(_section("Raised by: " + " · ".join(f"{escape(n)} {c}" for n, c in report.raised_by)))
    blocks.append({"type": "divider"})
    blocks.append(_section(f"*⏳ No Product & Tech reply in 2+ days — {len(report.no_reply)}*"))
    if report.no_reply:
        blocks += _groups(report.no_reply, lambda t: t, "waiting",
                          lambda t: f"• {_link(t)} — {_days(max(0, (now - t.created_at).days))}", tag)
    else:
        blocks.append(_section("✅ Every ticket older than 2 days has a Product & Tech reply"))
    blocks += [{"type": "divider"}, _footer(config)]
    return {"text": f"{header} — cc {mentions}", "blocks": blocks[:50]}


def build_stalled(items: list[tuple[Task, Comment]], config: dict, now: datetime, tag: Tag) -> dict:
    header = f"⏰ Stalled conversations · {_date(now, config)}"
    blocks = [_section(f"*{header}*\n_Open support tickets where Product & Tech replied, "
                       f"but nobody has commented for 24h+_")]

    def bullet(item):
        task, last = item
        ago = _days(max(1, (now - last.created_at).days))
        who = f" by {escape(last.author_name)}" if last.author_name else ""
        return f"• {_link(task)} — last comment {ago} ago{who}"

    if items:
        blocks += _groups(items, lambda it: it[0], "stalled", bullet, tag)
    else:
        blocks.append(_section("✅ No stalled conversations today"))
    blocks += [{"type": "divider"}, _footer(config)]
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
