# av_title_convert.py
# -*- coding: utf-8 -*-
"""
av_title_convert.py

「タイトル単体変換」専用スクリプト（title.txt絶対パス固定版・要件反映版）。

要件
- title.txt の先頭1行（タイトル）のみを対象。
- actress.txt参照による女優名付与はしない。
- 新規女優のDB/CSV登録や更新はしない。

表示ルール
- タイトル末尾が既登録女優名(old/new)なら、その末尾部分を display に変換。
  ※末尾に連続して並ぶ複数女優名も「末尾に出てきている」とみなす。
- そのうえで、タイトル文中にいる既登録女優のうち
  「末尾に出てきていない女優」は display を末尾に追加付与する。

入出力（固定）
- 入力:
    %APPDATA%\\sakura\\avtext\\title.txt
- 出力:
    %APPDATA%\\sakura\\avtext\\conv_converted.txt
- 文字コード:
    出力は常に cp932(SJIS)

追加修正
- av_text_convert.py と同じ多段エイリアス解決（OLD->NEW の推移解決）
- 異体字吸収（実害確認分）：步 -> 歩
- 長さ超過は切り詰めずWARNのみ（av_text_convert.py と方針統一）
"""

import os
import csv
import re
import configparser
from pathlib import Path
from datetime import datetime

MAX_FILENAME_LEN = 240

# 実害が出たものだけ最小限で吸収（過剰変換を避ける）
VARIANT_CHAR_MAP = {
    "步": "歩",
}


def normalize_variant_chars(text: str) -> str:
    if not text:
        return text
    return "".join(VARIANT_CHAR_MAP.get(ch, ch) for ch in text)


# ===================== 固定パス（%APPDATA% 基準） =====================

def get_base_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "sakura" / "avtext"
    # 念のためのフォールバック（ほぼ通らない想定）
    return Path.home() / "AppData" / "Roaming" / "sakura" / "avtext"


BASE_DIR = get_base_dir()

TITLE_PATH = BASE_DIR / "title.txt"
OUTPUT_PATH = BASE_DIR / "conv_converted.txt"
ALIASES_CSV = BASE_DIR / "aliases.csv"
SETTING_INI = BASE_DIR / "setting.ini"
LOG_PATH = BASE_DIR / "av_title_convert.log"


def log(msg: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # BASE_DIR がないとログも書けないので、親だけは作る（中身は作らない）
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


log("=== av_title_convert start ===")
log(f"[INFO] BASE_DIR={BASE_DIR}")
log(f"[INFO] TITLE_PATH={TITLE_PATH}")
log(f"[INFO] OUTPUT_PATH={OUTPUT_PATH}")

try:
    import pyodbc  # type: ignore
except Exception as e:
    pyodbc = None  # type: ignore
    log(f"[WARN] pyodbc import failed: {e!r}")


# ===================== DB 設定/接続 =====================

def load_db_config():
    if not SETTING_INI.exists():
        log("[INFO] setting.ini not found. DB access disabled.")
        return None

    config = configparser.ConfigParser()
    try:
        config.read(SETTING_INI, encoding="utf-8")
    except Exception as e:
        log(f"[WARN] failed to read setting.ini: {e!r}")
        return None

    if config.has_section("DB Setting"):
        section = config["DB Setting"]
    elif config.has_section("DB"):
        section = config["DB"]
    else:
        log("[WARN] setting.ini: section [DB Setting] or [DB] not found.")
        return None

    def clean(v, default=""):
        if v is None:
            v = default
        return v.strip().strip("'\"")

    server = clean(section.get("IP") or section.get("Server") or "localhost")
    user = clean(section.get("User") or "sa")
    password = clean(section.get("Password") or "")
    database = clean(section.get("Database") or "FileDB")

    cfg = {"server": server, "user": user, "password": password, "database": database}
    log(f"[INFO] DB config loaded: server={server}, database={database}")
    return cfg


def get_db_connection():
    if pyodbc is None:
        log("[INFO] pyodbc not available. Use CSV aliases.")
        return None

    cfg = load_db_config()
    if cfg is None:
        return None

    driver_candidates = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
    ]
    try:
        for d in pyodbc.drivers():
            if "SQL Server" in d and d not in driver_candidates:
                driver_candidates.append(d)
    except Exception:
        pass

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
            conn = pyodbc.connect(conn_str, timeout=3)
            log(f"[INFO] DB connected with driver '{drv}'.")
            return conn
        except Exception as e:
            last_err = e
            log(f"[WARN] DB connect failed with '{drv}': {e!r}")

    log(f"[WARN] All DB connect attempts failed. Use CSV aliases. last_err={last_err!r}")
    return None


# ===================== エイリアス読み込み =====================

