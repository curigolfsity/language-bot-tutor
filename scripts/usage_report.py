"""Where the API money goes: token usage and estimated cost from the tutor's own database.

    tutor usage            last 7 days
    tutor usage -d 30      last 30 days

Conversation turns carry their usage on the tutor turn row; every other model call (help,
ask, grading, lessons) is in `llm_calls`. Costs are estimates from the prices below; your
Claude Console billing page is the source of truth. Eval runs are not included (their
reports under evals/corrections/reports/ carry their own cost).
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from tutor_api.config import get_settings
from tutor_api.db.engine import make_engine

# USD per 1M tokens: input, output, cache read, 5-minute cache write.
# From https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-11-25).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def cost(model: str, inp: int, out: int, read: int, write: int) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return (inp * p[0] + out * p[1] + read * p[2] + write * p[3]) / 1_000_000


TURNS = """
SELECT date(t.created_at) AS day, 'chat' AS kind, p.target_lang AS lang, t.llm_model AS model,
       t.input_tokens, t.output_tokens,
       coalesce((t.result_json->>'cache_read_input_tokens')::int, 0),
       coalesce((t.result_json->>'cache_creation_input_tokens')::int, 0)
FROM turns t JOIN sessions s ON s.id = t.session_id JOIN learner_profiles p ON p.id = s.profile_id
WHERE t.role = 'tutor' AND t.llm_model IS NOT NULL AND t.created_at >= :since
"""
CALLS = """
SELECT date(created_at), kind, lang, model, input_tokens, output_tokens,
       cache_read_input_tokens, cache_creation_input_tokens
FROM llm_calls WHERE created_at >= :since
"""


async def main() -> int:
    ap = argparse.ArgumentParser(prog="tutor usage", description=__doc__.splitlines()[0])
    ap.add_argument("-d", "--days", type=int, default=7)
    args = ap.parse_args()
    since = datetime.now(UTC) - timedelta(days=args.days)

    engine = make_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = [*(await conn.execute(text(TURNS), {"since": since})).all()]
        rows += [*(await conn.execute(text(CALLS), {"since": since})).all()]
    await engine.dispose()

    if not rows:
        print(f"No model calls in the last {args.days} days.")
        return 0
    # (kind, lang, model) -> [calls, input, output, read, write]
    agg: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    per_day: dict[str, float] = defaultdict(float)
    unknown: set[str] = set()
    for day, kind, lang, model, inp, out, read, write in rows:
        a = agg[(kind, lang or "-", model)]
        for i, v in enumerate((1, inp, out, read, write)):
            a[i] += v or 0
        c = cost(model, inp or 0, out or 0, read or 0, write or 0)
        if c is None:
            unknown.add(model)
        else:
            per_day[str(day)] += c

    print(f"Model usage, last {args.days} days (estimated cost)\n")
    print(
        f"{'what':<8}{'lang':<6}{'model':<20}{'calls':>7}{'tokens in/out':>17}"
        f"{'cost':>10}{'per call':>10}"
    )
    total = 0.0
    for (kind, lang, model), (n, inp, out, read, write) in sorted(
        agg.items(), key=lambda kv: -(cost(kv[0][2], *kv[1][1:]) or 0)
    ):
        c = cost(model, inp, out, read, write)
        total += c or 0
        cost_s = f"${c:.3f}" if c is not None else "?"
        each = f"${c / n:.4f}" if c is not None else "?"
        tokens = f"{inp + read + write:,}/{out:,}"
        print(f"{kind:<8}{lang:<6}{model:<20}{n:>7}{tokens:>17}{cost_s:>10}{each:>10}")
    print(f"\nTotal: ${total:.2f}")
    print("By day: " + ", ".join(f"{d} ${v:.2f}" for d, v in sorted(per_day.items())))
    if unknown:
        print(f"(no price for {', '.join(sorted(unknown))}: add it to PRICES in this script)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
