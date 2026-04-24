# av_text_convert.py
# -*- coding: utf-8 -*-
"""
av_text_convert.py

サクラエディタの長いマクロを置き換える用スクリプト（DB版）。

・記号／空白の正規化
・F**K -> FUCK（それ以外の半角 * は全角 ＊ に）
・Windows 禁止文字 (\ / : * ? " < > |) を全角記号に変換
・別名 → display への統一（ACTRESS_DATA or aliases.csv で管理）
・DB/CSV に登録されている名前は、出現位置でスペース区切りになるよう分割
・同じ名前（display 含む）は 1 回だけに整理
・未登録の名前は DB(または CSV) に old だけの行として追加（1 行目の単語は除外）
・「短い名(本名)」「本名(短い名)」「(短い名)本名」からエイリアスを自動生成して DB/CSV 更新
・行全体が同じ文字列 2 回なら 1 回に圧縮（初愛ねんね初愛ねんね など）
・最終的に 1 行にまとめて出力し、末尾に .mp4 を付与

★追加修正
- NEW_NAME が別レコードの OLD_NAME を指す「多段エイリアス」を推移的に解決し、
  チェーン内の全名称（旧/中継/新）を同一 display に寄せる。
  循環があっても無限ループしない（WARNして停止）。
- 異体字吸収（実害確認分）：步 -> 歩
  ※一般的なUnicode正規化だけでは吸えない/副作用が出る場合があるため、まずは明示マップで対応
"""

import sys
import csv
import re
import configparser
from pathlib import Path
from datetime import datetime

# ===================== 共通設定 =====================

# ここは「切り詰め」ではなく「警告の目安」としてだけ使う
MAX_FILENAME_LEN = 240

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "av_text_convert.log"

# 実害が出たものだけ最小限で吸収（過剰変換を避ける）
VARIANT_CHAR_MAP = {
    "步": "歩",
}


def normalize_variant_chars(text: str) -> str:
    if not text:
        return text
    return "".join(VARIANT_CHAR_MAP.get(ch, ch) for ch in text)


