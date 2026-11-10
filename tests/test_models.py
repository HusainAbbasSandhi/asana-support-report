import copy
import json
from pathlib import Path

import pytest

from digest_bot.config import load_config
from digest_bot.models import from_asana

FIX = Path(__file__).parent / "fixtures"
BUG_GID = "1202029361021711"
REQ_GID = "1208716124012867"


@pytest.fixture
def bug_raw():
    return json.loads((FIX / "bug_task.json").read_text(encoding="utf-8"))


@pytest.fixture
def req_raw():
    return json.loads((FIX / "request_task.json").read_text(encoding="utf-8"))


def _field(raw, gid):
    return next(f for f in raw["custom_fields"] if f["gid"] == gid)


def test_priority_prefers_field_a_and_trims(bug_raw):
    assert from_asana(bug_raw, BUG_GID).priority == "High"


def test_priority_falls_back_to_field_b(bug_raw):
    _field(bug_raw, "1202861948139129")["enum_value"] = None
    assert from_asana(bug_raw, BUG_GID).priority == "Low"


def test_section_from_matching_project_membership(bug_raw):
    assert from_asana(bug_raw, BUG_GID).section_name == "Blocked"


def test_status_read(bug_raw):
    assert from_asana(bug_raw, BUG_GID).status == "In Progress"


def test_module_joined_with_slash(bug_raw):
    assert from_asana(bug_raw, BUG_GID).module == "Loyalty/Campaigns"


def test_module_falls_back_to_feature_field(bug_raw):
    _field(bug_raw, "1215418181758775")["multi_enum_values"] = []
    assert from_asana(bug_raw, BUG_GID).module == "Feedback"


def test_requester_enum_then_reporter_people_fallback(bug_raw):
    assert from_asana(bug_raw, BUG_GID).requester == "Dimple Manglani"
    _field(bug_raw, "1208648898989523")["enum_value"] = None
    assert from_asana(bug_raw, BUG_GID).requester == "Lay Patel"


def test_request_task_has_none_fields(req_raw):
    t = from_asana(req_raw, REQ_GID)
    assert t.priority is None and t.assignee_name is None
    assert t.section_name == "Other requests"
    assert t.module is None and t.requester is None and t.status is None


def test_created_at_is_utc_aware(bug_raw):
    t = from_asana(bug_raw, BUG_GID)
    assert t.created_at.tzinfo is not None
    assert t.created_at.hour == 20


def test_null_name_becomes_untitled(req_raw):
    req_raw["name"] = None
    assert from_asana(req_raw, REQ_GID).name == "(untitled)"
    req_raw["name"] = "   "
    assert from_asana(req_raw, REQ_GID).name == "(untitled)"


def test_basic_fields(bug_raw):
    t = from_asana(bug_raw, BUG_GID)
    assert t.gid == "111"
    assert t.name == "OTP <fails> & SMS"
    assert t.url.endswith("/task/111")
    assert t.assignee_name == "Joel Gnan"


def test_created_by_gid_read(bug_raw, req_raw):
    assert from_asana(bug_raw, BUG_GID).created_by_gid == "1213456649719771"
    req_raw["created_by"] = None  # Asana returns null for some very old tasks
    assert from_asana(req_raw, REQ_GID).created_by_gid is None


def test_opt_fields_request_creator():
    from digest_bot.models import ASANA_OPT_FIELDS
    assert "created_by.gid" in ASANA_OPT_FIELDS


def test_raised_by_filters_on_creator(bug_raw, req_raw):
    from digest_bot.models import raised_by
    bug, req = from_asana(bug_raw, BUG_GID), from_asana(req_raw, REQ_GID)
    assert raised_by([bug, req], ["1213456649719771"]) == [bug]
    assert raised_by([bug, req], ["1213456649719771", "1211520249551622"]) == [bug, req]
    assert raised_by([bug, req], ["someone-else"]) == []


def test_raised_by_empty_list_means_no_filter(bug_raw, req_raw):
    from digest_bot.models import raised_by
    tasks = [from_asana(bug_raw, BUG_GID), from_asana(req_raw, REQ_GID)]
    assert raised_by(tasks, []) == tasks
    assert raised_by(tasks, None) == tasks


def test_config_support_team_ids():
    cfg = load_config(str(Path(__file__).parent.parent / "config.yaml"))
    team = cfg["asana"]["support_team"]
    for gid in ["1213708140273045", "1213456649719771", "1209630028448041", "1212000756732376",
                "1212745386205914", "1211520249551622", "1211616394608433"]:
        assert gid in team
    assert all(isinstance(g, str) for g in team)
    assert isinstance(team, dict)
    for vishal in ["1209630028448041", "1209520614296294", "1209566934451998"]:
        assert team[vishal] == "Vishal Naidu"


def test_raised_by_accepts_mapping(bug_raw):
    from digest_bot.models import raised_by
    bug = from_asana(bug_raw, BUG_GID)
    assert raised_by([bug], {"1213456649719771": "Haydar Abbas"}) == [bug]


def test_assignee_gid_and_email(bug_raw, req_raw):
    bug_raw["assignee"]["email"] = "joel.gnan@reelo.io"
    t = from_asana(bug_raw, BUG_GID)
    assert t.assignee_gid == "1202713496056982"
    assert t.assignee_email == "joel.gnan@reelo.io"
    r = from_asana(req_raw, REQ_GID)
    assert r.assignee_gid is None and r.assignee_email is None


def test_due_date_read_from_due_on_or_due_at(bug_raw):
    assert from_asana(bug_raw, BUG_GID).due_on is None
    bug_raw["due_on"] = "2026-11-20"
    assert from_asana(bug_raw, BUG_GID).due_on == "2026-11-20"
    bug_raw["due_on"] = None
    bug_raw["due_at"] = "2026-11-20T10:00:00.000Z"
    assert from_asana(bug_raw, BUG_GID).due_on == "2026-11-20T10:00:00.000Z"
    from digest_bot.models import ASANA_OPT_FIELDS
    assert "due_on" in ASANA_OPT_FIELDS and "due_at" in ASANA_OPT_FIELDS


def test_opt_fields_request_assignee_email():
    from digest_bot.models import ASANA_OPT_FIELDS
    assert "assignee.email" in ASANA_OPT_FIELDS and "assignee.gid" in ASANA_OPT_FIELDS


def test_comments_from_stories_keeps_only_comments_sorted():
    from digest_bot.models import comments_from_stories
    stories = [
        {"resource_subtype": "comment_added", "created_at": "2026-11-03T10:00:00.000Z",
         "created_by": {"gid": "u2", "name": "Joel"}},
        {"resource_subtype": "assigned", "created_at": "2026-11-01T10:00:00.000Z",
         "created_by": {"gid": "u9", "name": "Bot"}},
        {"resource_subtype": "comment_added", "created_at": "2026-11-02T10:00:00.000Z",
         "created_by": None},
    ]
    cs = comments_from_stories(stories)
    assert [c.author_name for c in cs] == [None, "Joel"]
    assert cs[1].author_gid == "u2"
    assert cs[0].created_at.day == 2


def test_load_config_reads_ids():
    cfg = load_config(str(Path(__file__).parent.parent / "config.yaml"))
    assert cfg["slack"]["channel"] in ("C075PCA1NF7", "C0CF6BY6KHS")  # #tech-cs-issues, or #test-channel while paused
    assert cfg["asana"]["bug_tracking"] == BUG_GID
    assert cfg["limits"]["list_max"] == 10
