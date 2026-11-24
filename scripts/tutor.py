"""Control the background tutor (API + Telegram bot). Use via tutor.cmd at the repo root:

tutor start | stop | restart | status
tutor logs [api|bot|supervisor] [-n 40]
tutor autostart on|off       start automatically when you log in to Windows
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from supervisor import (  # noqa: E402
    HEALTH_URL,
    LOG_DIR,
    PID_FILE,
    ROOT,
    STATE_FILE,
    api_healthy,
)

PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
SUPERVISOR = ROOT / "scripts" / "supervisor.py"
SHORTCUT_NAME = "Spanish Tutor.lnk"
STILL_ACTIVE = 259


def _pid_alive(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return bool(ok) and code.value == STILL_ACTIVE


def _is_python(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True,
    ).stdout.lower()  # fmt: skip
    return "python" in out


def running_pid() -> int | None:
    """The supervisor's pid, or None. Guards against a stale pid file reused by another app."""
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if _pid_alive(pid) and _is_python(pid):
        return pid
    PID_FILE.unlink(missing_ok=True)
    return None


def start() -> int:
    if pid := running_pid():
        print(f"Already running (supervisor pid {pid}).")
        return 0
    if api_healthy():
        print(
            "Something is already serving the API on port 8000.\n"
            "Close any `uvicorn` / `python -m tutor_telegram` windows first, then retry."
        )
        return 1
    subprocess.Popen(
        [str(PYTHONW), str(SUPERVISOR)], cwd=ROOT,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )  # fmt: skip
    print("Starting", end="", flush=True)
    for _ in range(60):
        time.sleep(0.5)
        print(".", end="", flush=True)
        if api_healthy():
            print(" API is up. The bot is starting too.")
            return status()
    print("\nThe API did not come up in 30s. Check: tutor logs api")
    return 1


def stop() -> int:
    pid = running_pid()
    if pid is None:
        print("Not running.")
        return 0
    # /T takes the API and bot (children) down with the supervisor.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.25)
    PID_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)
    print("Stopped.")
    return 0


def status() -> int:
    pid = running_pid()
    if pid is None:
        print("Status: stopped. Run: tutor start")
        return 1
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    print(f"Supervisor: running (pid {pid})")
    print(f"API:        {'healthy' if api_healthy() else 'NOT responding'} ({HEALTH_URL})")
    for name in ("api", "bot"):
        s = state.get(name, {})
        alive = "running" if s.get("running") else "restarting"
        print(f"  {name}: {alive}, restarts: {s.get('restarts', 0)}")
    print(f"Autostart at logon: {'on' if _shortcut().exists() else 'off'}")
    return 0


def logs(name: str, lines: int) -> int:
    path = LOG_DIR / f"{name}.log"
    if not path.exists():
        print(f"No log yet: {path}")
        return 1
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(text[-lines:]))
    return 0


def _startup_dir() -> Path:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Startup')"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    return Path(out)


def _shortcut() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def autostart(on: bool) -> int:
    lnk = _shortcut()
    if not on:
        lnk.unlink(missing_ok=True)
        print("Autostart off.")
        return 0
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath=$env:TARGET;$s.Arguments='\"'+$env:ARGS+'\"';"
        "$s.WorkingDirectory=$env:WD;$s.WindowStyle=7;$s.Save()"
    )
    env = {
        "LNK": str(lnk), "TARGET": str(PYTHONW), "ARGS": str(SUPERVISOR), "WD": str(ROOT),
    }  # fmt: skip
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=os.environ | env, check=True)
    print(f"Autostart on: the tutor starts by itself when you log in.\n  ({lnk})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="tutor", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("start", "stop", "restart", "status"):
        sub.add_parser(c)
    lp = sub.add_parser("logs")
    lp.add_argument("name", nargs="?", default="bot", choices=["api", "bot", "supervisor"])
    lp.add_argument("-n", type=int, default=40)
    ap = sub.add_parser("autostart")
    ap.add_argument("mode", choices=["on", "off"])
    a = p.parse_args()

    if a.cmd == "start":
        return start()
    if a.cmd == "stop":
        return stop()
    if a.cmd == "restart":
        stop()
        return start()
    if a.cmd == "status":
        return status()
    if a.cmd == "logs":
        return logs(a.name, a.n)
    return autostart(a.mode == "on")


if __name__ == "__main__":
    sys.exit(main())
