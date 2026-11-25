# language-bot-tutor

A personal AI language tutor you chat with on Telegram. It holds real conversations and
role-plays at your level, corrects your mistakes gently, and brings them back later so they
stick. **Spanish (A1–C2) is live; more languages (Chinese next) are planned.** Adding a
language is curriculum data, not code.

## What it does
- 💬 **Free chat and 🎭 role-plays** (café, doctor, job interview…), with level-aware replies
- ✏️ **Corrections** with short explanations in your own language, and praise for what you got right
- 💡 **Help on every message**: hint, translate, suggested answer, deeper explanation
- 🙋 **Side questions** (start a message with `?`), answered without interrupting the conversation
- 🧠 **Practise your mistakes**: spaced repetition of your own past errors
- 🎤 **Voice messages**, transcribed locally with Whisper
- 🔥 **Streaks, a daily goal and evening reminders**

## How it's built
- `apps/api`: FastAPI core. All logic lives here: prompts, grading, the learner model, persistence.
- `apps/telegram_bot`: a thin client that only calls the API.
- `packages/contracts`: shared request/response models.
- `curriculum/<lang>/`: levels, grammar topics and scenarios as YAML. **A new language is a new folder.**
- `evals/corrections`: correction-accuracy eval.
- Claude (Anthropic API) generates structured outputs; Postgres stores the data; faster-whisper does speech-to-text.

See [docs/architecture.md](docs/architecture.md) for the design and [CLAUDE.md](CLAUDE.md) for the
project rules and commands.

## Quick start (Windows)
Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL 16.

```
copy .env.example .env          # then fill in ANTHROPIC_API_KEY, CLIENT_API_KEYS, TELEGRAM_TOKEN, DATABASE_URL
uv sync
uv run alembic -c apps/api/alembic.ini upgrade head
tutor start                     # API + bot in the background (tutor status | logs | stop)
tutor autostart on              # optional: start at Windows logon
```

Tests: `uv run pytest`. The eval makes paid API calls: `uv run python evals/corrections/run_eval.py --level A1`.

## Adding a language (e.g. Chinese)
1. Create `curriculum/zh/` with `language.yaml`, `levels.yaml`, `grammar/*.yaml` and `scenarios/*.yaml`
   (copy `curriculum/es/` as a template). The API validates it at startup.
2. Add eval cases in `evals/corrections/cases/` and run the eval.
3. Run a bot with `BOT_TARGET_LANG=zh`.
