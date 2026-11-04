# Asana → Slack Tech Requests Digest

Every day at **10:30 IST**, this job reads all open tasks from two Asana projects and posts one digest to Slack **#tech-cs-issues**, tagging Priyank Mistry, Joel Gnan and Parin Sanghvi.

- **Bug Tracking**: open count, new in the last 24h, Critical/High, Blocked, unassigned, oldest open
- **Requests to Tech Team**: open count by section, new in the last 24h, oldest open

The job only reads from Asana. It never changes tasks. Design: [`docs/superpowers/specs/2026-11-04-asana-tech-digest-design.md`](docs/superpowers/specs/2026-11-04-asana-tech-digest-design.md).

## Setup (one time)

1. **Asana token.** Sign in to Asana as an account that can see both projects. Go to *Profile → Settings → Apps → Developer apps → Create new token* (personal access token).
2. **Slack bot.** At <https://api.slack.com/apps>, create an app for the Reelo workspace.
   - Under *OAuth & Permissions*, add the bot scope **`chat:write`**, then *Install to Workspace* (this may need a Slack admin's approval).
   - Copy the **Bot User OAuth Token** (`xoxb-…`).
   - In Slack, open **#tech-cs-issues** and run `/invite @<your app name>`. The channel is private, so the bot can't post until it's invited.
3. **GitHub.** Push this repo. Under *Settings → Secrets and variables → Actions*, add:
   - `ASANA_TOKEN`
   - `SLACK_BOT_TOKEN`

## Running it

- **Automatically:** every day at 05:00 UTC (10:30 IST). GitHub can start scheduled runs a few minutes late.
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

Edit [`config.yaml`](config.yaml) to change the channel, the people tagged, the list sizes or the "new" window. Slack user IDs are listed under *Profile → ⋮ → Copy member ID*.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Run fails with `not_in_channel` | Invite the bot to #tech-cs-issues. |
| Run fails with `Asana API error 401/403` | The token is wrong or expired, or the account can't see a project. Create a new token. |
| No post and no failed run | GitHub **disables scheduled workflows after 60 days with no repository activity**. Re-enable it under *Actions → Daily tech requests digest → Enable workflow*, or push any commit. |

When a run fails, GitHub emails the repository owner. A failed run never posts a half-built message.
