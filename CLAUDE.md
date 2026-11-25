# Spanish Tutor — guide for Claude sessions

A personal AI language tutor (Spanish first, A1–C2). It is built to scale to more users, more clients (web, mobile) and more target languages.
**Read `docs/architecture.md` before any structural change** (new table, new endpoint, new app, new folder). If a change departs from it, update that doc in the same change.

## Non-negotiable rules
1. **Curriculum is data, not code.**
   - Grammar topics (with prerequisites), scenarios and the per-level policy live in YAML under `curriculum/<lang>/`.
   - Never hard-code topics, levels, scenario text or level thresholds in Python.
2. **Clients hold no business logic.**
   - `apps/telegram_bot` (and later web/mobile) only talk to the core API over HTTP.
   - They never import `tutor_api`, never touch the DB, and never call Anthropic.
   - Grading, level logic, prompt building and persistence all live in `apps/api`.
3. **Every conversation turn returns validated JSON (`TurnResult`):**
   - `reply`
   - `corrections[]` of `{wrong, right, rule_tag, explanation, severity}`
   - `new_vocab[]`
   - `grammar_tags[]`

   Use Anthropic structured outputs with the Pydantic model. Never regex-parse free text. Never use assistant prefill or forced `tool_choice`, because current models reject both.
4. **`rule_tag` and `grammar_tags` are curriculum topic ids** (e.g. `es.a1.ser_vs_estar_basic`). Unknown ids are mapped to `unknown` and logged, never stored as-is.
5. **Level adaptation is driven by `curriculum/<lang>/levels.yaml`.** That file sets bot difficulty, explanation language and correction depth. Code reads the policy; it does not encode it.
6. **The DB stores curriculum ids as text** (no FK to YAML). The API validates the curriculum at startup (unique ids, prerequisites exist, no cycles) and refuses to start if it is invalid.
7. **The model id is configuration.** Use `TUTOR_MODEL` (default `claude-opus-5-5`), never a literal in code. Set `effort` explicitly and handle `stop_reason == "refusal"`.

## Layout
```
curriculum/<lang>/        levels.yaml, grammar/{a1..c2}.yaml, scenarios/{a1..c2}.yaml
apps/api/src/tutor_api/   core FastAPI backend
  routes/                 thin HTTP layer only: validate, call a service, return DTO
  services/               orchestration (turn_service, session_service), owns transactions
  domain/                 PURE functions, no I/O: level policy, mastery math, prompt assembly
  curriculum/             YAML loader + validator
  llm/                    Anthropic wrapper, TurnResult schema, prompt templates
  db/                     SQLAlchemy 2 async models + repositories
apps/api/migrations/      Alembic
apps/telegram_bot/        thin Telegram client (python-telegram-bot + httpx)
packages/contracts/       shared Pydantic request/response DTOs (the API contract)
evals/corrections/        correction-accuracy eval (cases/<lang>/*.yaml + run_eval.py --lang)
scripts/                  local background runner (supervisor.py) + its CLI (tutor.py, via tutor.cmd)
```

## Commands
All Python is managed with uv from the repo root.
```
Get-Service postgresql-x64-16                             # Postgres 16 (native Windows service, auto-starts)
uv sync                                                   # install workspace
uv run alembic -c apps/api/alembic.ini upgrade head       # migrate
tutor start | stop | restart | status | logs [api|bot]     # API + bot in the background (scripts/supervisor.py)
tutor autostart on                                        # start at Windows logon
tutor usage [-d 7]                                        # tokens + estimated cost per kind/lang/model
uv run uvicorn tutor_api.main:app --reload                # core API, foreground dev (run `tutor stop` first)
uv run python -m tutor_telegram                           # bot, foreground dev (only one bot may poll)
uv run pytest                                             # tests (no real LLM calls)
uv run ruff check . ; uv run ruff format .
uv run python evals/corrections/run_eval.py --level A1    # costs API money: run deliberately
```
Prerequisites (Windows): Python 3.12, uv, Git, PostgreSQL 16. No Docker: Postgres is installed natively at `D:\PostgreSQL\16` (data in `D:\PostgreSQL\16\data`, port 5432, `psql` at `D:\PostgreSQL\16\bin\psql.exe`). DB `spanish_tutor`, owned by role `tutor`.
After changing API or bot code, run `tutor restart` (the background API does not auto-reload).
Installing packages: set `UV_CACHE_DIR=D:/uv-cache` first (uv's default cache is on C:).
Config comes from `.env` (see `.env.example`). Never commit `.env`. The C: drive is nearly full, so keep tools, caches and data on D:.

## Conventions
- Python 3.12, type hints everywhere, async SQLAlchemy 2 + asyncpg, Pydantic v2.
- API DTOs live in `packages/contracts`. DB models never leak out of `apps/api`.
- Schema changes always go through a new Alembic migration. Never edit an applied migration.
- Tests mock the LLM wrapper (`llm/`). Unit-test `domain/` exhaustively, since it is pure.
- Any change to the prompt or the `TurnResult` schema means re-running the eval for the affected levels. Report the numbers.
- Keep the stable part of the system prompt first (cacheable). Put per-learner and per-turn data after it.
- Language-specific content belongs in `curriculum/<lang>/`. Code must stay language-agnostic, with `lang` as a parameter.

## Phase 1 scope (current)
**In scope:**
- core API
- Telegram text chat
- roleplay scenarios
- level-aware corrections
- persisting mistakes, vocab and mastery to Postgres
- correction eval script
- added on request (2026-11-25): streaks/daily goal/reminders, side questions ("ask"),
  spaced-repetition practice of the learner's own mistakes, voice messages in (speech-to-text),
  grammar lessons with generated exercises, Chinese (zh) and Japanese (ja) curricula (2026-11-25)

**Not yet (do not build unless asked):**
- listening exercises and spoken replies (text-to-speech)
- web or mobile clients
- spaced-repetition of vocabulary
- placement test
- billing and real auth
