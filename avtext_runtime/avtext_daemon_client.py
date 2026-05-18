# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from multiprocessing.connection import Client

PIPE_ADDRESS = r"\\.\pipe\avtext_runtime_daemon"
AUTHKEY = b"avtext-runtime-daemon"
COOLDOWN_SECONDS = 30.0
READY_WAIT_SECONDS = 0.30
READY_POLL_INTERVAL_SECONDS = 0.05
REQUEST_TIMEOUT_SECONDS = 1.20
SLOW_THRESHOLD_MS = 150
MODE_TITLE_AND_ACTRESS = "title_and_actress"
MODE_TITLE_ONLY = "title_only"
MODE_NO_TITLE = "no_title"
VALID_MODES = {MODE_TITLE_AND_ACTRESS, MODE_TITLE_ONLY, MODE_NO_TITLE}


class SimpleLogger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def log(self, message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3] + f" {message}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")


def get_base_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "sakura" / "avtext"
    return Path(__file__).resolve().parent


def build_state_path(base_dir: Path) -> Path:
    return base_dir / "daemon_state.json"


def build_log_path(base_dir: Path) -> Path:
    return base_dir / "avtext_daemon_client.log"


def build_python_choice_path(base_dir: Path) -> Path:
    return base_dir / "avtext_python_choice.txt"


def run_one_shot_fallback(mode: str, extra_args: list[str]):
    from avtext_service import run_one_shot

    return run_one_shot(mode, extra_args)


def load_state(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, patch: dict) -> None:
    state = load_state(path)
    state.update(patch)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def clear_cooldown_if_needed(path: Path) -> None:
    state = load_state(path)
    try:
        cooldown_until = float(state.get("cooldown_until", 0.0) or 0.0)
    except Exception:
        cooldown_until = 0.0

    if cooldown_until <= 0.0 and not state.get("last_error"):
        return

    save_state(
        path,
        {
            "cooldown_until": 0.0,
            "last_error": "",
            "last_attempt_at": time.time(),
        },
    )


def sync_healthy_state_if_needed(path: Path, payload: dict) -> None:
    daemon_pid = int((payload or {}).get("daemon_pid", 0) or 0)
    daemon_ready = bool((payload or {}).get("daemon_ready"))
    daemon_pipe = ((payload or {}).get("daemon_pipe") or "").strip()
    if daemon_pid <= 0 or not daemon_ready or not daemon_pipe:
        return

    state = load_state(path)
    try:
        cooldown_until = float(state.get("cooldown_until", 0.0) or 0.0)
    except Exception:
        cooldown_until = 0.0

    needs_update = False
    if int(state.get("daemon_pid", 0) or 0) != daemon_pid:
        needs_update = True
    elif not bool(state.get("daemon_ready")):
        needs_update = True
    elif (state.get("daemon_pipe") or "").strip() != daemon_pipe:
        needs_update = True
    elif cooldown_until > 0.0:
        needs_update = True
    elif state.get("last_error"):
        needs_update = True

    if not needs_update:
        return

    save_state(
        path,
        {
            "daemon_pid": daemon_pid,
            "daemon_ready": True,
            "daemon_pipe": daemon_pipe,
            "cooldown_until": 0.0,
            "last_error": "",
        },
    )


def activate_cooldown(path: Path, reason: str) -> None:
    save_state(
        path,
        {
            "cooldown_until": time.time() + COOLDOWN_SECONDS,
            "last_error": reason,
            "last_attempt_at": time.time(),
        },
    )


def is_cooldown_active(path: Path) -> bool:
    state = load_state(path)
    try:
        cooldown_until = float(state.get("cooldown_until", 0.0) or 0.0)
    except Exception:
        cooldown_until = 0.0
    return cooldown_until > time.time()


def send_request(payload: dict, *, timeout_sec: float):
    conn = Client(address=PIPE_ADDRESS, family="AF_PIPE", authkey=AUTHKEY)
    try:
        conn.send(payload)
        if not conn.poll(timeout_sec):
            raise TimeoutError(f"daemon response timeout after {timeout_sec:.2f}s")
        return conn.recv()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def daemon_available() -> bool:
    try:
        resp = send_request({"op": "ping"}, timeout_sec=0.10)
        return bool(resp and resp.get("ok"))
    except Exception:
        return False


def persist_python_choice(base_dir: Path) -> None:
    exe = (sys.executable or "").strip()
    if not exe:
        return
    path = build_python_choice_path(base_dir)
    try:
        current = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    except Exception:
        current = ""
    if current == exe:
        return
    path.write_text(exe, encoding="utf-8", newline="\n")


def start_daemon(base_dir: Path, logger: SimpleLogger) -> bool:
    daemon_script = base_dir / "avtext_daemon.py"
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000008 | 0x00000200 | 0x08000000

    try:
        subprocess.Popen(
            [sys.executable, "-u", str(daemon_script)],
            cwd=str(base_dir),
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as e:
        logger.log(f"[ERROR] daemon start failed: {e!r}")
        return False

    deadline = time.monotonic() + READY_WAIT_SECONDS
    while time.monotonic() < deadline:
        if daemon_available():
            return True
        time.sleep(READY_POLL_INTERVAL_SECONDS)

    logger.log("[WARN] daemon start timed out; fallback to one-shot")
    return False


def print_result_and_exit(payload: dict) -> int:
    message = (payload or {}).get("message", "")
    if message:
        print(message)
    return int((payload or {}).get("code", 1))


def run_via_daemon(mode: str, extra_args: list[str], logger: SimpleLogger):
    started = time.perf_counter()
    payload = send_request(
        {
            "op": "run",
            "mode": mode,
            "args": list(extra_args or []),
        },
        timeout_sec=REQUEST_TIMEOUT_SECONDS,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if elapsed_ms >= SLOW_THRESHOLD_MS:
        logger.log(f"[WARN] daemon request slow: mode={mode} elapsed_ms={elapsed_ms}")
    return payload


def main() -> int:
    if len(sys.argv) < 2:
        print("mode is required")
        return 2

    mode = (sys.argv[1] or "").strip()
    extra_args = sys.argv[2:]
    if mode not in VALID_MODES:
        print(f"unknown mode: {mode}")
        return 2

    base_dir = get_base_dir()
    state_path = build_state_path(base_dir)
    logger = SimpleLogger(build_log_path(base_dir))
    persist_python_choice(base_dir)

    if is_cooldown_active(state_path):
        logger.log(f"[INFO] cooldown active. fallback one-shot mode={mode}")
        result = run_one_shot_fallback(mode, extra_args)
        return print_result_and_exit(result.to_payload())

    try:
        payload = run_via_daemon(mode, extra_args, logger)
        sync_healthy_state_if_needed(state_path, payload)
        return print_result_and_exit(payload)
    except Exception as e:
        logger.log(f"[WARN] daemon request failed before start attempt: {e!r}")

    if not start_daemon(base_dir, logger):
        activate_cooldown(state_path, "daemon_start_failed")
        result = run_one_shot_fallback(mode, extra_args)
        return print_result_and_exit(result.to_payload())

    try:
        payload = run_via_daemon(mode, extra_args, logger)
        sync_healthy_state_if_needed(state_path, payload)
        return print_result_and_exit(payload)
    except Exception as e:
        logger.log(f"[WARN] daemon request failed after start: {e!r}")
        activate_cooldown(state_path, repr(e))
        result = run_one_shot_fallback(mode, extra_args)
        return print_result_and_exit(result.to_payload())


if __name__ == "__main__":
    sys.exit(main())
