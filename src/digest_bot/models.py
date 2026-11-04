"""Normalise raw Asana task JSON into a flat Task record."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Custom field GIDs (Bug Tracking). Referenced by GID because two fields share the name "Priority".
PRIORITY_A = "1202861948139129"  # Critical / High / Moderate / Low
PRIORITY_B = "1200058217049452"  # High / Medium / Low
STATUS = "1205244304819066"
MODULE = "1215418181758775"
FEATURE = "1202853926214497"  # legacy module field
REQUESTER = "1208648898989523"  # enum
REPORTER = "1216285168420620"  # people

ASANA_OPT_FIELDS = (
    "name,permalink_url,created_at,due_on,due_at,created_by.gid,assignee.gid,assignee.name,assignee.email,"
    "memberships.project.gid,"
    "memberships.section.name,custom_fields.gid,custom_fields.enum_value.name,"
    "custom_fields.multi_enum_values.name,custom_fields.people_value.name"
)


@dataclass(frozen=True)
class Task:
    gid: str
    name: str
    url: str
    created_at: datetime
    assignee_name: str | None
    section_name: str | None
    priority: str | None
    status: str | None
    requester: str | None
    module: str | None
    created_by_gid: str | None = None
    assignee_gid: str | None = None
    assignee_email: str | None = None
    due_on: str | None = None  # Asana due_on (date) or due_at (datetime); None when no due date


@dataclass(frozen=True)
class Comment:
    created_at: datetime
    author_gid: str | None
    author_name: str | None


STORY_OPT_FIELDS = "resource_subtype,created_at,created_by.gid,created_by.name"


def comments_from_stories(stories: list[dict]) -> list[Comment]:
    """Keep only real comments (not system events), oldest first."""
    out = []
    for s in stories or []:
        if s.get("resource_subtype") != "comment_added" or not s.get("created_at"):
            continue
        author = s.get("created_by") or {}
        out.append(Comment(_parse_ts(s["created_at"]), _clean(author.get("gid")), _clean(author.get("name"))))
    return sorted(out, key=lambda c: c.created_at)


def raised_by(tasks: list[Task], creator_gids) -> list[Task]:
    """Keep tasks created by one of `creator_gids`. An empty/missing list means no filter."""
    if not creator_gids:
        return list(tasks)
    allowed = {str(g) for g in creator_gids}
    return [t for t in tasks if t.created_by_gid in allowed]


def _clean(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _enum(fields: dict, gid: str) -> str | None:
    f = fields.get(gid) or {}
    return _clean((f.get("enum_value") or {}).get("name"))


def _multi(fields: dict, gid: str) -> str | None:
    f = fields.get(gid) or {}
    names = [_clean(v.get("name")) for v in (f.get("multi_enum_values") or [])]
    names = [n for n in names if n]
    return "/".join(names) or None


def _people(fields: dict, gid: str) -> str | None:
    f = fields.get(gid) or {}
    names = [_clean(p.get("name")) for p in (f.get("people_value") or [])]
    names = [n for n in names if n]
    return ", ".join(names) or None


def _section(raw: dict, project_gid: str) -> str | None:
    for m in raw.get("memberships") or []:
        if ((m.get("project") or {}).get("gid")) == project_gid:
            return _clean((m.get("section") or {}).get("name"))
    return None


def _parse_ts(value: str) -> datetime:
    # Asana returns e.g. "2026-11-03T20:00:00.000Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def from_asana(raw: dict, project_gid: str) -> Task:
    fields = {f.get("gid"): f for f in (raw.get("custom_fields") or [])}
    return Task(
        gid=str(raw.get("gid")),
        name=_clean(raw.get("name")) or "(untitled)",
        url=raw.get("permalink_url") or "",
        created_at=_parse_ts(raw["created_at"]),
        assignee_name=_clean((raw.get("assignee") or {}).get("name")),
        section_name=_section(raw, project_gid),
        priority=_enum(fields, PRIORITY_A) or _enum(fields, PRIORITY_B),
        status=_enum(fields, STATUS),
        requester=_enum(fields, REQUESTER) or _people(fields, REPORTER),
        module=_multi(fields, MODULE) or _multi(fields, FEATURE),
        created_by_gid=_clean((raw.get("created_by") or {}).get("gid")),
        assignee_gid=_clean((raw.get("assignee") or {}).get("gid")),
        assignee_email=_clean((raw.get("assignee") or {}).get("email")),
        due_on=_clean(raw.get("due_on")) or _clean(raw.get("due_at")),
    )
