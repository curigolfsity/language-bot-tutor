"""Background supervisor: keeps the core API and the Telegram bot running.

Runs windowless (started with pythonw by `tutor start` or at Windows logon), restarts a
child that exits, and writes logs to logs/. Control it with `tutor.cmd` at the repo root.
Standard library only, so it never depends on the app's own imports working.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / ".run"
LOG_DIR = ROOT / "logs"
PID_FILE = RUN_DIR / "supervisor.pid"
STATE_FILE = RUN_DIR / "state.json"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

API_HOST, API_PORT = "127.0.0.1", 8000
HEALTH_URL = f"http://{API_HOST}:{API_PORT}/healthz"

SERVICES: dict[str, list[str]] = {
    "api": [
        str(PYTHON), "-m", "uvicorn", "tutor_api.main:app",
        "--host", API_HOST, "--port", str(API_PORT),
    ],
    "bot": [str(PYTHON), "-m", "tutor_telegram"],
}  # fmt: skip

MAX_LOG_BYTES = 5 * 1024 * 1024
HEALTHY_RUN_SECONDS = 60  # a child that ran this long resets its restart backoff
MIN_BACKOFF, MAX_BACKOFF = 2.0, 300.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    with open(LOG_DIR / "supervisor.log", "a", encoding="utf-8") as f:
        f.write(line)


def open_log(name: str):
    path = LOG_DIR / f"{name}.log"
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        path.replace(path.with_suffix(".log.1"))
    return open(path, "ab")


def api_healthy(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


class Child:
    def __init__(self, name: str, cmd: list[str]) -> None:
        self.name, self.cmd = name, cmd
        self.proc: subprocess.Popen[bytes] | None = None
        self.started = 0.0
        self.backoff = MIN_BACKOFF
        self.next_start = 0.0
        self.restarts = 0

    def start(self) -> None:
        env = os.environ | {"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        out = open_log(self.name)
        self.proc = subprocess.Popen(
            self.cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
        )  # fmt: skip
        out.close()  # the child holds its own handle
        self.started = time.monotonic()
        log(f"{self.name}: started (pid {self.proc.pid})")

    def poll(self) -> None:
        now = time.monotonic()
        if self.proc is None:
            if now >= self.next_start:
                self.start()
            return
        code = self.proc.poll()
        if code is None:
            return
        ran = now - self.started
        self.backoff = (
            MIN_BACKOFF if ran >= HEALTHY_RUN_SECONDS else min(self.backoff * 2, MAX_BACKOFF)
        )
        self.proc, self.next_start = None, now + self.backoff
        self.restarts += 1
        log(f"{self.name}: exited with code {code} after {ran:.0f}s; "
            f"restarting in {self.backoff:.0f}s (see logs/{self.name}.log)")  # fmt: skip

    def state(self) -> dict:
        return {
            "running": self.proc is not None,
            "pid": self.proc.pid if self.proc else None,
            "restarts": self.restarts,
        }


def write_state(children: list[Child]) -> None:
    STATE_FILE.write_text(
        json.dumps({"supervisor_pid": os.getpid(), **{c.name: c.state() for c in children}}),
        encoding="utf-8",
    )


def main() -> int:
    RUN_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    if api_healthy():
        log("refusing to start: something is already serving the API on port "
            f"{API_PORT} (a manual `uvicorn` window?)")  # fmt: skip
        return 1
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log(f"supervisor started (pid {os.getpid()})")

    api, bot = Child("api", SERVICES["api"]), Child("bot", SERVICES["bot"])
    api.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and api.proc and api.proc.poll() is None:
        if api_healthy():
            break
        time.sleep(0.5)
    children = [api, bot]
    try:
        while True:
            for c in children:
                c.poll()
            write_state(children)
            time.sleep(1)
    finally:
        for c in children:
            if c.proc and c.proc.poll() is None:
                c.proc.kill()
        PID_FILE.unlink(missing_ok=True)
        STATE_FILE.unlink(missing_ok=True)
        log("supervisor stopped")


if __name__ == "__main__":
    sys.exit(main())
