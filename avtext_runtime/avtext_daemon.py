# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from multiprocessing.connection import Listener
from datetime import datetime

from avtext_common import SimpleLogger
from avtext_service import get_base_dir, AvTextRuntimeService


PIPE_ADDRESS = r"\\.\pipe\avtext_runtime_daemon"
AUTHKEY = b"avtext-runtime-daemon"


def build_state_path(base_dir: Path) -> Path:
    return base_dir / "daemon_state.json"


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


def main() -> int:
    base_dir = get_base_dir()
    state_path = build_state_path(base_dir)
    daemon_log = SimpleLogger(base_dir / "avtext_daemon.log")
    service = AvTextRuntimeService(base_dir, daemon_logger=daemon_log)
    listener = None
    listener_ready = False

    try:
        daemon_log.log("=== avtext_daemon start ===")
        listener = Listener(address=PIPE_ADDRESS, family="AF_PIPE", authkey=AUTHKEY)
        listener_ready = True
        save_state(
            state_path,
            {
                "daemon_pid": os.getpid(),
                "daemon_pipe": PIPE_ADDRESS,
                "daemon_ready": True,
                "daemon_last_start": datetime.now().isoformat(timespec="seconds"),
            },
        )

        while True:
            conn = listener.accept()
            try:
                req = conn.recv()
                op = (req.get("op") or "").strip()
                if op == "ping":
                    conn.send({"ok": True, "pid": os.getpid()})
                    continue
                if op == "shutdown":
                    conn.send({"ok": True, "shutdown": True})
                    break

                mode = req.get("mode", "")
                extra_args = list(req.get("args") or [])
                result = service.run_mode(mode, extra_args)
                payload = result.to_payload()
                payload["daemon_pid"] = os.getpid()
                payload["daemon_ready"] = True
                payload["daemon_pipe"] = PIPE_ADDRESS
                conn.send(payload)
            except Exception as e:
                daemon_log.log(f"[ERROR] request handling failed: {e!r}")
                try:
                    conn.send({"ok": False, "code": 1, "message": f"daemon error: {e!r}"})
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    except Exception as e:
        daemon_log.log(f"[ERROR] daemon failed: {e!r}")
        return 1
    finally:
        try:
            if listener is not None:
                listener.close()
        except Exception:
            pass
        service.close(daemon_log)
        if listener_ready:
            state = load_state(state_path)
            if int(state.get("daemon_pid", 0) or 0) == os.getpid():
                save_state(
                    state_path,
                    {
                        "daemon_pid": 0,
                        "daemon_ready": False,
                    },
                )
        daemon_log.log("=== avtext_daemon end ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
