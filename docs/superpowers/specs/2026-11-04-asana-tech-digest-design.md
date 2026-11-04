# Asana → Slack Tech Requests Daily Digest — Design

**Date:** 2026-11-04
**Owner:** Husain Abbas (Support)
**Status:** Approved design, pending spec review

## Purpose

Support agents raise requests for the tech team in Asana. Today there is no single daily view of what is open, new, urgent, or stuck. This automation posts one daily digest to Slack so the tech leads see the state of support-raised work at the start of the day without opening Asana.

**Success looks like:** every day at 10:30 IST, one message appears in `#tech-cs-issues` that tags Priyank, Joel and Parin, summarizes all open tasks in both projects, and highlights new, high-priority, blocked, unassigned and oldest items with links back to Asana.

## Scope

### In scope
- Asana workspace **Reelo** (`463982800396267`), two projects:
  - **Bug Tracking** — `1202029361021711` (owner Parin Sanghvi; ~173 open)
  - **Requests to Tech Team** — `1208716124012867` (owner Mokshi Sanghvi; ~17 open)
- **All open (incomplete) tasks** in those projects, regardless of who raised them.
- One Slack message per day to `#tech-cs-issues` (`C075PCA1NF7`, private).
- Mentions in every message: Priyank Mistry `U04H2DR5JJ1`, Joel Gnan `U01NJ4W5RLL`, Parin Sanghvi `U01GGKD7468`.
- Schedule: **every day at 10:30 IST** (05:00 UTC), plus manual trigger.

### Out of scope
- Writing anything back to Asana (read-only).
- Per-ticket real-time alerts, escalation DMs, threads, or weekly reports.
- Filtering by which support agent raised a task.
- Historical trend/metrics storage.

## Digest format

One Slack message (Slack `mrkdwn`; Block Kit sections if needed to stay within limits):

```
🛠️ Tech Requests — Daily Digest · <Weekday>, <D Mon>
cc <@U04H2DR5JJ1> <@U01NJ4W5RLL> <@U01GGKD7468>

🐞 BUG TRACKING — <N> open  (🆕 <n> new · 🔴 <n> Critical/High · 🚫 <n> Blocked · 👤 <n> unassigned)
🆕 New since yesterday
  • <link|title> — <priority> · <module> · by <requester> · → <assignee>
🔴 Critical / High still open
  • …
⏳ Oldest open (top 5)
  • <link|title> — <age> days · → <assignee|unassigned>

📋 REQUESTS TO TECH TEAM — <N> open  (🆕 <n> new)
  <section> <count> · <section> <count> · …
🆕 New since yesterday
  • <link|title> — <section> · → <assignee>
⏳ Oldest open (top 5)
  • …

🔗 <Bug Tracking link> · <Requests to Tech Team link>
```

### Definitions
- **Open:** `completed = false`.
- **New:** `created_at` within the 24 hours before the run.
- **Critical/High:** Priority value is `Critical` or `High` (see Priority rule below).
- **Blocked:** task is in the Bug Tracking section **Blocked**, or its **Status** field is `Blocked`.
- **Unassigned:** `assignee` is null.
- **Age:** whole days between `created_at` and run time.
- **Requester:** Bug Tracking `Requester` enum value; fall back to `Reporter` people field; else omitted.
- **Module:** Bug Tracking `Module` multi-enum, falling back to legacy `Feature` multi-enum; values joined with `/`; omitted if empty.

### Priority rule
Bug Tracking has two custom fields named "Priority":
- `1202861948139129` — Critical / High / Moderate / Low
- `1200058217049452` — High / Medium / Low

Use the first field if set, otherwise the second. Values are trimmed (one option is stored as `" High"`). Fields are referenced by **GID**, not name.

### Limits
- Each bulleted list shows at most **10** items (oldest lists: **5**), followed by `+N more` when truncated.
- Within lists, sort: Critical before High, then oldest first.
- Empty lists are omitted; if a project has zero open tasks, show `✅ Nothing open`.
- Titles are truncated to ~90 characters and Slack-escaped (`&`, `<`, `>`).

