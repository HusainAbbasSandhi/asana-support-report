"""Post a message to Slack via chat.postMessage."""
from __future__ import annotations

import requests

URL = "https://slack.com/api/chat.postMessage"
TIMEOUT = 30


class SlackError(Exception):
    pass


def post_message(channel: str, payload: dict, token: str, session=None) -> str:
    session = session or requests.Session()
    body = {"channel": channel, "text": payload["text"], "blocks": payload["blocks"],
            "unfurl_links": False, "unfurl_media": False}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    try:
        resp = session.post(URL, json=body, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SlackError(f"Slack request failed: {exc.__class__.__name__}") from None
    if resp.status_code != 200:
        raise SlackError(f"Slack HTTP error {resp.status_code}")
    data = resp.json()
    if not data.get("ok"):
        raise SlackError(f"Slack API error: {data.get('error', 'unknown')}")
    return data.get("ts", "")