def load_aliases_from_csv(csv_path: Path):
    aliases = []
    if not csv_path.exists():
        log(f"[INFO] aliases.csv not found: {csv_path}")
        return aliases

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old = normalize_variant_chars((row.get("old") or "").strip())
            new = normalize_variant_chars((row.get("new") or "").strip())
            disp = normalize_variant_chars((row.get("display") or "").strip())

            if not old and not new and not disp:
                continue

            if not disp:
                if new and old:
                    disp = f"{old}({new})"
                elif new:
                    disp = new
                elif old:
                    disp = old

            aliases.append((old, new, disp))

    log(f"[INFO] {len(aliases)} aliases loaded from CSV.")
    return aliases


def load_aliases_from_db(conn):
    aliases = []
    sql = """
        SELECT OLD_NAME, NEW_NAME, DISPLAY_NAME
        FROM dbo.ACTRESS_DATA
    """
    try:
        cur = conn.cursor()
        cur.execute(sql)
        for old, new, disp in cur:
            old = normalize_variant_chars((old or "").strip())
            new = normalize_variant_chars((new or "").strip())
            disp = normalize_variant_chars((disp or "").strip())

            if not old and not new and not disp:
                continue

            if not disp:
                if new and old:
                    disp = f"{old}({new})"
                elif new:
                    disp = new
                elif old:
                    disp = old

            aliases.append((old, new, disp))

        log(f"[INFO] {len(aliases)} aliases loaded from DB.")
    except Exception as e:
        log(f"[ERROR] load_aliases_from_db failed: {e!r}")
    return aliases


def load_aliases(conn):
    if conn is not None:
        aliases = load_aliases_from_db(conn)
        if aliases:
            return aliases
        log("[WARN] DB returned no aliases. Fallback to CSV.")
    return load_aliases_from_csv(ALIASES_CSV)


def build_alias_helpers(aliases):
    """
    av_text_convert.py と同じ方針：
      OLD -> NEW を終端まで辿ってチェーン全体を同一displayへ寄せる。
      DISPLAY_NAME がどこかにあれば終端側を優先。
      DISPLAY_NAME が無い場合は「最後のOLD(終端NEW)」をdisplayにする。
    """
    old_to_new = {}
    display_by_old = {}
    all_names = set()
    explicit_displays = set()

    for old, new, disp in aliases:
        old = normalize_variant_chars((old or "").strip())
        new = normalize_variant_chars((new or "").strip())
        disp = normalize_variant_chars((disp or "").strip())

        if old:
            all_names.add(old)
        if new:
            all_names.add(new)
        if disp:
            explicit_displays.add(disp)

        if old and new:
            old_to_new[old] = new
        if old and disp:
            display_by_old[old] = disp

    name_to_display = {}
    canonical_displays = set()
    visited_global = set()

    for start_old in list(old_to_new.keys()):
        if start_old in visited_global:
            continue

        chain = []
        seen = set()
        cur = start_old
        last_old = cur

        while True:
            if cur in seen:
                log(f"[WARN] alias chain cycle detected: start={start_old}, at={cur}, chain={chain}")
                break
            seen.add(cur)
            chain.append(cur)

            nxt = old_to_new.get(cur, "")
            if nxt:
                last_old = cur
                cur = nxt
                continue
            break

        terminal = chain[-1] if chain else start_old

        canonical = None
        for node in reversed(chain):
            if node in display_by_old and display_by_old[node]:
                canonical = display_by_old[node]
                break

        if canonical is None:
            if last_old and terminal and last_old != terminal:
                canonical = f"{last_old}({terminal})"
            else:
                canonical = terminal or start_old

        canonical = normalize_variant_chars(canonical)

        canonical_displays.add(canonical)
        for node in chain:
            name_to_display[node] = canonical

        visited_global |= set(chain)

    # 孤立ノード（OLD->NEWチェーンに乗っていない名前）
    for n in all_names:
        if n in name_to_display:
            continue
        if n in display_by_old and display_by_old[n]:
            disp = normalize_variant_chars(display_by_old[n])
            name_to_display[n] = disp
            canonical_displays.add(disp)
        else:
            name_to_display[n] = n

    alias_names_sorted = sorted(all_names, key=len, reverse=True)
    known_tokens = set(all_names) | explicit_displays | canonical_displays
    return alias_names_sorted, name_to_display, known_tokens


# ===================== 文字正規化（タイトル用） =====================

def sanitize_for_windows_filename(name: str) -> str:
    trans = str.maketrans({
        '\\': '＼',
        '/': ' ',
        ':': '：',
        '*': '＊',
        '?': '？',
        '"': '”',
        '<': '＜',
        '>': '＞',
        '|': '｜',
    })
    name = name.translate(trans)
    name = re.sub(r'[\x00-\x1F]', '', name)
    name = name.rstrip(" .")

    # 切り詰めない（WARNのみ）
    if len(name) > MAX_FILENAME_LEN:
        log(f"[WARN] filename length over threshold: len={len(name)} > {MAX_FILENAME_LEN} (no truncation)")

    return name


