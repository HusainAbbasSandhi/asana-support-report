# Asana Tech Requests Daily Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python job that, every day at 10:30 IST, reads all open tasks from two Asana projects and posts one digest message to Slack `#tech-cs-issues` tagging Priyank, Joel and Parin.

**Architecture:** Pure-function core (`models.py` normalises Asana JSON into `Task`; `digest.py` turns tasks into a Slack payload) wrapped by thin HTTP clients (`asana_client.py`, `slack_client.py`) and a CLI (`main.py`). GitHub Actions runs it on a cron.

**Tech Stack:** Python 3.12, `requests`, `PyYAML`, `pytest`; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-04-asana-tech-digest-design.md`

## Global Constraints

- Python 3.12; runtime deps only `requests`, `PyYAML`; dev dep `pytest`.
- Package lives in `src/digest_bot/`; run as `python -m digest_bot.main [--dry-run]` with `PYTHONPATH=src` (or `pip install -e .`).
- Secrets only from env: `ASANA_TOKEN`, `SLACK_BOT_TOKEN`. Never in files or logs.
- Asana custom fields referenced by GID only:
  - Priority A (Critical/High/Moderate/Low): `1202861948139129`
  - Priority B (High/Medium/Low): `1200058217049452`
  - Status: `1205244304819066`
  - Module: `1215418181758775`; legacy Feature: `1202853926214497`
  - Requester (enum): `1208648898989523`; Reporter (people): `1216285168420620`
- Projects: Bug Tracking `1202029361021711`, Requests to Tech Team `1208716124012867`. Channel `C075PCA1NF7`. Mentions `U04H2DR5JJ1`, `U01NJ4W5RLL`, `U01GGKD7468`.
- Limits: `list_max` 10, `oldest_max` 5, `new_window_hours` 24, titles truncated to 90 chars.
- Timezone for header date: `Asia/Kolkata`. Cron `0 5 * * *`.
- Read-only against Asana. Build the full payload before posting; post nothing on any error.

## Review Focus

1. **Task in several projects** — `section_name` must come from the membership whose `project.gid` matches the project being read, not the first membership.
2. **Titles with `&`, `<`, `>` or emoji** — must be escaped for Slack mrkdwn and not break links; an empty/null name renders as `(untitled)`.
3. **Asana pagination beyond 100 tasks** — Bug Tracking has ~173 open; every `next_page` must be followed.
4. **Slack size limits** — a section block's text must stay ≤ 3000 chars and the message ≤ 50 blocks; if exceeded, drop "Oldest" lists first.
5. **Timezone** — `created_at` is UTC (`...Z`); "new" uses UTC math, header date uses IST (a run at 05:00 UTC shows the IST date).

---

### Task 1: Project scaffold, config and Task model

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `config.yaml`, `.gitignore`, `src/digest_bot/__init__.py`, `src/digest_bot/config.py`, `src/digest_bot/models.py`
- Test: `tests/test_models.py`, `tests/fixtures/bug_task.json`, `tests/fixtures/request_task.json`

**Interfaces:**
- Produces:
  - `config.load_config(path: str = "config.yaml") -> dict` (plain dict mirroring spec's config.yaml)
  - `@dataclass(frozen=True) class Task: gid: str; name: str; url: str; created_at: datetime (tz-aware UTC); assignee_name: str | None; section_name: str | None; priority: str | None; status: str | None; requester: str | None; module: str | None`
  - `models.from_asana(raw: dict, project_gid: str) -> Task`
  - `models.ASANA_OPT_FIELDS: str` = `"name,permalink_url,created_at,assignee.name,memberships.project.gid,memberships.section.name,custom_fields.gid,custom_fields.enum_value.name,custom_fields.multi_enum_values.name,custom_fields.people_value.name"`

- [ ] **Step 1: Scaffold** `pyproject.toml` (setuptools, `package-dir = {"" = "src"}`, pytest `pythonpath = ["src"]`), `requirements.txt` (`requests`, `PyYAML`, `pytest`), `.gitignore` (`.venv/`, `__pycache__/`, `.env`), and `config.yaml` copied verbatim from the spec.

- [ ] **Step 2: Write fixtures** — `bug_task.json`: a raw Asana task with two memberships (another project first, then `1202029361021711` / section `"Blocked"`), Priority A `enum_value.name = " High"`, Priority B set to `"Low"`, Status `"In Progress"`, Module multi-enum `["Loyalty","Campaigns"]`, Requester `"Dimple Manglani"`, assignee `"Joel Gnan"`, `created_at` `"2026-11-03T20:00:00.000Z"`, name `"OTP <fails> & SMS"`. `request_task.json`: no custom fields, section `"Other requests"`, assignee null.

- [ ] **Step 3: Write failing tests** in `tests/test_models.py`:

```python
def test_priority_prefers_field_a_and_trims(): assert bug.priority == "High"
def test_priority_falls_back_to_field_b():  # remove field A value → "Low"
def test_section_from_matching_project_membership(): assert bug.section_name == "Blocked"
def test_module_joined_with_slash(): assert bug.module == "Loyalty/Campaigns"
def test_module_falls_back_to_feature_field():
def test_requester_enum_then_reporter_people_fallback():
def test_request_task_has_none_fields(): assert req.priority is None and req.assignee_name is None and req.section_name == "Other requests"
def test_created_at_is_utc_aware(): assert bug.created_at.tzinfo is not None
def test_null_name_becomes_untitled():
def test_load_config_reads_ids(): assert load_config()["slack"]["channel"] == "C075PCA1NF7"
```

- [ ] **Step 4: Run** `pytest tests/test_models.py -v` → FAIL (module not found).

- [ ] **Step 5: Implement** `config.load_config` (yaml.safe_load) and `models.from_asana` per the field rules in the spec; build a `{gid: field}` dict from `custom_fields` once; empty strings → `None`.

- [ ] **Step 6: Run** `pytest -v` → all PASS.

- [ ] **Step 7: Commit** `git add -A && git commit -m "feat: scaffold project, config loader and Task model"`

---

### Task 2: Digest builder

**Files:**
- Create: `src/digest_bot/digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Consumes: `Task`, config dict (Task 1).
- Produces: `digest.build_digest(bug_tasks: list[Task], request_tasks: list[Task], config: dict, now: datetime) -> dict` returning `{"text": str, "blocks": list[dict]}`; helper `digest.escape(text: str) -> str`.

