import pytest

from digest_bot.slack_client import SlackError, post_message


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.resp


def test_post_message_sends_channel_and_blocks():
    s = FakeSession(FakeResp(200, {"ok": True, "ts": "123.45"}))
    ts = post_message("C1", {"text": "hi", "blocks": [{"type": "divider"}]}, "xoxb-t", session=s)
    assert ts == "123.45"
    call = s.calls[0]
    assert call["url"] == "https://slack.com/api/chat.postMessage"
    assert call["json"]["channel"] == "C1"
    assert call["json"]["text"] == "hi"
    assert call["json"]["blocks"] == [{"type": "divider"}]
    assert call["headers"]["Authorization"] == "Bearer xoxb-t"


def test_post_message_raises_on_ok_false():
    s = FakeSession(FakeResp(200, {"ok": False, "error": "not_in_channel"}))
    with pytest.raises(SlackError, match="not_in_channel"):
        post_message("C1", {"text": "hi", "blocks": []}, "xoxb-t", session=s)


class SeqSession:
    def __init__(self, resps):
        self.resps = list(resps)
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        return self.resps.pop(0)


class Resp429(FakeResp):
    def __init__(self, retry_after):
        super().__init__(429, {})
        self.headers = {"Retry-After": retry_after}


def test_post_message_retries_once_on_429():
    slept = []
    s = SeqSession([Resp429("2"), FakeResp(200, {"ok": True, "ts": "1.2"})])
    assert post_message("C1", {"text": "hi", "blocks": []}, "t", session=s, sleep=slept.append) == "1.2"
    assert slept == [2.0] and s.calls == 2


def test_post_message_non_json_raises_slack_error():
    class BadJson(FakeResp):
        def json(self):
            raise ValueError("no json")

    s = FakeSession(BadJson(200, None))
    with pytest.raises(SlackError, match="invalid response"):
        post_message("C1", {"text": "hi", "blocks": []}, "t", session=s)


class GetSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self.exc:
            raise self.exc
        return self.resp


def test_lookup_user_id_found():
    from digest_bot.slack_client import lookup_user_id
    s = GetSession(FakeResp(200, {"ok": True, "user": {"id": "U123"}}))
    assert lookup_user_id("joel.gnan@reelo.io", "t", session=s) == "U123"
    assert s.calls[0]["url"] == "https://slack.com/api/users.lookupByEmail"
    assert s.calls[0]["params"] == {"email": "joel.gnan@reelo.io"}


def test_lookup_user_id_not_found_or_error_returns_none():
    import requests
    from digest_bot.slack_client import lookup_user_id
    assert lookup_user_id("x@y", "t", session=GetSession(FakeResp(200, {"ok": False, "error": "users_not_found"}))) is None
    assert lookup_user_id("x@y", "t", session=GetSession(exc=requests.ConnectionError())) is None
    assert lookup_user_id(None, "t", session=GetSession(FakeResp(200, {"ok": True}))) is None


def test_slack_error_carries_code():
    s = FakeSession(FakeResp(200, {"ok": False, "error": "invalid_blocks"}))
    with pytest.raises(SlackError) as exc:
        post_message("C1", {"text": "hi", "blocks": []}, "t", session=s)
    assert exc.value.code == "invalid_blocks"


def test_post_message_raises_on_http_error():
    s = FakeSession(FakeResp(500, {}))
    with pytest.raises(SlackError, match="500"):
        post_message("C1", {"text": "hi", "blocks": []}, "xoxb-t", session=s)
