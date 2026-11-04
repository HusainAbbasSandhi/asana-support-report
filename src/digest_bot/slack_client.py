"""Post a message to Slack via chat.postMessage."""
from __future__ import annotations

import time

import requests

URL = "https://slack.com/api/chat.postMessage"
TIMEOUT = 30


LOOKUP_URL = "https://slack.com/api/users.lookupByEmail"


class SlackError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def lookup_user_id(email: str | None, token: str, session=None) -> str | None:
    """Slack user ID for an email, or None. Never raises: a missing tag must not block a post."""
    if not email:
        return None
    session = session or requests.Session()
    try:
        resp = session.get(LOOKUP_URL, params={"email": email},
                           headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        data = resp.json() if resp.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        return None
    return (data.get("user") or {}).get("id") if data.get("ok") else None


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
        raise SlackError(f"Slack API error: {code}", code=code)
    return data.get("ts", "")