Rules (from spec): header `🛠️ Tech Requests — Daily Digest · <Weekday>, <D Mon>` (IST date) and `cc <@U…> <@U…> <@U…>`; Bug section summary `🐞 BUG TRACKING — N open  (🆕 n new · 🔴 n Critical/High · 🚫 n Blocked · 👤 n unassigned)`; lists New / Critical-High / Oldest; Requests section summary with per-section counts in project order of first appearance, then New / Oldest; footer links `https://app.asana.com/1/463982800396267/project/<gid>`. Blocked = `section_name == "Blocked"` or `status == "Blocked"`. Critical/High = priority in `{"Critical","High"}`. Sort lists Critical > High > other, then oldest first. Bullet: `• <url|title> — <parts joined " · "> · → <assignee or "unassigned">`, omitting empty parts. `+N more` after truncation. Empty project → `✅ Nothing open`. One `section` block per project part (header, bug, requests, footer); each block text ≤ 3000 chars, dropping Oldest lists first if over.

- [ ] **Step 1: Write failing tests** (fixed `now = datetime(2026,11,4,5,0,tzinfo=UTC)`, tasks built with a small `make_task(**kw)` helper):

```python
def test_header_has_ist_date_and_mentions(): assert "Wednesday, 4 Nov" in text and "<@U04H2DR5JJ1> <@U01NJ4W5RLL> <@U01GGKD7468>" in text
def test_bug_summary_counts():  # 5 tasks: 2 new, 1 Critical + 1 High, 1 Blocked by section, 1 by status, 1 unassigned → "5 open" "🆕 2 new" "🔴 2 Critical/High" "🚫 2 Blocked" "👤 1 unassigned"
def test_new_means_created_within_24h():  # created 23h ago counts, 25h ago does not
def test_critical_sorted_before_high_then_oldest():
def test_list_truncates_with_more_line():  # 13 new → 10 bullets + "+3 more"
def test_oldest_list_max_five_with_age_days(): assert "21 days" in text
def test_requests_section_counts_by_section(): assert "Other requests 2" in text
def test_empty_project_shows_nothing_open(): assert "✅ Nothing open" in text
def test_title_escaped_and_truncated(): assert "&lt;fails&gt; &amp;" in text and no title > 90 chars
def test_block_text_under_3000_chars_drops_oldest_first():  # 200 long-title tasks → every block ≤ 3000, "Oldest" absent, "New" present
def test_footer_links_both_projects():
```

- [ ] **Step 2: Run** `pytest tests/test_digest.py -v` → FAIL.
- [ ] **Step 3: Implement** `build_digest` and `escape` (`&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`; escape before truncating, truncate with `…`). `text` fallback = the header line. Use `zoneinfo.ZoneInfo(config["timezone"])` for the header date.
- [ ] **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: digest builder"` (add new files first).

---

### Task 3: Asana client

**Files:**
- Create: `src/digest_bot/asana_client.py`
- Test: `tests/test_asana_client.py`