## Architecture

Python 3.12, dependencies: `requests`, `PyYAML`; dev: `pytest`.

```
asana-support-report/
├── config.yaml              # non-secret settings
├── src/digest_bot/
│   ├── asana_client.py      # fetch open tasks (paged) with needed fields
│   ├── models.py            # Task dataclass, normalisation from Asana JSON
│   ├── digest.py            # pure: list[Task] + config + now → Slack payload
│   ├── slack_client.py      # chat.postMessage
│   └── main.py              # CLI entry: load config, fetch, build, post / --dry-run
├── tests/
│   ├── fixtures/*.json      # sample Asana responses
│   └── test_digest.py, test_models.py
└── .github/workflows/digest.yml
```

### Units
- **asana_client** — `fetch_open_tasks(project_gid) -> list[dict]`. Calls `GET /projects/{gid}/tasks?completed_since=now&opt_fields=…&limit=100`, follows `next_page`. Retries 429/5xx with backoff (honours `Retry-After`), max 3 attempts. Auth: `Authorization: Bearer $ASANA_TOKEN`.
- **models** — `Task` dataclass (`gid, name, url, created_at, assignee_name, section_name, priority, status, requester, module`) and `from_asana(raw, project_kind) -> Task`, applying the field rules above.
- **digest** — `build_digest(bug_tasks, request_tasks, config, now) -> dict` returning `{"text": fallback, "blocks": [...]}`. No I/O; fully unit-tested.
- **slack_client** — `post_message(channel, payload)` → `POST https://slack.com/api/chat.postMessage` with `Bearer $SLACK_BOT_TOKEN`; raises if `ok` is false.
- **main** — `python -m digest_bot.main [--dry-run]`. Dry run prints the payload and posts nothing.

### config.yaml
```yaml
timezone: Asia/Kolkata
asana:
  workspace: "463982800396267"
  bug_tracking: "1202029361021711"
  requests_to_tech: "1208716124012867"
slack:
  channel: "C075PCA1NF7"
  mention_user_ids: ["U04H2DR5JJ1", "U01NJ4W5RLL", "U01GGKD7468"]
limits:
  list_max: 10
  oldest_max: 5
  new_window_hours: 24
```

## Data flow

GitHub Actions cron (05:00 UTC) → `main.py` → Asana API (two projects) → `Task` objects → `build_digest` → Slack `chat.postMessage` → `#tech-cs-issues`.

## Scheduling & deployment

- `.github/workflows/digest.yml`: `on: schedule: - cron: "0 5 * * *"` and `workflow_dispatch` (with a `dry_run` boolean input).
- Repository secrets: `ASANA_TOKEN`, `SLACK_BOT_TOKEN`.
- GitHub cron can run several minutes late under load; acceptable.
- Note: GitHub disables scheduled workflows after 60 days with no repo activity; the README documents re-enabling (or a keep-alive commit).

## Error handling

- Any Asana or Slack failure (after retries) exits non-zero → workflow fails → GitHub emails the repo owner. No partial message is posted (digest is built fully before posting).
- Unknown/missing custom fields degrade gracefully (field omitted), never crash.
- Slack message over block/character limits: lists are already capped; if still too long, drop the "Oldest" lists first.

## Testing

- **Unit (pytest):** `models` field rules (two priorities, trimmed values, requester fallback, blocked detection); `digest` counts, sorting, truncation/`+N more`, empty-project output, mention line, escaping. Fixed `now` for determinism.
- **Live dry run:** `python -m digest_bot.main --dry-run` against real Asana, reviewed by Husain before the first real post.
- **First real post:** manual `workflow_dispatch` run, verified in `#tech-cs-issues`.

## Prerequisites (owner: Husain)

1. Asana personal access token from the Reelo account (`husain.abbas@reelo.io`).
2. Slack app with bot scope `chat:write` installed to the workspace (may need admin approval), bot invited to `#tech-cs-issues`.
3. A GitHub repository for this project, with the two secrets added.
