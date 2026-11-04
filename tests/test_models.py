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


def test_load_config_reads_ids():
    cfg = load_config(str(Path(__file__).parent.parent / "config.yaml"))
    assert cfg["slack"]["channel"] == "C075PCA1NF7"
    assert cfg["asana"]["bug_tracking"] == BUG_GID
    assert cfg["limits"]["list_max"] == 10
