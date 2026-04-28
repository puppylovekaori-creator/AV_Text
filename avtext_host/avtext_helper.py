# -*- coding: utf-8 -*-
"""
Firefox Native Messaging host for AV text support.

target:
  - "title"           : title.txt を単一行に正規化して上書き
  - "actress"         : actress.txt を全置換
  - "actress_with_alias": actress.txt を「選択文字列()」で全置換
  - "no"              : no.txt を全置換
  - "focus_sakura"    : サクラエディタを最前面＆フォーカス
  - "check_actress"   : dbo.ACTRESS_DATA の OLD_NAME / NEW_NAME 完全一致で登録済判定
  - "register_actress": 未登録なら dbo.ACTRESS_DATA(OLD_NAME) に自動登録（クリック時のみ想定）

保存先:
  %APPDATA%\\sakura\\avtext\\title.txt / actress.txt / no.txt / setting.ini

ログ:
  （この .py のあるフォルダ）\\avtext_helper.log
"""

import sys
import os
import json
import struct
import subprocess
import time
import configparser
from pathlib import Path
from datetime import datetime
import ctypes
from ctypes import wintypes

# ---------- パス（配置フォルダ基準） ----------
HOST_DIR = Path(__file__).resolve().parent
LOG_PATH = HOST_DIR / "avtext_helper.log"

OUT_DIR = Path(os.environ.get("APPDATA", "")) / "sakura" / "avtext"
TITLE_PATH = OUT_DIR / "title.txt"
ACTRESS_PATH = OUT_DIR / "actress.txt"
NO_PATH = OUT_DIR / "no.txt"
SETTING_INI_PATH = OUT_DIR / "setting.ini"
MENU_ORDER_MODE_PATH = OUT_DIR / "menu_order_mode.json"

RELOAD_TASK_NAME = "AvText_ReloadTitle_Admin"
DEFAULT_MENU_ORDER_MODE = "top"
VALID_MENU_ORDER_MODES = {"top", "near_cursor"}

# ---------- pyodbc ----------
try:
    import pyodbc  # type: ignore
    pyodbc.pooling = False  # type: ignore  # IMC06 対策：死んだ接続をプールから掴まない
except Exception as e:
    pyodbc = None  # type: ignore


def debug_log(msg: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        HOST_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


def _read_exact(n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sys.stdin.buffer.read(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


def read_message():
    raw_len = _read_exact(4)
    if not raw_len:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    if msg_len <= 0:
        return {}
    raw = _read_exact(msg_len)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def send_message(obj) -> None:
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(raw)))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def write_text_full(path: Path, text: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text if text is not None else "")
        f.write("\n")


def _normalize_single_line_text(text: str) -> str:
    text = "" if text is None else str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    return " ".join(parts).strip()


def write_first_line(path: Path, text: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_single_line_text(text)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(normalized)
        f.write("\n")


def normalize_menu_order_mode(mode: str) -> str:
    mode = (mode or "").strip()
    return mode if mode in VALID_MENU_ORDER_MODES else DEFAULT_MENU_ORDER_MODE


def read_menu_order_mode() -> str:
    try:
        if not MENU_ORDER_MODE_PATH.exists():
            return DEFAULT_MENU_ORDER_MODE
        raw = MENU_ORDER_MODE_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            return DEFAULT_MENU_ORDER_MODE
        payload = json.loads(raw)
        return normalize_menu_order_mode(payload.get("mode", ""))
    except Exception as e:
        debug_log(f"[WARN] read_menu_order_mode failed: {e!r}")
        return DEFAULT_MENU_ORDER_MODE


def write_menu_order_mode(mode: str) -> str:
    normalized = normalize_menu_order_mode(mode)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"mode": normalized}
    MENU_ORDER_MODE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return normalized


def focus_sakura_window() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    candidates = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lParam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        t_low = title.lower()
        if ("sakura" in t_low) or ("サクラ" in title):
            candidates.append((hwnd, title))
        return True

    user32.EnumWindows(enum_proc, 0)

    if not candidates:
        return "NG(no_window)"

    hwnd, title = candidates[0]

    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)

    try:
        fg = user32.GetForegroundWindow()
        cur_tid = kernel32.GetCurrentThreadId()

        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)

        if fg_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
        user32.AttachThreadInput(cur_tid, target_tid, True)

        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetFocus(hwnd)

    finally:
        try:
            if fg_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            user32.AttachThreadInput(cur_tid, target_tid, False)
        except Exception:
            pass

    return f"OK({title})"


