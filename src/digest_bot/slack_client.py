"""Post a message to Slack via chat.postMessage."""
from __future__ import annotations

import sys
import time

import requests

URL = "https://slack.com/api/chat.postMessage"
TIMEOUT = 30


LOOKUP_URL = "https://slack.com/api/users.lookupByEmail"


class SlackError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


_warned: set[str] = set()


def _warn_once(code: str) -> None:
    if code not in _warned:
        _warned.add(code)
        hint = " (add users:read and users:read.email to the Slack app)" if code == "missing_scope" else ""
        print(f"warning: Slack user lookup failed: {code}{hint}; showing names without @tags", file=sys.stderr)


def lookup_user_id(email: str | None, token: str, session=None) -> str | None:
    """Slack user ID for an email, or None. Never raises: a missing tag must not block a post.
    The email goes in the form body, not the URL."""
    if not email:
        return None
    session = session or requests.Session()
    try:
        resp = session.post(LOOKUP_URL, data={"email": email},
                            headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        data = resp.json() if resp.status_code == 200 else {"error": f"http_{resp.status_code}"}
    except (requests.RequestException, ValueError) as exc:
        _warn_once(exc.__class__.__name__)
        return None
    if data.get("ok"):
        return (data.get("user") or {}).get("id")
    if data.get("error") != "users_not_found":
        _warn_once(data.get("error", "unknown"))
    return None


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
