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


def _attempts_ist(on):
    """Every scheduled attempt as minutes-after-midnight IST."""
    out = []
    for entry in on["schedule"]:
        minute, hour, *_ = entry["cron"].split()
        for m in minute.split(","):
            out.append((int(hour) * 60 + int(m) + 330) % (24 * 60))
    return sorted(out)


def _step(data, name_part):
    steps = next(iter(data["jobs"].values()))["steps"]
    return next(s for s in steps if name_part in s.get("name", ""))


def _check_window(name, report, start_h):
    data, on = _load(name)
    attempts = _attempts_ist(on)
    assert len(attempts) >= 4, "several attempts so a skipped GitHub trigger doesn't lose the day"
    assert start_h * 60 - 10 <= attempts[0] <= start_h * 60       # first try just before the hour
    assert attempts[-1] <= start_h * 60 + 50                      # last try within the hour
    assert all(a % 60 != 0 for a in attempts)                     # never on the busy :00 minute
    assert f"--report {report}" in _runs(data) and "pytest" not in _runs(data)
    assert "workflow_dispatch" in on


def _check_once_a_day(name, report):
    data, _ = _load(name)
    check = _step(data, "already posted")
    assert check["uses"].startswith("actions/cache/restore@")
    assert check["with"]["lookup-only"] is True
    assert f"sent-{report}-" in check["with"]["key"] and "steps.day.outputs.date" in check["with"]["key"]
    assert check["if"] == "github.event_name == 'schedule'"   # manual/test runs are never blocked
    post = _step(data, "Build and post")
    assert "steps.sent.outputs.cache-hit != 'true'" in post["if"]
    save = _step(data, "Remember")
    assert save["uses"].startswith("actions/cache/save@")
    assert save["with"]["key"] == check["with"]["key"]
    assert "github.event_name == 'schedule'" in save["if"] and "cache-hit != 'true'" in save["if"]
    day = _step(data, "date (IST)")
    assert "Asia/Kolkata" in day["run"]


def test_daily_tries_from_957_to_1047_ist():
    _check_window("digest.yml", "daily", 10)


def test_stalled_tries_from_1357_to_1447_ist():
    _check_window("stalled.yml", "stalled", 14)


def test_daily_posts_once_per_day():
    _check_once_a_day("digest.yml", "daily")


def test_stalled_posts_once_per_day():
    _check_once_a_day("stalled.yml", "stalled")


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
