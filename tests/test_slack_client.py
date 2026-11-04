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


def test_post_message_raises_on_http_error():
    s = FakeSession(FakeResp(500, {}))
    with pytest.raises(SlackError, match="500"):
        post_message("C1", {"text": "hi", "blocks": []}, "xoxb-t", session=s)