def normalize_title_text(raw: str) -> str:
    text = normalize_variant_chars(raw.strip())
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = text.replace("　", " ")

    # スラッシュ区切りを先に分割できるようスペース化
    text = text.replace("／", "/")
    text = text.replace("/", " ")

    text = text.replace("F**K", "FUCK")
    text = text.replace("*", "＊")

    text = re.sub(r"[ ]+", " ", text)
    return text.strip()


def load_first_line_fixed(path: Path):
    data = None
    enc_used = None
    for enc in ("utf-8", "cp932"):
        try:
            with path.open("r", encoding=enc) as f:
                data = f.read()
            enc_used = enc
            break
        except UnicodeDecodeError:
            continue

    if data is None:
        raise UnicodeError(f"failed to decode {path} as utf-8 / cp932")

    lines = data.splitlines()
    first = lines[0].strip() if lines else ""
    return first, enc_used or "unknown"


# ===================== 検出/組み立て =====================

def detect_registered_names_in_title(title: str, candidate_names):
    found = []
    seen = set()
    for name in candidate_names:
        if not name:
            continue
        if name in title and name not in seen:
            seen.add(name)
            found.append(name)
    return found


def resolve_tail_display(token: str, name_to_display, display_set):
    token = normalize_variant_chars(token)
    if token in name_to_display:
        return name_to_display[token]
    if token in display_set:
        return token
    return None


def convert_title_only(title_line: str, aliases):
    alias_names_sorted, name_to_display, _known_tokens = build_alias_helpers(aliases)
    candidate_names = alias_names_sorted
    display_set = set(name_to_display.values())

    normalized_title = normalize_title_text(title_line)
    tokens = normalized_title.split()

    tail_display = None
    tail_display_set = set()

    i = len(tokens) - 1
    while i >= 0:
        disp = resolve_tail_display(tokens[i], name_to_display, display_set)
        if not disp:
            break
        tokens[i] = disp
        tail_display_set.add(disp)
        tail_display = disp
        i -= 1

    matched_names = detect_registered_names_in_title(normalized_title, candidate_names)

    matched_displays = []
    seen_disp = set()
    for n in matched_names:
        disp = name_to_display.get(n, n)
        if disp:
            disp = normalize_variant_chars(disp)
        if disp and disp not in seen_disp:
            seen_disp.add(disp)
            matched_displays.append(disp)

    extra_displays = []
    for disp in matched_displays:
        if disp in tail_display_set:
            continue
        if disp not in extra_displays:
            extra_displays.append(disp)

    base = " ".join(tokens)
    if extra_displays:
        base = (base + " " + " ".join(extra_displays)).strip()

    base = sanitize_for_windows_filename(base)
    base = re.sub(r"[ ]+", " ", base).strip()

    if not base.lower().endswith(".mp4"):
        base += ".mp4"

    if len(base) > MAX_FILENAME_LEN:
        log(f"[WARN] filename length over threshold after ext: len={len(base)} > {MAX_FILENAME_LEN} (no truncation)")

    return base + "\n", matched_names, tail_display, extra_displays


# ===================== main =====================

def main():
    conn = get_db_connection()
    aliases = load_aliases(conn)

    if not TITLE_PATH.exists():
        msg = f"title.txt が見つかりません: {TITLE_PATH}"
        print(msg)
        log(f"[ERROR] {msg}")
        return

    try:
        title_line, enc = load_first_line_fixed(TITLE_PATH)
    except UnicodeError:
        msg = "title.txt の文字コードを utf-8 / cp932 で読めませんでした。"
        print(msg)
        log(f"[ERROR] {msg}")
        return

    converted, matched_names, tail_display, extra_displays = convert_title_only(title_line, aliases)

    try:
        # 出力先ディレクトリは確実に作る
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = converted.encode("cp932", errors="ignore")
        decoded = encoded.decode("cp932")
        if decoded != converted:
            log("[WARN] cp932 encode(decode) caused character drop/replacement in output text.")
        with OUTPUT_PATH.open("w", encoding="cp932", newline=None) as f:
            f.write(decoded)
        log(f"[INFO] output written: {OUTPUT_PATH}")
    except Exception as e:
        log(f"[ERROR] failed to write output: {e!r}")
        raise

    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass

    log(f"[INFO] matched_names={matched_names}")
    log(f"[INFO] tail_display={tail_display}")
    log(f"[INFO] extra_displays={extra_displays}")

    print(
        f"変換完了: {OUTPUT_PATH} "
        f"（input: {TITLE_PATH} encoding={enc}, output: cp932, CRLF, .mp4付き）"
    )
    log("=== av_title_convert end ===")


if __name__ == "__main__":
    main()