"""Load and validate `curriculum/<lang>/` YAML. Invalid curriculum => the API refuses to start."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from tutor_api.curriculum.models import (
    Curriculum,
    GrammarTopic,
    LanguageMeta,
    LevelPolicy,
    Scenario,
)

log = logging.getLogger(__name__)


class CurriculumError(Exception):
    """Raised for any invalid curriculum. The message lists every problem found."""


def _read_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as e:
        raise CurriculumError(f"{path}: YAML syntax error: {e}") from e


def _read_list_dir(directory: Path, errors: list[str]) -> list[tuple[Path, dict[str, Any]]]:
    items: list[tuple[Path, dict[str, Any]]] = []
    if not directory.is_dir():
        errors.append(f"missing directory: {directory}")
        return items
    for path in sorted(directory.glob("*.yaml")):
        data = _read_yaml(path) or []
        if not isinstance(data, list):
            errors.append(f"{path}: expected a list of entries")
            continue
        items.extend((path, entry) for entry in data)
    return items


def load_curriculum(lang_dir: Path) -> Curriculum:
    """Load one language directory and validate it. Raises CurriculumError on any problem."""
    errors: list[str] = []

    # language.yaml
    meta_path = lang_dir / "language.yaml"
    meta: LanguageMeta | None = None
    if not meta_path.is_file():
        errors.append(f"missing {meta_path}")
    else:
        try:
            meta = LanguageMeta.model_validate(_read_yaml(meta_path))
        except ValidationError as e:
            errors.append(f"{meta_path}: {e}")
        else:
            if meta.code != lang_dir.name:
                errors.append(f"{meta_path}: code {meta.code!r} != directory {lang_dir.name!r}")

    # levels.yaml
    levels: dict[str, LevelPolicy] = {}
    levels_path = lang_dir / "levels.yaml"
    if not levels_path.is_file():
        errors.append(f"missing {levels_path}")
    else:
        raw_levels = _read_yaml(levels_path) or {}
        if not isinstance(raw_levels, dict) or not raw_levels:
            errors.append(f"{levels_path}: expected a mapping of level code -> policy")
        else:
            for code, body in raw_levels.items():
                try:
                    levels[str(code)] = LevelPolicy.model_validate({"code": str(code), **body})
                except (ValidationError, TypeError) as e:
                    errors.append(f"{levels_path} [{code}]: {e}")
            ranks = [p.rank for p in levels.values()]
            if len(set(ranks)) != len(ranks):
                errors.append(f"{levels_path}: level ranks must be unique, got {sorted(ranks)}")
            for p in levels.values():
                if p.tutor_reply.vocab_ceiling not in raw_levels:
                    errors.append(
                        f"{levels_path} [{p.code}]: vocab_ceiling {p.tutor_reply.vocab_ceiling!r} "
                        "is not a defined level"
                    )

    # grammar/*.yaml
    topics: dict[str, GrammarTopic] = {}
    for path, entry in _read_list_dir(lang_dir / "grammar", errors):
        try:
            topic = GrammarTopic.model_validate(entry)
        except ValidationError as e:
            errors.append(f"{path} [{entry.get('id', '?')}]: {e}")
            continue
        if topic.id in topics:
            errors.append(f"{path}: duplicate topic id {topic.id}")
            continue
        topics[topic.id] = topic

    # scenarios/*.yaml
    scenarios: dict[str, Scenario] = {}
    for path, entry in _read_list_dir(lang_dir / "scenarios", errors):
        try:
            sc = Scenario.model_validate(entry)
        except ValidationError as e:
            errors.append(f"{path} [{entry.get('id', '?')}]: {e}")
            continue
        if sc.id in scenarios or sc.id in topics:
            errors.append(f"{path}: duplicate id {sc.id}")
            continue
        scenarios[sc.id] = sc

    errors.extend(_validate_graph(lang_dir.name, levels, topics, scenarios))

    if errors:
        raise CurriculumError(f"invalid curriculum in {lang_dir}:\n  - " + "\n  - ".join(errors))
    assert meta is not None
    ordered = tuple(sorted(levels, key=lambda c: levels[c].rank))
    return Curriculum(
        lang=meta, levels=levels, topics=topics, scenarios=scenarios, _ordered_levels=ordered
    )


def _validate_graph(
    lang: str,
    levels: dict[str, LevelPolicy],
    topics: dict[str, GrammarTopic],
    scenarios: dict[str, Scenario],
) -> list[str]:
    errors: list[str] = []

    def check_level_and_prefix(kind: str, item_id: str, level: str) -> None:
        if level not in levels:
            errors.append(f"{kind} {item_id}: level {level!r} missing from levels.yaml")
        expected_prefix = f"{lang}.{level.lower()}."
        if not item_id.startswith(expected_prefix):
            errors.append(f"{kind} {item_id}: id must start with {expected_prefix!r}")

    for t in topics.values():
        check_level_and_prefix("topic", t.id, t.level)
        for pre in t.prerequisites:
            if pre not in topics:
                errors.append(f"topic {t.id}: unknown prerequisite {pre}")
            elif (
                t.level in levels
                and topics[pre].level in levels
                and levels[topics[pre].level].rank > levels[t.level].rank
            ):
                errors.append(
                    f"topic {t.id}: prerequisite {pre} is at a higher level "
                    f"({topics[pre].level} > {t.level})"
                )

    # Cycle detection (iterative DFS with colours).
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(topics, white)
    for start in topics:
        if colour[start] != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        while stack:
            node, idx = stack.pop()
            if idx == 0:
                colour[node] = grey
                path.append(node)
            prereqs = [p for p in topics[node].prerequisites if p in topics]
            if idx < len(prereqs):
                stack.append((node, idx + 1))
                nxt = prereqs[idx]
                if colour[nxt] == grey:
                    cycle = path[path.index(nxt) :] + [nxt]
                    errors.append("prerequisite cycle: " + " -> ".join(cycle))
                elif colour[nxt] == white:
                    stack.append((nxt, 0))
            else:
                colour[node] = black
                path.pop()

    for s in scenarios.values():
        check_level_and_prefix("scenario", s.id, s.level)
        for tt in s.target_topics:
            if tt not in topics:
                errors.append(f"scenario {s.id}: unknown target_topic {tt}")

    for lp in levels.values():
        if lp.starter_scenario is None:
            continue
        sc = scenarios.get(lp.starter_scenario)
        if sc is None:
            errors.append(f"level {lp.code}: unknown starter_scenario {lp.starter_scenario}")
        elif sc.level != lp.code:
            errors.append(
                f"level {lp.code}: starter_scenario {sc.id} is at level {sc.level}, not {lp.code}"
            )

    return errors


def load_all_curricula(root: Path) -> dict[str, Curriculum]:
    """Load every `root/<lang>/` directory. Raises CurriculumError if any is invalid."""
    if not root.is_dir():
        raise CurriculumError(f"curriculum root not found: {root}")
    result: dict[str, Curriculum] = {}
    for lang_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        cur = load_curriculum(lang_dir)
        result[cur.code] = cur
        log.info(
            "curriculum %s loaded: %d levels, %d topics, %d scenarios",
            cur.code,
            len(cur.levels),
            len(cur.topics),
            len(cur.scenarios),
        )
    if not result:
        raise CurriculumError(f"no languages found under {root}")
    return result
