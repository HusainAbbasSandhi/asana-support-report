import pytest

from digest_bot.asana_client import AsanaError, fetch_open_tasks


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers})
        return self.responses.pop(0)


def test_follows_pagination():
    s = FakeSession([
        FakeResp(200, {"data": [{"gid": "1"}, {"gid": "2"}], "next_page": {"offset": "abc"}}),
        FakeResp(200, {"data": [{"gid": "3"}], "next_page": None}),
    ])
    tasks = fetch_open_tasks("P1", "t", session=s, sleep=lambda _: None)
    assert [t["gid"] for t in tasks] == ["1", "2", "3"]
    assert "offset" not in s.calls[0]["params"]
    assert s.calls[1]["params"]["offset"] == "abc"
    assert s.calls[0]["url"] == "https://app.asana.com/api/1.0/projects/P1/tasks"


def test_sends_auth_and_params():
    s = FakeSession([FakeResp(200, {"data": [], "next_page": None})])
    fetch_open_tasks("P1", "t", session=s, sleep=lambda _: None)
    call = s.calls[0]
    assert call["headers"]["Authorization"] == "Bearer t"
    assert call["params"]["completed_since"] == "now"
    assert call["params"]["limit"] == 100
    assert "memberships.section.name" in call["params"]["opt_fields"]


def test_retries_on_429_then_succeeds():
    slept = []
    s = FakeSession([
        FakeResp(429, {}, {"Retry-After": "1"}),
        FakeResp(200, {"data": [{"gid": "1"}], "next_page": None}),
    ])
    assert len(fetch_open_tasks("P1", "t", session=s, sleep=slept.append)) == 1
    assert slept == [1.0]


def test_raises_after_three_failures():
    s = FakeSession([FakeResp(500), FakeResp(500), FakeResp(500)])
    with pytest.raises(AsanaError):
        fetch_open_tasks("P1", "t", session=s, sleep=lambda _: None)
    assert len(s.calls) == 3


def test_401_raises_immediately_without_retry():
    s = FakeSession([FakeResp(401, {"errors": [{"message": "Not Authorized"}]})])
    with pytest.raises(AsanaError, match="401"):
        fetch_open_tasks("P1", "t", session=s, sleep=lambda _: None)
    assert len(s.calls) == 1


def test_error_message_does_not_leak_token():
    s = FakeSession([FakeResp(403, {"errors": [{"message": "Forbidden"}]})])
    with pytest.raises(AsanaError) as exc:
        fetch_open_tasks("P1", "secret-token", session=s, sleep=lambda _: None)
    assert "secret-token" not in str(exc.value)