def log(msg: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


log("=== av_text_convert start ===")

try:
    import pyodbc  # type: ignore
except Exception as e:
    pyodbc = None  # type: ignore
    log(f"[WARN] pyodbc import failed: {e!r}")


# ===================== DB アクセス =====================

def load_db_config():
    ini_path = SCRIPT_DIR / "setting.ini"
    if not ini_path.exists():
        log("[INFO] setting.ini not found. DB access disabled.")
        return None

    config = configparser.ConfigParser()
    try:
        config.read(ini_path, encoding="utf-8")
    except Exception as e:
        log(f"[WARN] failed to read setting.ini: {e!r}")
        return None

    section = None
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
    """
    戻り値: list[tuple(old, new, display)]
    """
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

            aliases.append((old, new, disp))

    log(f"[INFO] {len(aliases)} aliases loaded from CSV.")
    return aliases


def load_aliases_from_db(conn):
    """
    戻り値: list[tuple(old, new, display)]
    """
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

            aliases.append((old, new, disp))

        log(f"[INFO] {len(aliases)} aliases loaded from DB.")
    except Exception as e:
        log(f"[ERROR] load_aliases_from_db failed: {e!r}")
    return aliases


def load_aliases(aliases_csv: Path, conn):
    if conn is not None:
        aliases = load_aliases_from_db(conn)
        if aliases:
            return aliases
        log("[WARN] DB returned no aliases. Fallback to CSV.")
    return load_aliases_from_csv(aliases_csv)


def build_alias_helpers(aliases):
    """
    多段エイリアス対応：
      OLD -> NEW を辿って終端まで解決し、チェーン内の全名称を同一displayへ寄せる。
      DISPLAY_NAME がどこかにあれば優先（終端側を優先）。
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

        # canonical display を決める（終端側の DISPLAY_NAME を優先）
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

    # 孤立（old_to_new のキーに出てこないが名前として存在する）も扱う
    # → 表示名があるならそれ、なければ自分自身
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


# ===================== 前処理系 =====================

def insert_spaces_for_aliases(text: str, alias_names_sorted):
    """
    既知名の直後にだけスペース（最長一致greedy走査）。
    """
    if not text:
        return text

    cand_sorted = [n for n in alias_names_sorted if n]

    # 先頭文字インデックス（軽い高速化）
    by_first = {}
    for name in cand_sorted:
        by_first.setdefault(name[0], []).append(name)

    out = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        matched = None

        cand_list = by_first.get(ch)
        if cand_list:
            for name in cand_list:
                if text.startswith(name, i):
                    prev = text[i - 1] if i > 0 else ""
                    nextc = text[i + len(name)] if i + len(name) < n else ""

                    # 括弧内の破壊回避（A(B) / (A)B を壊さない）
                    if prev in ("(", "（"):
                        continue
                    if nextc in (")", "）", "(", "（"):
                        continue

                    matched = name
                    break

        if matched:
            out.append(matched)

            # 既知名の「直後」だけスペース（必要なときだけ）
            j = i + len(matched)
            if j < n:
                nxt = text[j]
                if (not nxt.isspace()) and (nxt not in (")", "）", "(", "（")):
                    out.append(" ")

            i += len(matched)
        else:
            out.append(ch)
            i += 1

    return "".join(out)


def insert_spaces_around_aliases_for_registration(text: str, alias_names_sorted, name_to_display: dict):
    """
    登録ソース専用：既知名が連結されている前提で前後にスペースを入れる（最長一致）。
    """
    if not text:
        return text

    # 候補トークン：old/new に加えて、括弧や空白を含まない display も保護対象に入れる
    candidates = set(n for n in alias_names_sorted if n)
    for disp in set(name_to_display.values()):
        d = normalize_variant_chars((disp or "").strip())
        if not d:
            continue
        if re.search(r"[\s()（）]", d):
            continue
        candidates.add(d)

    cand_sorted = sorted(candidates, key=len, reverse=True)

    # 先頭文字インデックス（簡易高速化）
    by_first = {}
    for name in cand_sorted:
        by_first.setdefault(name[0], []).append(name)

    out = []
    i = 0
    n = len(text)

    def is_ws(ch: str) -> bool:
        return bool(ch) and ch.isspace()

    while i < n:
        ch = text[i]
        matched = None

        cand_list = by_first.get(ch)
        if cand_list:
            for name in cand_list:
                if text.startswith(name, i):
                    prev = text[i - 1] if i > 0 else ""
                    nextc = text[i + len(name)] if i + len(name) < n else ""

                    # 既存の括弧破壊回避（A(B) / (A)B を壊さない）
                    if prev in ("(", "（"):
                        continue
                    if nextc in (")", "）", "(", "（"):
                        continue

                    matched = name
                    break

        if matched:
            # 前にスペース（必要なときだけ）
            if out:
                last = out[-1]
                if (not is_ws(last)) and (last not in ("(", "（")):
                    out.append(" ")

            out.append(matched)

            # 後ろにスペース（必要なときだけ）
            j = i + len(matched)
            if j < n:
                nxt = text[j]
                if (not is_ws(nxt)) and (nxt not in (")", "）", "(", "（")):
                    out.append(" ")

            i += len(matched)
        else:
            out.append(ch)
            i += 1

    return "".join(out)


def unify_aliases(text: str, name_to_display):
    tokens = text.split()
    unified = [name_to_display.get(tok, tok) for tok in tokens]
    return " ".join(unified)


def dedupe_space_separated_tokens(text: str):
    tokens = text.split()
    seen = set()
    out = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return " ".join(out)


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

    # ★ここは「切り詰めない」「止めない」：警告だけ
    if len(name) > MAX_FILENAME_LEN:
        log(f"[WARN] filename length over threshold: len={len(name)} > {MAX_FILENAME_LEN} (no truncation)")

    return name


def canonicalize_parenthesized_alias_tokens(text: str, name_to_display: dict) -> str:
    """
    A(B) / (A)B が入ってきても display へ揃える（片側が既知なら display）。
    """
    def repl_ab(m):
        a = normalize_variant_chars(m.group(1))
        b = normalize_variant_chars(m.group(2))
        if a in name_to_display:
            return name_to_display[a]
        if b in name_to_display:
            return name_to_display[b]
        return normalize_variant_chars(m.group(0))

    def repl_ba(m):
        a = normalize_variant_chars(m.group(1))
        b = normalize_variant_chars(m.group(2))
        if a in name_to_display:
            return name_to_display[a]
        if b in name_to_display:
            return name_to_display[b]
        return normalize_variant_chars(m.group(0))

    # A(B)
    text = re.sub(r'([^\s()]+)\(([^\s()]+)\)', repl_ab, text)
    # (A)B
    text = re.sub(r'\(([^\s()]+)\)([^\s()]+)', repl_ba, text)

    return text


def has_people_separators(text: str) -> bool:
    """
    registration_text が「セパレータで既に分割されている」か判定する。
    """
    s = (text or "").strip()
    if not s:
        return False

    if "】・【" in s:
        return True
    if "／" in s or "/" in s:
        return True
    if "・" in s or "、" in s or "," in s:
        return True

    if "\t" in s:
        return True
    if "\n" in s or "\r" in s:
        return True
    if " " in s:
        return True

    return False


def normalize_and_tokenize(raw: str, alias_names_sorted, name_to_display, *,
                           for_registration: bool = False):
    """
    1ブロック分のテキストを整形しトークン化。
    for_registration=True のときだけ “既知名の前後スペース挿入” を使う。
    """
    text = normalize_variant_chars(raw.strip())

    text = text.replace("（", "(").replace("）", ")")

    # ★括弧付き表記を先に正規displayへ寄せる
    text = canonicalize_parenthesized_alias_tokens(text, name_to_display)

    text = text.replace("／", " ")
    text = text.replace("】・【", " ")

    text = text.replace("\r\n", " ")
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")

    text = text.replace("/", " ")
    text = text.replace(":", "：")
    text = text.replace("    ", " ")
    text = text.replace(", ", " ")
    text = text.replace(".", "")
    text = text.replace("　", " ")

    if for_registration:
        text = insert_spaces_around_aliases_for_registration(text, alias_names_sorted, name_to_display)
    else:
        text = insert_spaces_for_aliases(text, alias_names_sorted)

    text = unify_aliases(text, name_to_display)

    text = text.replace("F**K", "FUCK")
    text = text.replace("*", "＊")

    text = text.replace(",", " ")

    text = text.strip()
    text = re.sub(r"[ ]+", " ", text)

    # ブロック内の冗長重複のみ整理
    text = dedupe_space_separated_tokens(text)

    tokens = text.split()
    tokens = [t for t in tokens if t != "#"]
    text = " ".join(tokens)

    return text, tokens


def detect_alias_pairs_in_raw(raw_text: str):
    raw_text = normalize_variant_chars(raw_text)

    pat1 = re.compile(
        r"([^\s()（）]+?)[ \t]*[\(\（][ \t]*([^\(\)（）]+?)[ \t]*[\)\）]"
    )
    pat2 = re.compile(
        r"[\(\（][ \t]*([^\(\)（）]+?)[ \t]*[\)\）][ \t]*([^\s()（）]+)"
    )

    pairs = []

    for m in pat1.finditer(raw_text):
        a = normalize_variant_chars(m.group(1).strip())
        b = normalize_variant_chars(m.group(2).strip())
        if a and b:
            pairs.append((a, b))

    for m in pat2.finditer(raw_text):
        a = normalize_variant_chars(m.group(1).strip())
        b = normalize_variant_chars(m.group(2).strip())
        if a and b:
            pairs.append((a, b))

    return pairs


def dedupe_line_full_repeat(raw_text: str) -> str:
    lines = raw_text.splitlines()
    out_lines = []

    for line in lines:
        s = line.strip()
        if not s:
            out_lines.append(line)
            continue

        if re.search(r"\s", s):
            out_lines.append(line)
            continue

        if any(ch in s for ch in "()（）／【】"):
            out_lines.append(line)
            continue

        n = len(s)
        if n % 2 == 0:
            half = s[: n // 2]
            if half * 2 == s:
                out_lines.append(half)
                continue

        out_lines.append(line)

    return "\n".join(out_lines)


# ===================== 新規登録トークン判定 =====================

def is_plausible_name_token(tok: str) -> bool:
    if not tok:
        return False

    if len(tok) >= 25:
        return False

    bad_chars = set('「」『』【】"“”…')
    if any(ch in tok for ch in bad_chars):
        return False

    if any(ch in tok for ch in "()（）"):
        return False

    return True


# ===================== 変換のメインロジック =====================

def convert_text(raw_text: str, aliases, first_line_raw: str, registration_text: str,
                 *, exclude_first_line_tokens_for_new_names: bool):
    alias_names_sorted, name_to_display, known_tokens = build_alias_helpers(aliases)

    people_is_already_separated = has_people_separators(registration_text)
    use_strong_split_for_people = (not people_is_already_separated)

    # ファイル名生成用トークン：1行目と2行目以降を別ブロックで正規化→連結
    tokens_first = []
    tokens_rest = []

    if first_line_raw:
        _, tokens_first = normalize_and_tokenize(
            first_line_raw, alias_names_sorted, name_to_display, for_registration=False
        )

    if registration_text:
        _, tokens_rest = normalize_and_tokenize(
            registration_text, alias_names_sorted, name_to_display, for_registration=use_strong_split_for_people
        )

    tokens_all = tokens_first + tokens_rest

    if not tokens_all:
        _, tokens_all = normalize_and_tokenize(
            raw_text, alias_names_sorted, name_to_display, for_registration=False
        )

    # 登録用は registration_text（連結のみ強め分割、分割済みは通常分割）
    _, tokens_reg = normalize_and_tokenize(
        registration_text, alias_names_sorted, name_to_display, for_registration=use_strong_split_for_people
    )

    # 1行目トークン（モードにより除外の有無を切替）
    first_line_tokens = set()
    if first_line_raw:
        _, first_tokens = normalize_and_tokenize(
            first_line_raw, alias_names_sorted, name_to_display, for_registration=False
        )
        first_line_tokens = set(first_tokens)

    # alias ペアも登録ソースに限定
    alias_pairs = detect_alias_pairs_in_raw(registration_text)
    alias_pair_names = set()
    for a, b in alias_pairs:
        alias_pair_names.add(a)
        alias_pair_names.add(b)

    # 新規名抽出
    new_names = []
    seen_new = set()
    for tok in tokens_reg:
        tok = normalize_variant_chars(tok)
        if not is_plausible_name_token(tok):
            continue
        if tok in known_tokens:
            continue
        if exclude_first_line_tokens_for_new_names and tok in first_line_tokens:
            continue
        if tok in alias_pair_names:
            continue
        if tok in seen_new:
            continue
        seen_new.add(tok)
        new_names.append(tok)

    base_line = " ".join(tokens_all)
    base_line = sanitize_for_windows_filename(base_line)

    if not base_line.lower().endswith(".mp4"):
        base_line = base_line + ".mp4"

    # .mp4 付与後の長さも警告だけ（切らない／止めない）
    if len(base_line) > MAX_FILENAME_LEN:
        log(f"[WARN] filename length over threshold after ext: len={len(base_line)} > {MAX_FILENAME_LEN} (no truncation)")

    final_text = base_line + "\n"
    return final_text, new_names, alias_pairs


# ===================== DB / CSV 更新 =====================

def append_new_names_to_csv(csv_path: Path, new_names):
    if not new_names:
        return

    unique = []
    seen = set()
    for n in new_names:
        n = normalize_variant_chars((n or "").strip())
        if not n:
            continue
        if n not in seen:
            seen.add(n)
            unique.append(n)

    if not unique:
        return

    if csv_path.exists():
        mode = "a"
        write_header = False
    else:
        mode = "w"
        write_header = True

    with csv_path.open(mode, encoding="utf-8-sig", newline="") as f:
        fieldnames = ["old", "new", "display"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for name in unique:
            writer.writerow({"old": name, "new": "", "display": ""})

    log(f"[INFO] {len(unique)} new names appended to CSV.")


def append_new_names_to_db(conn, new_names):
    """
    ACTRESS_ID は明示しない。
    テーブル側の DEFAULT(NEXT VALUE FOR dbo.ACTRESS_DATA_SEQ) を踏む。
    """
    if not new_names or conn is None:
        return

    unique = []
    seen = set()
    for n in new_names:
        n = normalize_variant_chars((n or "").strip())
        if not n:
            continue
        if n not in seen:
            seen.add(n)
            unique.append(n)

    if not unique:
        return

    try:
        cur = conn.cursor()
        for name in unique:
            cur.execute(
                "SELECT COUNT(*) FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ?", (name,),
            )
            if cur.fetchone()[0] == 0:
                cur.execute(
                    "INSERT INTO dbo.ACTRESS_DATA (OLD_NAME) VALUES (?)",
                    (name,),
                )
        conn.commit()
        log(f"[INFO] {len(unique)} new names inserted into DB.")
    except Exception as e:
        log(f"[ERROR] append_new_names_to_db failed: {e!r}")


def update_alias_pairs_in_csv(csv_path: Path, alias_pairs):
    if not alias_pairs:
        return

    unique_pairs = []
    seen_keys = set()
    for a, b in alias_pairs:
        a = normalize_variant_chars(a.strip())
        b = normalize_variant_chars(b.strip())
        if not a or not b:
            continue
        key = tuple(sorted((a, b)))
        if key not in seen_keys:
            seen_keys.add(key)
            unique_pairs.append((a, b))

    rows = []
    fieldnames = ["old", "new", "display"]

    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                fieldnames = reader.fieldnames
            for row in reader:
                rows.append(
                    {
                        "old": normalize_variant_chars((row.get("old") or "").strip()),
                        "new": normalize_variant_chars((row.get("new") or "").strip()),
                        "display": normalize_variant_chars((row.get("display") or "").strip()),
                    }
                )

    index_by_old = {}
    for i, row in enumerate(rows):
        old = row.get("old", "")
        if old and old not in index_by_old:
            index_by_old[old] = i

    def decide_old_new(a: str, b: str):
        in_a = a in index_by_old
        in_b = b in index_by_old

        if in_a and not in_b:
            return a, b
        if in_b and not in_a:
            return b, a

        if len(a) < len(b):
            return a, b
        if len(b) < len(a):
            return b, a

        return a, b

    for a, b in unique_pairs:
        old_name, new_name = decide_old_new(a, b)

        if old_name in index_by_old:
            row = rows[index_by_old[old_name]]
            current_new = row.get("new", "")
            if not current_new or current_new == new_name:
                row["new"] = new_name
            else:
                row["new"] = new_name
        else:
            rows.append({"old": old_name, "new": new_name, "display": ""})
            index_by_old[old_name] = len(rows) - 1

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "old": row.get("old", ""),
                    "new": row.get("new", ""),
                    "display": row.get("display", ""),
                }
            )

    log(f"[INFO] {len(unique_pairs)} alias pairs merged into CSV.")


def update_alias_pairs_in_db(conn, alias_pairs):
    if not alias_pairs or conn is None:
        return

    unique_pairs = []
    seen_keys = set()
    for a, b in alias_pairs:
        a = normalize_variant_chars(a.strip())
        b = normalize_variant_chars(b.strip())
        if not a or not b:
            continue
        key = tuple(sorted((a, b)))
        if key not in seen_keys:
            seen_keys.add(key)
            unique_pairs.append((a, b))

    try:
        cur = conn.cursor()

        def exists(name: str):
            cur.execute(
                "SELECT ACTRESS_ID, NEW_NAME FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ?",
                (name,),
            )
            return cur.fetchone()

        def decide_old_new(a: str, b: str):
            row_a = exists(a)
            row_b = exists(b)

            if row_a and not row_b:
                return a, b
            if row_b and not row_a:
                return b, a

            if not row_a and not row_b:
                if len(a) < len(b):
                    return a, b
                if len(b) < len(a):
                    return b, a
                return a, b

            return a, b

        for a, b in unique_pairs:
            old_name, new_name = decide_old_new(a, b)

            cur.execute(
                "SELECT ACTRESS_ID, NEW_NAME FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ?",
                (old_name,),
            )
            row = cur.fetchone()

            if row:
                actress_id, current_new = row
                current_new = normalize_variant_chars((current_new or "").strip())
                if not current_new or current_new == new_name:
                    cur.execute(
                        "UPDATE dbo.ACTRESS_DATA "
                        "SET NEW_NAME = ?, UPDATED_AT = SYSDATETIME() "
                        "WHERE ACTRESS_ID = ?",
                        (new_name, actress_id),
                    )
            else:
                cur.execute(
                    "INSERT INTO dbo.ACTRESS_DATA (OLD_NAME, NEW_NAME) VALUES (?, ?)",
                    (old_name, new_name),
                )

        conn.commit()
        log(f"[INFO] {len(unique_pairs)} alias pairs merged into DB.")
    except Exception as e:
        log(f"[ERROR] update_alias_pairs_in_db failed: {e!r}")


# ===================== テキスト読み込み共通処理 =====================

def load_text_with_fallback(path: Path):
    text = None
    encoding_used = None
    for enc in ("utf-8", "cp932"):
        try:
            with path.open("r", encoding=enc) as f:
                text = f.read()
            encoding_used = enc
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise UnicodeError(f"failed to decode {path} as utf-8 / cp932")

    return text, encoding_used


def get_text_excluding_first_line(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 1:
        return ""
    return "\n".join(lines[1:])


# ===================== main =====================

def main():
    aliases_csv = SCRIPT_DIR / "aliases.csv"
    conn = get_db_connection()

    is_arg_mode = len(sys.argv) >= 2

    # --- 入力ソースの判定 ---
    if is_arg_mode:
        input_path = Path(sys.argv[1])
        if not input_path.exists():
            msg = f"入力ファイルが見つかりません: {input_path}"
            print(msg)
            log(f"[ERROR] {msg}")
            sys.exit(1)

        try:
            text, encoding_used = load_text_with_fallback(input_path)
        except UnicodeError:
            msg = "input ファイルの文字コードを utf-8 / cp932 で読めませんでした。"
            print(msg)
            log(f"[ERROR] {msg}")
            sys.exit(1)

        log(f"[INFO] input loaded: {input_path} (encoding={encoding_used})")

        preprocessed = dedupe_line_full_repeat(text)

        lines = preprocessed.splitlines()
        first_line_raw = lines[0] if lines else ""

        registration_text = get_text_excluding_first_line(preprocessed)

        source_desc = f"{input_path} (encoding={encoding_used})"
        output_path = input_path.with_name(
            input_path.stem + "_converted" + input_path.suffix
        )

        exclude_first_line_tokens_for_new_names = True

    else:
        title_path = SCRIPT_DIR / "title.txt"
        actress_path = SCRIPT_DIR / "actress.txt"

        if not title_path.exists():
            msg = f"title.txt が見つかりません: {title_path}"
            print(msg)
            log(f"[ERROR] {msg}")
            sys.exit(1)
        if not actress_path.exists():
            msg = f"actress.txt が見つかりません: {actress_path}"
            print(msg)
            log(f"[ERROR] {msg}")
            sys.exit(1)

        try:
            title_text, enc_title = load_text_with_fallback(title_path)
        except UnicodeError:
            msg = "title.txt の文字コードを utf-8 / cp932 で読めませんでした。"
            print(msg)
            log(f"[ERROR] {msg}")
            sys.exit(1)

        try:
            actress_text, enc_act = load_text_with_fallback(actress_path)
        except UnicodeError:
            msg = "actress.txt の文字コードを utf-8 / cp932 で読めませんでした。"
            print(msg)
            log(f"[ERROR] {msg}")
            sys.exit(1)

        log(f"[INFO] title loaded:  {title_path} (encoding={enc_title})")
        log(f"[INFO] actress loaded: {actress_path} (encoding={enc_act})")

        title_lines = title_text.splitlines()
        title_line = title_lines[0].rstrip("\r\n") if title_lines else ""

        actress_block = actress_text

        combined = title_line + "\n" + actress_block

        preprocessed = dedupe_line_full_repeat(combined)

        lines = preprocessed.splitlines()
        first_line_raw = lines[0] if lines else ""

        registration_text = get_text_excluding_first_line(preprocessed)

        source_desc = f"title.txt({enc_title}) + actress.txt({enc_act})"
        output_path = SCRIPT_DIR / "conv_converted.txt"

        # actress.txt は明示リストなので、1行目トークン除外はしない
        exclude_first_line_tokens_for_new_names = False

    # --- エイリアス読み込み & 変換本体 ---
    aliases = load_aliases(aliases_csv, conn)

    converted, new_names, alias_pairs = convert_text(
        preprocessed,
        aliases,
        first_line_raw,
        registration_text,
        exclude_first_line_tokens_for_new_names=exclude_first_line_tokens_for_new_names
    )

    # 出力は SJIS 固定
    try:
        encoded = converted.encode("cp932", errors="ignore")
        decoded = encoded.decode("cp932")
        if decoded != converted:
            log("[WARN] cp932 encode(decode) caused character drop/replacement in output text.")
        with output_path.open("w", encoding="cp932") as f:
            f.write(decoded)
        log(f"[INFO] output written: {output_path}")
    except Exception as e:
        log(f"[ERROR] failed to write output: {e!r}")
        raise

    # DB / CSV 更新
    if conn is not None:
        update_alias_pairs_in_db(conn, alias_pairs)
        append_new_names_to_db(conn, new_names)
        try:
            conn.close()
        except Exception:
            pass
    else:
        update_alias_pairs_in_csv(aliases_csv, alias_pairs)
        append_new_names_to_csv(aliases_csv, new_names)

    print(f"変換完了: {output_path} （input: {source_desc}, output: cp932, CRLF, .mp4付き）")
    log(f"[INFO] people_is_already_separated={has_people_separators(registration_text)}")
    log(f"[INFO] registration_text_len={len(registration_text)}")
    log(f"[INFO] new_names={new_names}")
    log("=== av_text_convert end ===")


if __name__ == "__main__":
    main()