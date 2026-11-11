"""Build Slack payloads for the daily digest and the stalled-conversations report. Pure: no I/O."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from digest_bot.metrics import DailyReport, group_by_assignee
from digest_bot.models import Comment, Task

BLOCK_TEXT_MAX = 3000
PROJECT_URL = "https://app.asana.com/1/{workspace}/project/{gid}"

def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


NAME_MAX = 55
TABLE_ROWS_MAX = 99  # Slack allows 100 rows per table, header included


def _cell(text: str) -> dict:
    return {"type": "raw_text", "text": text}


def _link_cell(task: Task) -> dict:
    name = task.name if len(task.name) <= NAME_MAX else task.name[: NAME_MAX - 1] + "…"
    if not task.url:
        return _cell(name)
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
        {"type": "link", "url": task.url, "text": name}]}]}


def _person(name: str | None) -> str:
    """Asana users without a display name show their email; turn akash.mathur@x into Akash Mathur."""
    if not name:
        return "Unassigned"
    if "@" in name:
        return " ".join(part.capitalize() for part in re.split(r"[._-]", name.split("@")[0]) if part)
    return name


def _table(header: list[str], rows: list[list[dict]], settings: list[dict]) -> dict:
    return {"type": "table", "column_settings": settings,
            "rows": [[_cell(h) for h in header], *rows[:TABLE_ROWS_MAX]]}


def _ordered(items: list, key) -> list:
    """Biggest assignee group first, Unassigned last, oldest request first within a group."""
    return [it for _, _, its in group_by_assignee(items, key=key) for it in its]


def _more(items: list) -> list[dict]:
    hidden = len(items) - TABLE_ROWS_MAX
    return [_section(f"_+{hidden} more in Asana_")] if hidden > 0 else []


NO_REPLY_LABEL = "First response pending by Prod & Tech (2+ days)"
TABLE_ROWS = [
    ("Open requests pending on Prod & Tech", "open"),
    ("Open for more than 4 days", "over_4d"),
    ("Assigned to a support team member", "assigned_to_support"),
]
RIGHT = {"align": "right"}
WRAP = {"is_wrapped": True}


def _daily_section(key: str, emoji: str, label: str, report: DailyReport, config: dict,
                   now: datetime) -> list[dict]:
    team = config["asana"].get("support_team") or {}
    metrics = [[_cell(name), _cell(str(getattr(report, attr)))] for name, attr in TABLE_ROWS]
    metrics.append([_cell(NO_REPLY_LABEL), _cell(str(len(report.no_reply)))])
    blocks = [
        {"type": "divider"},
        _section(f"*{emoji} {label.upper()}*"),
        _table(["Metric", "Count"], metrics, [WRAP, RIGHT]),
    ]
    if report.raised_by:
        blocks += [_section("*Raised by*"),
                   _table(["Support agent", "Open requests"],
                          [[_cell(n), _cell(str(c))] for n, c in report.raised_by], [WRAP, RIGHT])]
    blocks.append(_section(f"*⏳ {escape(NO_REPLY_LABEL)} — {len(report.no_reply)}*\n"
                           f"_Requests with a due date are not included_"))
    if report.no_reply:
        tasks = _ordered(report.no_reply, lambda t: t)
        rows = [[_cell(str(i)), _link_cell(t), _cell(team.get(t.created_by_gid, "—")),
                 _cell(_person(t.assignee_name)), _cell(_days(max(0, (now - t.created_at).days)))]
                for i, t in enumerate(tasks, 1)]
        blocks.append(_table(["#", "Request", "Raised by", "Assigned to", "Waiting since raised"],
                             rows, [RIGHT, WRAP, WRAP, WRAP, WRAP]))
        blocks += _more(tasks)
    else:
        blocks.append(_section("✅ Every request older than 2 days has a first response from Prod &amp; Tech"))
    blocks.append(_project_link(key, label, config))
    return blocks


def build_daily(reports: dict[str, DailyReport], config: dict, now: datetime) -> dict:
    """One message, one section per project in PROJECTS."""
    mentions = " ".join(f"<@{u}>" for u in config["slack"]["mention_user_ids"])
    header = f"🛠️ Tech Requests — Daily Digest · {_date(now, config)}"
    blocks = [_section(f"*{header}*\ncc {mentions}\n_Open requests raised by the support team_")]
    for key, emoji, label in PROJECTS:
        blocks += _daily_section(key, emoji, label, reports.get(key) or DailyReport(0, 0, 0), config, now)
    return {"text": f"{header} — cc {mentions}", "blocks": blocks[:50]}


def build_stalled(items: dict[str, list[tuple[Task, Comment | None]]], config: dict, now: datetime) -> dict:
    team = config["asana"].get("support_team") or {}
    header = f"⏰ Stalled conversations · {_date(now, config)}"
    blocks = [_section(f"*{header}*\n_Open support requests where Prod &amp; Tech have not replied for 24h+, or not at all "
                       f"after 2 days · support follow-ups don't count · requests with a due date are not included_")]

    def row(i: int, item) -> list[dict]:
        task, last = item
        if last is None:
            since = f"No reply yet (raised {_days(max(0, (now - task.created_at).days))} ago)"
            by = "—"
        else:
            since = _days(max(1, (now - last.created_at).days))
            by = _person(last.author_name) if last.author_name else "—"
        return [_cell(str(i)), _link_cell(task), _cell(team.get(task.created_by_gid, "—")),
                _cell(_person(task.assignee_name)), _cell(since), _cell(by)]

    for key, emoji, label in PROJECTS:
        its = _ordered(items.get(key) or [], lambda it: it[0])
        blocks += [{"type": "divider"}, _section(f"*{emoji} {label.upper()} — {len(its)} stalled*")]
        if its:
            blocks.append(_table(["#", "Request", "Raised by", "Assigned to", "Since last Prod & Tech reply",
                                  "Replied by"], [row(i, it) for i, it in enumerate(its, 1)],
                                 [RIGHT, WRAP, WRAP, WRAP, WRAP, WRAP]))
            blocks += _more(its)
        else:
            blocks.append(_section("✅ No stalled conversations"))
        blocks.append(_project_link(key, label, config))
    return {"text": header, "blocks": blocks[:50]}


def _cell_text(cell: dict) -> str:
    if cell["type"] == "raw_text":
        return cell["text"]
    return "".join(el.get("text", "") for sec in cell.get("elements", []) for el in sec.get("elements", []))


def _pad(row: list[str], widths: list[int]) -> str:
    return "  ".join(v.ljust(w) for v, w in zip(row, widths)).rstrip()


def monospace_fallback(payload: dict) -> dict:
    """Same message with every table block rendered as a monospace code block."""
    blocks = []
    for b in payload["blocks"]:
        if b["type"] != "table":
            blocks.append(b)
            continue
        rows = [[_cell_text(c) for c in row] for row in b["rows"]]
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        lines = [_pad(rows[0], widths), "  ".join("-" * w for w in widths), *(_pad(r, widths) for r in rows[1:])]
        blocks.append(_section("```\n" + "\n".join(lines) + "\n```"))
    return {**payload, "blocks": blocks}
