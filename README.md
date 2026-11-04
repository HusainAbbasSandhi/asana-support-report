# Asana → Slack Tech Requests Digest

This job reads open tasks **raised by the support team** in Asana (Bug Tracking and Requests to Tech Team) and posts two messages to Slack **#tech-cs-issues** every day.

- **10:00 IST, daily digest.** It tags Priyank Mistry, Joel Gnan and Parin Sanghvi, then shows:
  - a summary table:
    - open tickets
    - open for more than 4 days
    - assigned to a support member
    - no Product & Tech reply in 2+ days
  - a "Raised by" count per agent
  - the list of tickets with no Product & Tech reply, grouped by assignee, with each assignee @tagged
- **14:00 IST, stalled conversations.** Tickets where Product & Tech replied but nobody has commented for 24h+, grouped by assignee and tagged.

"Product & Tech" means anyone not on the support team list in `config.yaml`. Only real comments count, not system events.

The job only reads from Asana. It never changes tasks. Design: [`docs/superpowers/specs/2026-11-04-asana-tech-digest-design.md`](docs/superpowers/specs/2026-11-04-asana-tech-digest-design.md).

## Setup (one time)

1. **Asana token.** Sign in to Asana as an account that can see both projects. Go to *Profile → Settings → Apps → Developer apps → Create new token* (personal access token).
2. **Slack bot.** At <https://api.slack.com/apps>, create an app for the Reelo workspace.
   - Under *OAuth & Permissions*, add the bot scopes **`chat:write`**, **`users:read`** and **`users:read.email`** (or create the app from [`slack-app-manifest.yaml`](slack-app-manifest.yaml)). Then click *Install to Workspace*. This may need a Slack admin's approval. The two `users:` scopes let the bot find each assignee's Slack account by email so it can tag them.
   - Copy the **Bot User OAuth Token** (`xoxb-…`).
   - In Slack, open **#tech-cs-issues** and run `/invite @<your app name>`. The channel is private, so the bot can't post until it's invited.
3. **GitHub.** Push this repo. Under *Settings → Secrets and variables → Actions*, add:
   - `ASANA_TOKEN`
   - `SLACK_BOT_TOKEN`

## Running it

- **Automatically:** the daily digest runs at 04:27 UTC (09:57 IST) and the stalled report at 08:27 UTC (13:57 IST). Both are scheduled a few minutes early and off the top of the hour, because GitHub often starts on-the-hour runs late. Expect the posts at around 10:00 and 14:00.
- **Manually:** under *Actions*, pick *Daily tech requests digest* or *Stalled conversations report*, then *Run workflow*. Tick **dry_run** to preview the message without posting it.
- **Locally:** `python -m digest_bot.main --report daily|stalled --dry-run`.
- **If assignees show as bold names instead of @tags:** the Slack app is missing the `users:` scopes, or that person's Asana email doesn't match their Slack email.
- **Tests** run in a separate `Tests` workflow on every push, so a failing test never blocks the daily post.
- **Manually:** *Actions → Daily tech requests digest → Run workflow*. Tick **dry_run** to see the message in the log without posting it.

### Locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
export ASANA_TOKEN=...                           # PowerShell: $env:ASANA_TOKEN="..."
PYTHONPATH=src python -m digest_bot.main --dry-run
pytest -q
```

## Changing things

Edit [`config.yaml`](config.yaml) to change the channel, the people tagged, the list sizes or the "new" window.

**Support team list:** only tasks *created* by the Asana users under `asana.support_team` appear in the digest, and the "👥 Raised by support" section counts open tasks per person. Each entry is `"<Asana user ID>": "<name>"`. To add someone, add a line. If one person has several accounts, give them all the same name so their counts are summed. To find the ID, open their Asana profile; the long number in the URL is the ID. Remove every entry to include all tasks. Slack user IDs are listed under *Profile → ⋮ → Copy member ID*.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Run fails with `not_in_channel` | Invite the bot to #tech-cs-issues. |
| Run fails with `Asana API error 401/403` | The token is wrong or expired, or the account can't see a project. Create a new token. |
| No post and no failed run | GitHub **disables scheduled workflows after 60 days with no repository activity**. Re-enable it under *Actions → Daily tech requests digest → Enable workflow*, or push any commit. |

When a run fails, GitHub emails the repository owner. A failed run never posts a half-built message.

**Before re-running a failed run, check #tech-cs-issues.** If the failure was a Slack timeout, the message may already have been posted, and re-running would post it twice.