**Interfaces:**
- Consumes: `models.ASANA_OPT_FIELDS`.
- Produces: `asana_client.fetch_open_tasks(project_gid: str, token: str, session: requests.Session | None = None) -> list[dict]`; raises `AsanaError(Exception)` after retries.

Calls `GET https://app.asana.com/api/1.0/projects/{gid}/tasks` with params `completed_since=now`, `opt_fields=ASANA_OPT_FIELDS`, `limit=100`, header `Authorization: Bearer <token>`; follows `next_page.offset` until null. Retries 429/5xx up to 3 attempts, sleeping `Retry-After` seconds (default 2, 4); sleep function injectable for tests (`sleep=time.sleep` kwarg).

- [ ] **Step 1: Write failing tests** with a fake session object returning canned responses:

```python
def test_follows_pagination():  # page1 next_page.offset="abc", page2 next_page None → 3 tasks total, second call has offset="abc"
def test_sends_auth_and_params(): assert headers["Authorization"] == "Bearer t" and params["completed_since"] == "now"
def test_retries_on_429_then_succeeds():  # 429 (Retry-After: 1) then 200 → result returned, sleep called with 1
def test_raises_after_three_failures():  # 500,500,500 → AsanaError
def test_401_raises_immediately_without_retry():
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest -v` → PASS.
- [ ] **Step 5: Commit** `feat: Asana client with paging and retries`

---

### Task 4: Slack client and CLI entry point

**Files:**
- Create: `src/digest_bot/slack_client.py`, `src/digest_bot/main.py`
- Test: `tests/test_slack_client.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `load_config`, `fetch_open_tasks`, `from_asana`, `build_digest`.
- Produces:
  - `slack_client.post_message(channel: str, payload: dict, token: str, session=None) -> str` (returns message `ts`); raises `SlackError` if HTTP error or `ok` false (include Slack's `error` string).
  - `main.run(dry_run: bool, config_path: str = "config.yaml", now: datetime | None = None) -> int` and `main()` parsing `--dry-run`, `--config`.

`run`: reads `ASANA_TOKEN` (required) and `SLACK_BOT_TOKEN` (required unless dry run; missing → print error, return 2); fetches both projects, maps via `from_asana(raw, project_gid)`, builds payload; dry run prints `json.dumps(payload, ensure_ascii=False, indent=2)` and returns 0; otherwise posts and prints `Posted ts=<ts>`. Any `AsanaError`/`SlackError` → message to stderr, return 1. Never prints tokens.

- [ ] **Step 1: Write failing tests**:

```python
def test_post_message_sends_channel_and_blocks():  # JSON body has channel, text, blocks; header Bearer
def test_post_message_raises_on_ok_false():  # {"ok": False, "error": "not_in_channel"} → SlackError containing "not_in_channel"
def test_run_dry_run_prints_and_does_not_post(monkeypatch, capsys):  # stub fetch → returns fixtures; post_message stub asserts not called; exit 0; stdout contains "BUG TRACKING"
def test_run_missing_slack_token_returns_2_when_not_dry_run():
def test_run_asana_error_returns_1_and_posts_nothing():
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: Commit** `feat: Slack client and CLI`

---

### Task 5: GitHub Actions workflow, README, live dry run

**Files:**
- Create: `.github/workflows/digest.yml`, `README.md`

**Interfaces:**
- Consumes: `python -m digest_bot.main [--dry-run]`.

- [ ] **Step 1: Write workflow**: triggers `schedule: - cron: "0 5 * * *"` and `workflow_dispatch` with boolean input `dry_run` (default false); job on `ubuntu-latest`: checkout, `actions/setup-python@v5` 3.12, `pip install -r requirements.txt`, `pytest -q`, then `python -m digest_bot.main ${{ inputs.dry_run && '--dry-run' || '' }}` with `PYTHONPATH: src`, env from secrets `ASANA_TOKEN`, `SLACK_BOT_TOKEN`.
- [ ] **Step 2: Write README**: what it does; local setup (`python -m venv .venv`, install, set env vars, `--dry-run`); prerequisites from spec (Asana PAT, Slack app with `chat:write` invited to `#tech-cs-issues`, repo secrets); manual run via Actions tab; note that GitHub disables cron after 60 days of repo inactivity and how to re-enable.
- [ ] **Step 3: Verify tests locally**: `pytest -q` → all pass.
- [ ] **Step 4: Live dry run** (needs `ASANA_TOKEN` from Husain): `python -m digest_bot.main --dry-run` → exit 0; output shows Bug Tracking ≈173 open and Requests ≈17 open; Husain reviews the message.
- [ ] **Step 5: Commit** `chore: GitHub Actions schedule and README`
- [ ] **Step 6 (with Husain): first real post** — push to GitHub, add secrets, run workflow manually with `dry_run=false`, confirm message in `#tech-cs-issues` with the three mentions.