# ===================== DB 設定（setting.ini） =====================

def _clean(v: str, default: str = "") -> str:
    if v is None:
        v = default
    return str(v).strip().strip("'\"")


def load_db_config_from_ini():
    if not SETTING_INI_PATH.exists():
        debug_log(f"[WARN] setting.ini not found: {SETTING_INI_PATH}")
        return None

    config = configparser.ConfigParser()
    try:
        config.read(SETTING_INI_PATH, encoding="utf-8")
    except Exception as e:
        debug_log(f"[WARN] setting.ini read failed: {e!r}")
        return None

    if config.has_section("DB Setting"):
        section = config["DB Setting"]
    elif config.has_section("DB"):
        section = config["DB"]
    else:
        debug_log("[WARN] setting.ini: section [DB Setting] or [DB] not found.")
        return None

    server = _clean(section.get("IP") or section.get("Server") or "")
    user = _clean(section.get("User") or "")
    password = _clean(section.get("Password") or "")
    database = _clean(section.get("Database") or "")

    if not server or not user or not database:
        debug_log(f"[WARN] setting.ini incomplete: server={bool(server)} user={bool(user)} db={bool(database)}")
        return None

    # port は指定がなければ 1433
    port = _clean(section.get("Port") or "1433")
    if port:
        server_for_odbc = f"{server},{port}"
    else:
        server_for_odbc = server

    cfg = {
        "server": server_for_odbc,
        "user": user,
        "password": password,
        "database": database,
    }
    debug_log(f"[INFO] DB config loaded (ini): server={cfg['server']}, database={cfg['database']}")
    return cfg


def get_db_connection():
    if pyodbc is None:
        raise RuntimeError("pyodbc is not available")

    cfg = load_db_config_from_ini()
    if cfg is None:
        raise RuntimeError(f"DB config not available (need {SETTING_INI_PATH})")

    driver_candidates = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
    ]

    last_err = None
    for drv in driver_candidates:
        conn_str = (
            f"DRIVER={{{drv}}};"
            f"SERVER={cfg['server']};"
            f"DATABASE={cfg['database']};"
            f"UID={cfg['user']};PWD={cfg['password']};"
            "TrustServerCertificate=yes;"
        )
        try:
            # 毎回新規接続（DB落ち→復帰の後でも IMC06 を引きずらない）
            conn = pyodbc.connect(conn_str, timeout=3, autocommit=True)
            debug_log(f"[INFO] DB connected with driver '{drv}'.")
            return conn
        except Exception as e:
            last_err = e
            debug_log(f"[WARN] DB connect failed with '{drv}': {e!r}")

    raise RuntimeError(f"All DB connect attempts failed: {last_err!r}")


def _build_display_name(name: str, rows) -> str:
    name = (name or "").strip()
    best_display = name
    best_score = -1

    for row in rows or []:
        try:
            old_name, new_name, display_name = row
        except Exception:
            continue

        old_s = (old_name or "").strip()
        new_s = (new_name or "").strip()
        disp_s = (display_name or "").strip()

        if disp_s:
            candidate = disp_s
            score = 3
        elif old_s and new_s:
            candidate = f"{old_s}({new_s})"
            score = 2
        else:
            candidate = old_s or new_s or name
            score = 1 if candidate else 0

        if old_s == name or new_s == name:
            score += 1

        if score > best_score and candidate:
            best_display = candidate
            best_score = score

    return best_display or name


