"""Guards for the non-negotiable layering rules in CLAUDE.md."""

import ast
import re
from pathlib import Path

from tutor_api.config import REPO_ROOT

API_SRC = REPO_ROOT / "apps" / "api" / "src" / "tutor_api"
BOT_SRC = REPO_ROOT / "apps" / "telegram_bot" / "src" / "tutor_telegram"


def imported_modules(root: Path) -> dict[Path, set[str]]:
    out: dict[Path, set[str]] = {}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(
                    node.module
                    if node.module.startswith("tutor_api")
                    else node.module.split(".")[0]
                )
        out[path] = mods
    return out


def test_bot_is_a_thin_client():
    forbidden = {"tutor_api", "anthropic", "sqlalchemy", "asyncpg", "yaml"}
    for path, mods in imported_modules(BOT_SRC).items():
        roots = {m.split(".")[0] for m in mods}
        assert not roots & forbidden, f"{path} imports {roots & forbidden}"


def test_domain_is_pure():
    io_modules = {"sqlalchemy", "anthropic", "httpx", "fastapi", "yaml", "asyncpg", "os", "pathlib"}
    allowed_internal = ("tutor_api.domain", "tutor_api.curriculum.models")
    for path, mods in imported_modules(API_SRC / "domain").items():
        roots = {m.split(".")[0] for m in mods}
        assert not roots & io_modules, f"{path} imports {roots & io_modules}"
        for m in mods:
            if m.startswith("tutor_api"):
                assert m.startswith(allowed_internal), f"{path} imports {m}"


def test_only_llm_package_imports_anthropic():
    for path, mods in imported_modules(API_SRC).items():
        if "anthropic" in mods:
            assert "llm" in path.relative_to(API_SRC).parts, f"{path} imports anthropic"


def test_routes_do_not_touch_db_or_llm():
    for path, mods in imported_modules(API_SRC / "routes").items():
        bad = {
            m for m in mods if m.startswith(("tutor_api.db", "tutor_api.llm", "tutor_api.domain"))
        }
        assert not bad and "sqlalchemy" not in mods, f"{path} imports {bad}"


def test_no_model_id_literals_outside_config():
    pattern = re.compile(r"""["']claude-[a-z0-9-]+["']""")
    for path in API_SRC.rglob("*.py"):
        if path.name == "config.py":
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), f"model id literal in {path}"


def test_no_level_codes_hardcoded_in_api_code():
    pattern = re.compile(r"""["'](A1|A2|B1|B2|C1|C2)["']""")
    for path in API_SRC.rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), f"level literal in {path}"
