# Asana → Slack tech digest
Python job (GitHub Actions cron) posting daily/stalled digests from Asana to Slack #tech-cs-issues. Read-only on Asana.
- Run: `python -m digest_bot.main --report daily|stalled --dry-run`. Tests: `pytest`.
- Lint: `ruff check .` (installed; 11 auto-fixable findings not yet applied).
- Config (support team list, channel) in `config.yaml`. Secrets ASANA_TOKEN, SLACK_BOT_TOKEN live in GitHub Actions secrets.

- A gitleaks pre-commit hook blocks commits that contain secrets.