def _check_actress_and_maybe_register(name: str, do_register: bool):
    """
    戻り:
      found_before: bool
      has_alias: bool
      display_name: str
      registered: bool
      already_exists: bool
    """
    name = (name or "").strip()
    if not name:
        return False, False, "", False, False

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 判定（OLD/NEWの完全一致）
        cur.execute(
            "SELECT OLD_NAME, NEW_NAME, DISPLAY_NAME FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ? OR NEW_NAME = ?",
            (name, name),
        )
        rows = cur.fetchall()
        found_before = bool(rows)
        has_alias = any(
            bool((old_name or "").strip()) and bool((new_name or "").strip())
            for old_name, new_name, _display_name in rows
        )
        display_name = _build_display_name(name, rows)

        if found_before:
            return True, has_alias, display_name, False, True

        if not do_register:
            return False, False, name, False, False

        # 登録（OLD_NAMEのみ）
        # 念のため二重チェック
        cur.execute(
            "SELECT OLD_NAME, NEW_NAME, DISPLAY_NAME FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ? OR NEW_NAME = ?",
            (name, name),
        )
        rows2 = cur.fetchall()
        if rows2:
            has_alias = any(
                bool((old_name or "").strip()) and bool((new_name or "").strip())
                for old_name, new_name, _display_name in rows2
            )
            display_name = _build_display_name(name, rows2)
            return True, has_alias, display_name, False, True

        cur.execute(
            "INSERT INTO dbo.ACTRESS_DATA (OLD_NAME) VALUES (?)",
            (name,),
        )
        return False, False, name, True, False

    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def handle_message(msg: dict) -> dict:
    target = msg.get("target")
    text = msg.get("text", "")
    req_id = msg.get("req_id")

    if target == "title":
        write_first_line(TITLE_PATH, text)
        return {"status": "ok", "target": target, "req_id": req_id}

    if target == "actress":
        write_text_full(ACTRESS_PATH, text)
        return {"status": "ok", "target": target, "req_id": req_id}

    if target == "actress_with_alias":
        normalized_text = _normalize_single_line_text(text)
        actress_text = f"{normalized_text}()" if normalized_text else "()"
        write_text_full(ACTRESS_PATH, actress_text)
        return {
            "status": "ok",
            "target": target,
            "req_id": req_id,
            "text": actress_text,
        }

    if target == "no":
        write_text_full(NO_PATH, text)
        return {"status": "ok", "target": target, "req_id": req_id}

    if target == "focus_sakura":
        res = focus_sakura_window()
        return {"status": "ok", "target": target, "req_id": req_id, "result": res}

    if target == "get_menu_order_mode":
        mode = read_menu_order_mode()
        return {"status": "ok", "target": target, "req_id": req_id, "mode": mode}

    if target == "set_menu_order_mode":
        mode = write_menu_order_mode(text)
        return {"status": "ok", "target": target, "req_id": req_id, "mode": mode}

    if target == "check_actress":
        # ここでは登録しない（クリック登録は register_actress 側）
        try:
            debug_log("[INFO] check_actress start")
            found_before, has_alias, display_name, registered, already_exists = _check_actress_and_maybe_register(
                text,
                do_register=False,
            )
            return {
                "status": "ok",
                "target": target,
                "req_id": req_id,
                "found": bool(found_before),
                "has_alias": bool(has_alias),
                "display_name": display_name or text,
            }
        except Exception as e:
            debug_log(f"[WARN] check_actress failed: {e!r}")
            return {"status": "error", "target": target, "req_id": req_id, "error": str(e)}

    if target == "register_actress":
        # クリック時のみ登録
        try:
            debug_log("[INFO] register_actress start")
            found_before, has_alias, display_name, registered, already_exists = _check_actress_and_maybe_register(
                text,
                do_register=True,
            )
            return {
                "status": "ok",
                "target": target,
                "req_id": req_id,
                "registered": bool(registered),
                "already_exists": bool(already_exists or found_before),
                "has_alias": bool(has_alias),
                "display_name": display_name or text,
            }
        except Exception as e:
            debug_log(f"[WARN] register_actress failed: {e!r}")
            return {"status": "error", "target": target, "req_id": req_id, "error": str(e)}

    return {"status": "error", "target": target, "req_id": req_id, "error": f"unknown target: {target!r}"}


def main() -> int:
    debug_log("=== avtext_helper start: ===")
    debug_log(f"[INFO] host_file={__file__}")
    debug_log(f"[INFO] pid={os.getpid()}")

    while True:
        try:
            msg = read_message()
            if msg is None:
                debug_log("read_message: EOF")
                break

            debug_log(f"read_message: {msg!r}")
            resp = handle_message(msg)
            debug_log(f"send_message: {resp!r}")
            send_message(resp)

        except Exception as e:
            debug_log(f"ERROR: {e!r}")
            try:
                send_message({"status": "error", "error": str(e)})
            except Exception:
                pass

    debug_log("=== avtext_helper end ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
