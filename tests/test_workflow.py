from pathlib import Path

import yaml

WF = Path(__file__).parent.parent / ".github" / "workflows"


def _load(name):
    data = yaml.safe_load((WF / name).read_text(encoding="utf-8-sig"))
    return data, data.get("on", data.get(True))  # PyYAML parses bare `on:` as True


def _runs(data):
    return " ".join(s.get("run", "") for job in data["jobs"].values() for s in job["steps"])


def _ist_minutes(cron):
    minute, hour, *_ = cron.split()
    return (int(hour) * 60 + int(minute) + 330) % (24 * 60)


def test_daily_runs_just_before_10_ist_with_daily_report():
    data, on = _load("digest.yml")
    cron = on["schedule"][0]["cron"]
    assert cron.split()[0] != "0"
    assert 9 * 60 + 50 <= _ist_minutes(cron) <= 10 * 60
    assert "--report daily" in _runs(data) and "pytest" not in _runs(data)


def test_stalled_runs_just_before_14_ist_with_stalled_report():
    data, on = _load("stalled.yml")
    cron = on["schedule"][0]["cron"]
    assert 13 * 60 + 50 <= _ist_minutes(cron) <= 14 * 60
    assert "--report stalled" in _runs(data) and "pytest" not in _runs(data)
    assert "workflow_dispatch" in on


def test_report_workflows_offer_test_channel_option():
    for name in ("digest.yml", "stalled.yml"):
        data, on = _load(name)
        assert on["workflow_dispatch"]["inputs"]["test_channel"]["type"] == "boolean"
        assert "inputs.test_channel && '--test'" in _runs(data)


def test_separate_test_workflow_runs_pytest_on_push():
    data, on = _load("tests.yml")
    assert "push" in on and "pull_request" in on
    assert "pytest" in _runs(data)


def test_manifest_has_lookup_scopes():
    m = yaml.safe_load((Path(__file__).parent.parent / "slack-app-manifest.yaml").read_text(encoding="utf-8"))
    scopes = m["oauth_config"]["scopes"]["bot"]
    assert {"chat:write", "users:read", "users:read.email"} <= set(scopes)
