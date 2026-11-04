"""Build the Slack digest payload from normalised tasks. Pure: no I/O."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from digest_bot.models import Task

TITLE_MAX = 90
BLOCK_TEXT_MAX = 3000
HIGH_PRIORITIES = ("Critical", "High")
PROJECT_URL = "https://app.asana.com/1/{workspace}/project/{gid}"


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _title(task: Task) -> str:
    name = task.name
    if len(name) > TITLE_MAX:
        name = name[: TITLE_MAX - 1] + "…"
    return escape(name)


def _age_days(task: Task, now: datetime) -> int:
    return max(0, (now - task.created_at).days)


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _bullet(task: Task, parts: list[str | None]) -> str:
    meta = [p for p in parts if p]
    meta.append(f"→ {escape(task.assignee_name) if task.assignee_name else 'unassigned'}")
    link = f"<{task.url}|{_title(task)}>" if task.url else _title(task)
    return f"• {link} — {' · '.join(meta)}"


def _priority_rank(task: Task) -> int:
    return HIGH_PRIORITIES.index(task.priority) if task.priority in HIGH_PRIORITIES else len(HIGH_PRIORITIES)


def _sort(tasks: list[Task]) -> list[Task]:
    return sorted(tasks, key=lambda t: (_priority_rank(t), t.created_at))


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _list_block(title: str, bullets: list[str], cap: int) -> dict | None:
    """One section block: title + up to `cap` bullets + '+N more', kept under Slack's 3000-char limit."""
    if not bullets:
        return None
    shown = bullets[:cap]
    while True:
        hidden = len(bullets) - len(shown)
        lines = [title, *shown]
        if hidden:
            lines.append(f"_+{hidden} more_")
        text = "\n".join(lines)
        if len(text) <= BLOCK_TEXT_MAX or not shown:
            return _section(text[:BLOCK_TEXT_MAX])
        shown = shown[:-1]


def _is_blocked(t: Task) -> bool:
    return t.section_name == "Blocked" or t.status == "Blocked"


def _esc(v: str | None) -> str | None:
    return escape(v) if v else None


def _bug_blocks(tasks: list[Task], now: datetime, cutoff: datetime, limits: dict) -> list[dict]:
    new = [t for t in tasks if t.created_at >= cutoff]
    high = [t for t in tasks if t.priority in HIGH_PRIORITIES]
    blocked = [t for t in tasks if _is_blocked(t)]
    unassigned = [t for t in tasks if not t.assignee_name]

    summary = f"*🐞 BUG TRACKING — {len(tasks)} open*"
    if not tasks:
        return [_section(summary + "\n✅ Nothing open")]
    summary += (f"  (🆕 {len(new)} new · 🔴 {len(high)} Critical/High · "
                f"🚫 {len(blocked)} Blocked · 👤 {len(unassigned)} unassigned)")

    def bug_bullet(t: Task) -> str:
        return _bullet(t, [_esc(t.priority), _esc(t.module), f"by {escape(t.requester)}" if t.requester else None])

    oldest = sorted(tasks, key=lambda t: t.created_at)
    blocks = [
        _section(summary),
        _list_block("*🆕 New since yesterday*", [bug_bullet(t) for t in _sort(new)], limits["list_max"]),
        _list_block("*🔴 Critical / High still open*", [bug_bullet(t) for t in _sort(high)], limits["list_max"]),
        _list_block("*⏳ Oldest open*", [_bullet(t, [_days(_age_days(t, now))]) for t in oldest], limits["oldest_max"]),
    ]
    return [b for b in blocks if b]


def _request_blocks(tasks: list[Task], now: datetime, cutoff: datetime, limits: dict) -> list[dict]:
    summary = f"*📋 REQUESTS TO TECH TEAM — {len(tasks)} open*"
    if not tasks:
        return [_section(summary + "\n✅ Nothing open")]
    new = [t for t in tasks if t.created_at >= cutoff]
    summary += f"  (🆕 {len(new)} new)"
    counts = Counter(t.section_name or "No section" for t in tasks)  # insertion order = first appearance
    summary += "\n" + " · ".join(f"{escape(name)} {n}" for name, n in counts.items())

    oldest = sorted(tasks, key=lambda t: t.created_at)
    blocks = [
        _section(summary),
        _list_block("*🆕 New since yesterday*",
                    [_bullet(t, [_esc(t.section_name)]) for t in _sort(new)], limits["list_max"]),
        _list_block("*⏳ Oldest open*",
                    [_bullet(t, [_days(_age_days(t, now)), _esc(t.section_name)]) for t in oldest],
                    limits["oldest_max"]),
    ]
    return [b for b in blocks if b]


def build_digest(bug_tasks: list[Task], request_tasks: list[Task], config: dict, now: datetime) -> dict:
    limits = config["limits"]
    cutoff = now - timedelta(hours=limits["new_window_hours"])
    local = now.astimezone(ZoneInfo(config["timezone"]))
    date = f"{local:%A}, {local.day} {local:%b}"
    mentions = " ".join(f"<@{uid}>" for uid in config["slack"]["mention_user_ids"])
    header = f"🛠️ Tech Requests — Daily Digest · {date}"

    ws = config["asana"]["workspace"]
    bug_url = PROJECT_URL.format(workspace=ws, gid=config["asana"]["bug_tracking"])
    req_url = PROJECT_URL.format(workspace=ws, gid=config["asana"]["requests_to_tech"])

    blocks = [
        _section(f"*{header}*\ncc {mentions}"),
        {"type": "divider"},
        *_bug_blocks(bug_tasks, now, cutoff, limits),
        {"type": "divider"},
        *_request_blocks(request_tasks, now, cutoff, limits),
        {"type": "divider"},
        _section(f"🔗 <{bug_url}|Open Bug Tracking> · <{req_url}|Open Requests to Tech Team>"),
    ]
    return {"text": f"{header} — cc {mentions}", "blocks": blocks}
