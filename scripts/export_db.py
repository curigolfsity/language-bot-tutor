"""Export the local database to backups/tutor.dump (to move it to the server).

    uv run python scripts/export_db.py

Uses pg_dump from PG_BIN (default D:/PostgreSQL/16/bin) and the credentials in DATABASE_URL.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from tutor_api.config import get_settings  # noqa: E402


def main() -> None:
    url = urlsplit(get_settings().database_url.replace("+asyncpg", ""))
    pg_dump = Path(os.environ.get("PG_BIN", "D:/PostgreSQL/16/bin")) / "pg_dump"
    out = ROOT / "backups" / "tutor.dump"
    out.parent.mkdir(exist_ok=True)
    env = {**os.environ, "PGPASSWORD": unquote(url.password or "")}
    subprocess.run(
        [
            str(pg_dump),
            "-h",
            url.hostname or "localhost",
            "-p",
            str(url.port or 5432),
            "-U",
            unquote(url.username or ""),
            "-d",
            url.path.lstrip("/"),
            "-Fc",
            "--no-owner",
            "--no-privileges",
            "-f",
            str(out),
        ],
        env=env,
        check=True,
        timeout=300,
    )
    print(f"exported to {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
