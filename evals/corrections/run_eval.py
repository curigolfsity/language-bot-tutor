"""Correction-accuracy eval. MAKES REAL API CALLS AND COSTS MONEY: run it deliberately.

    uv run python evals/corrections/run_eval.py --level A1
    uv run python evals/corrections/run_eval.py              # every level with a cases file
    uv run python evals/corrections/run_eval.py --lang zh    # cases/zh/ (default: es)

Each case goes through `turn_service.run_correction` (the production LLM + sanitise + policy path)
with a fixed neutral context: free conversation, no history, native language "en".
Writes a dated JSON report to evals/corrections/reports/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scoring import CaseScore, Expected, Predicted, aggregate, score_case  # noqa: E402
from tutor_api.config import get_settings  # noqa: E402
from tutor_api.curriculum import Curriculum, load_curriculum  # noqa: E402
from tutor_api.domain.policy import resolve_policy  # noqa: E402
from tutor_api.domain.prompt import build_learner_summary  # noqa: E402
from tutor_api.llm import AnthropicTurnLLM, TurnLLM  # noqa: E402
from tutor_api.services.errors import UpstreamError  # noqa: E402
from tutor_api.services.turn_service import run_correction  # noqa: E402

HERE = Path(__file__).resolve().parent
NEUTRAL_NATIVE_LANG = "en"


def load_cases(cases_dir: Path, levels: list[str] | None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(cases_dir.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if levels and case["level"] not in levels:
                continue
            out.setdefault(case["level"], []).append(case)
    return out


async def run_case(
    llm: TurnLLM, curriculum: Curriculum, case: dict[str, Any], sem: asyncio.Semaphore
) -> dict[str, Any]:
    policy = resolve_policy(curriculum, case["level"], NEUTRAL_NATIVE_LANG)
    async with sem:
        t0 = time.perf_counter()
        try:
            run = await run_correction(
                llm, curriculum, policy, None, build_learner_summary([], []), [], case["text"]
            )
        except UpstreamError as e:
            return {"id": case["id"], "error": str(e)}
        seconds = time.perf_counter() - t0
    expected = [Expected(**e) for e in case.get("expected") or []]
    predicted = [Predicted(c.wrong, c.right, c.rule_tag) for c in run.final.corrections]
    score = score_case(case["text"], expected, predicted, case.get("must_not_flag") or [])
    o = run.outcome
    return {
        "id": case["id"],
        "text": case["text"],
        "refused": run.refused,
        "seconds": round(seconds, 2),
        "score": asdict(score),
        "policy_violations": list(run.policy_violations),
        "unknown_tags": list(run.unknown_tags),
        "predicted": [c.model_dump() for c in run.final.corrections],
        "reply": run.final.reply,
        "model": o.model,
        "usage": {
            "input_tokens": o.input_tokens,
            "output_tokens": o.output_tokens,
            "cache_read_input_tokens": o.cache_read_input_tokens,
            "cache_creation_input_tokens": o.cache_creation_input_tokens,
        },
    }


def cost_usd(usage: dict[str, int], in_price: float, out_price: float) -> float:
    per = 1_000_000
    return (
        usage["input_tokens"] * in_price / per
        + usage["cache_creation_input_tokens"] * in_price * 1.25 / per
        + usage["cache_read_input_tokens"] * in_price * 0.1 / per
        + usage["output_tokens"] * out_price / per
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--level", action="append", help="level to run (repeatable); default: all")
    ap.add_argument("--lang", default="es")
    ap.add_argument("--cases-dir", type=Path, help="default: cases/<lang>/")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--input-price", type=float, default=4.0, help="USD per 1M input tokens")
    ap.add_argument("--output-price", type=float, default=20.0, help="USD per 1M output tokens")
    ap.add_argument("--out", type=Path, default=HERE / "reports")
    ap.add_argument("--effort", help="override TUTOR_EFFORT for this run (low|medium|high|...)")
    ap.add_argument("--label", default="", help="suffix for the report file name")
    args = ap.parse_args()

    settings = get_settings()
    if args.effort:
        settings = settings.model_copy(update={"tutor_effort": args.effort})
    curriculum = load_curriculum(settings.curriculum_dir / args.lang)
    cases = load_cases(args.cases_dir or HERE / "cases" / args.lang, args.level)
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 1

    llm = AnthropicTurnLLM(settings)
    sem = asyncio.Semaphore(args.concurrency)
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "model": settings.tutor_model,
        "effort": settings.tutor_effort,
        "lang": args.lang,
        "levels": {},
    }
    try:
        for level in sorted(cases, key=curriculum.rank):
            results = await asyncio.gather(
                *(run_case(llm, curriculum, c, sem) for c in cases[level])
            )
            ok = [r for r in results if "error" not in r]
            metrics = aggregate(
                [CaseScore(**r["score"]) for r in ok],
                policy_violations=sum(len(r["policy_violations"]) for r in ok),
                refusals=sum(1 for r in ok if r["refused"]),
            )
            usage = {
                k: sum(r["usage"][k] for r in ok)
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            }
            secs = sorted(r["seconds"] for r in ok)
            report["levels"][level] = {
                "metrics": asdict(metrics),
                "latency_s": {
                    "median": round(statistics.median(secs), 2) if secs else None,
                    "p90": round(secs[int(0.9 * (len(secs) - 1))], 2) if secs else None,
                },
                "errors": [r for r in results if "error" in r],
                "usage": usage,
                "cost_usd": round(cost_usd(usage, args.input_price, args.output_price), 4),
                "cases": ok,
            }
    finally:
        await llm.aclose()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    label = f"_{args.label}" if args.label else ""
    out_path = args.out / f"{stamp}_{args.lang}_{'-'.join(sorted(report['levels']))}{label}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"model={report['model']} effort={report['effort']}")
    print(
        f"{'level':<6}{'cases':>6}{'recall':>8}{'prec':>8}{'tag_acc':>9}{'mnf_fp':>8}"
        f"{'policy':>8}{'refuse':>8}{'errors':>8}{'cost$':>9}{'med_s':>7}{'p90_s':>7}"
    )
    for level, data in report["levels"].items():
        m = data["metrics"]

        def f(x: float | None) -> str:
            return "-" if x is None else f"{x:.2f}"

        print(
            f"{level:<6}{m['cases']:>6}{f(m['recall']):>8}{f(m['precision']):>8}"
            f"{f(m['rule_tag_accuracy']):>9}{m['must_not_flag_false_positives']:>8}"
            f"{m['policy_violations']:>8}{m['refusals']:>8}{len(data['errors']):>8}"
            f"{data['cost_usd']:>9.4f}"
            f"{f(data['latency_s']['median']):>7}{f(data['latency_s']['p90']):>7}"
        )
    print(f"report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
