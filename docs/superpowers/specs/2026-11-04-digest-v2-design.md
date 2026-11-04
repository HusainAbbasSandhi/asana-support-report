# Tech Digest v2 — Summary table + response tracking — Design

**Date:** 2026-11-04
**Requested by:** Parin Sanghvi, via Husain Abbas
**Supersedes:** the message layout in `2026-11-04-asana-tech-digest-design.md`. Infrastructure, secrets, schedule mechanics and the support-team filter are unchanged.

## Purpose

The tech leads want two things: a quick numeric picture of support-raised work, and a short, actionable list of tickets where Product & Tech hasn't responded, with the person responsible tagged. A second, afternoon message catches conversations that started but have gone quiet.

## Scope (both messages)

- Projects: **Bug Tracking** (`1202029361021711`) and **Requests to Tech Team** (`1208716124012867`), combined.
- Only **open** tasks **created by the support team**, as defined by `config.yaml → asana.support_team` (Asana user ID → name).
- **Product & Tech** means anyone who is **not** on the support team list.
- A **comment** is an Asana story with `resource_subtype == "comment_added"`. System events such as assignment and field changes are not comments.

## Message 1 — Daily digest, 10:30 IST

```
🛠️ Tech Requests — Daily Digest · Thursday, 5 Nov
cc @Priyank Mistry @Joel Gnan @Parin Sanghvi

┌───────────────────────────────────────┬───────┐   ← Slack native table block
│ Metric                                │ Count │
├───────────────────────────────────────┼───────┤
│ Open tickets raised by support        │   71  │   (1)
│ Open for more than 4 days             │   50  │   (2)
│ Assigned to a support team member     │    6  │   (3)
│ No Product & Tech reply in 2+ days    │   30  │   (4)
└───────────────────────────────────────┴───────┘
Raised by: Haydar Abbas 23 · Adithya Kaushik 19 · Ishika Batra 17 · …

⏳ No Product & Tech reply in 2+ days — 30
@Priyank Mistry — 15 waiting
  • <link|Expire the membership | Bake Affair> — 3 days
  • …
@Joel Gnan — 5 waiting
  • …
Unassigned — 2 waiting
  • …

🔗 Open Bug Tracking · Open Requests to Tech Team
```

### Metric definitions
1. **Open tickets:** count of in-scope tasks.
2. **Open for more than 4 days:** `now − created_at > 96h`.
3. **Assigned to a support team member:** the assignee's Asana ID is in `support_team`.
4. **No Product & Tech reply in 2+ days:** `now − created_at > 48h`, and the task has **no comment ever** from a non-support user.

### Section 4 list
- Grouped by **assignee**, largest group first, with "Unassigned" last.
- Each group header @tags the assignee in Slack (see Tagging) and gives the count.
- Each task shows its title as a link and its age in days, oldest first.
- Each group lists at most **10** tasks, then "+N more", to stay within Slack's limits.

### Removed from v1
The "New since yesterday", "Critical still open" and "Oldest open" lists; the Blocked and unassigned counts; and the per-project sections. The per-agent "Raised by" counts move to one line under the table.

## Message 2 — Stalled conversations, 14:00 IST (new)

```
⏰ Stalled conversations · Thursday, 5 Nov
Open support tickets where Product & Tech replied, but nobody has commented for 24h+

@Joel Gnan — 3 stalled
  • <link|Data mismatch | Yuki> — last comment 2 days ago by Haydar Abbas
  • …
```

- **Stalled:** an in-scope task with **at least one** non-support comment (so a first response exists), whose **latest comment from anyone** is more than **24h** old.
- Grouped and tagged by assignee, as in section 4. Each line shows when the last comment was made and who made it.
- If nothing is stalled, the message still posts with "✅ No stalled conversations today", so a missing post always means a failure.

## Tagging (Asana assignee → Slack user)

- Asana returns `assignee.email`. The bot calls Slack `users.lookupByEmail` and tags `<@U…>`.
- This needs Slack bot scopes **`users:read`** and **`users:read.email`**, on top of `chat:write`. Adding scopes means **reinstalling the app, which Parin approves once more**.
- Lookups are cached per run. If no Slack user matches, or the lookup fails, the name is shown in bold instead. A tag never blocks the post.

## Table rendering

- The summary uses Slack's **`table` block**. If Slack rejects the message with `invalid_blocks`, the bot resends it once with the same table as a monospace code block, which renders everywhere.

## Data access

- Tasks are fetched as now, adding `assignee.gid` and `assignee.email` to the requested fields.
- For each in-scope task, the bot reads its comments: `GET /tasks/{gid}/stories` with `opt_fields=resource_subtype,created_at,created_by.gid,created_by.name`, paginated. At about 70 tasks that's about 70 calls per run, well within Asana's rate limits. Retries reuse the existing 429/5xx logic.
- Both messages use the same fetch code. The command is `python -m digest_bot.main --report daily|stalled [--dry-run]`.

## Scheduling

- `digest.yml`: as now, cron `57 4 * * *` (10:27 IST), running `--report daily`.
- New `stalled.yml`: cron `57 8 * * *` (13:57 IST), running `--report stalled`. It has the same secrets, `workflow_dispatch` and `dry_run` input.

## Error handling

Unchanged: nothing is posted unless the whole message built successfully, and a failure turns the run red and triggers GitHub's email. A failed Slack user lookup degrades to a bold name. A failed comments fetch for any task fails the whole run, because partial counts would mislead.

## Testing

- **Unit:** the metric definitions at their boundaries (exactly 48h and 96h); the "no non-support comment" rule, including comments by support members and system stories; the stalled rule (no P&T comment → not stalled; P&T comment with recent activity → not stalled; last comment older than 24h → stalled); grouping and order; the 10-item cap; the table block shape and the monospace fallback; tag fallback to a bold name.
- **Live:** a dry run of both reports against real Asana, reviewed before the first post.

## Prerequisites

1. Parin re-approves the Slack app with the `users:read` and `users:read.email` scopes. I'll update the manifest.
2. No new GitHub secrets are needed.
