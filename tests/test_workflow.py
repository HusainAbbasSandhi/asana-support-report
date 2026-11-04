from pathlib import Path

import yaml

WF = Path(__file__).parent.parent / ".github" / "workflows"


def _load(name):
    data = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    return data, data.get("on", data.get(True))  # PyYAML parses bare `on:` as True


def test_digest_job_does_not_run_tests():
    data, _ = _load("digest.yml")
    runs = " ".join(s.get("run", "") for job in data["jobs"].values() for s in job["steps"])
    assert "pytest" not in runs


def test_digest_cron_avoids_top_of_hour_and_lands_near_1030_ist():
    _, on = _load("digest.yml")
    minute, hour, *_ = on["schedule"][0]["cron"].split()
    assert minute != "0"
    ist_minutes = (int(hour) * 60 + int(minute) + 330) % (24 * 60)
    assert 10 * 60 + 20 <= ist_minutes <= 10 * 60 + 30


def test_separate_test_workflow_runs_pytest_on_push():
    data, on = _load("tests.yml")
    assert "push" in on and "pull_request" in on
    runs = " ".join(s.get("run", "") for job in data["jobs"].values() for s in job["steps"])
    assert "pytest" in runs
