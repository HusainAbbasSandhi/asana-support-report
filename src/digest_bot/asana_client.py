"""Read open tasks from an Asana project (read-only)."""
from __future__ import annotations

import time

import requests

from digest_bot.models import ASANA_OPT_FIELDS

BASE = "https://app.asana.com/api/1.0"
MAX_ATTEMPTS = 3
DEFAULT_BACKOFF = (2.0, 4.0)
TIMEOUT = 30


class AsanaError(Exception):
    pass


def _get(session, url, params, headers, sleep) -> dict:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise AsanaError(f"Asana request failed: {exc.__class__.__name__}") from None
            sleep(DEFAULT_BACKOFF[attempt - 1])
            continue
        if resp.status_code == 200:
            return resp.json()
        retryable = resp.status_code == 429 or resp.status_code >= 500
        if not retryable or attempt == MAX_ATTEMPTS:
            raise AsanaError(f"Asana API error {resp.status_code}: {resp.text[:300]}")
        retry_after = resp.headers.get("Retry-After")
        sleep(float(retry_after) if retry_after else DEFAULT_BACKOFF[attempt - 1])
    raise AsanaError("unreachable")


def fetch_open_tasks(project_gid: str, token: str, session: requests.Session | None = None,
                     sleep=time.sleep) -> list[dict]:
    session = session or requests.Session()
    url = f"{BASE}/projects/{project_gid}/tasks"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"completed_since": "now", "opt_fields": ASANA_OPT_FIELDS, "limit": 100}
    tasks: list[dict] = []
    while True:
        body = _get(session, url, params, headers, sleep)
        tasks.extend(body.get("data") or [])
        offset = (body.get("next_page") or {}).get("offset")
        if not offset:
            return tasks
        params = {**params, "offset": offset}
