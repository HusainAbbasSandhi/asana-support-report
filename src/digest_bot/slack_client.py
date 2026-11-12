"""Post a message to Slack via chat.postMessage."""
from __future__ import annotations

import time

import requests

URL = "https://slack.com/api/chat.postMessage"
TIMEOUT = 30


class SlackError(Exception):
    def __init__(self, message: str, code: str | None = None, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.detail = detail  # Slack's response_metadata.messages, e.g. which block was invalid


def _retry_after(resp) -> float:
    try:
        return float((getattr(resp, "headers", None) or {}).get("Retry-After", 1))
    except ValueError:
        return 1.0


def post_message(channel: str, payload: dict, token: str, session=None, sleep=time.sleep) -> str:
    session = session or requests.Session()
    body = {"channel": channel, "text": payload["text"], "blocks": payload["blocks"],
            "unfurl_links": False, "unfurl_media": False}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    # A 429 means Slack did not accept the message, so one retry cannot double-post.
    # Timeouts are NOT retried: Slack may already have posted.
    for attempt in (1, 2):
        try:
            resp = session.post(URL, json=body, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SlackError(f"Slack request failed: {exc.__class__.__name__}") from None
        if resp.status_code == 429 and attempt == 1:
            sleep(_retry_after(resp))
            continue
        break
    if resp.status_code != 200:
        raise SlackError(f"Slack HTTP error {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        raise SlackError("Slack returned an invalid response (not JSON)") from None
    if not data.get("ok"):
        code = data.get("error", "unknown")
        detail = "; ".join((data.get("response_metadata") or {}).get("messages") or [])
        raise SlackError(f"Slack API error: {code}", code=code, detail=detail)
    return data.get("ts", "")
