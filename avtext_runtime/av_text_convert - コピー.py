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

★仕様
  - 出力ファイルは常に SJIS(cp932)
  - 出力は 1 行のみで、行末に '\\n' を付ける
    → Windows のテキスト書き込みで CRLF に変換される
"""

import sys
import csv
import re
import configparser
from pathlib import Path
from datetime import datetime

# ===================== 共通設定 =====================

MAX_FILENAME_LEN = 240  # 一応 255 文字制限に余裕を持たせる

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "av_text_convert.log"


def log(msg: str) -> None:
    """タイムスタンプ付きでログ出力（失敗しても黙って無視）。"""
    try:
        # 例: 2025-11-30 21:34:12.345
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        # ログすら書けなくても処理は続ける
        pass

# まずログを開いておく（ここまで来れば必ずログファイルは作られる）
log("=== av_text_convert start ===")

# pyodbc の読み込み（失敗しても CSV でフォールバック）
try:
    import pyodbc  # type: ignore
except Exception as e:  # ImportError だけでなく一応全部
    pyodbc = None  # type: ignore
    log(f"[WARN] pyodbc import failed: {e!r}")


# ===================== DB アクセス =====================

def load_db_config():
    """
    SCRIPT_DIR/setting.ini から接続情報を読む。
    書式（例）:
      [DB Setting]
      IP = '192.168.0.22'
      User = 'sa'
      Password = 'xxxx'
      Database = 'FileDB'
    """
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
    """pyodbc + setting.ini から接続を試みる。失敗したら None。"""
    if pyodbc is None:
        log("[INFO] pyodbc not available. Use CSV aliases.")
        return None

    cfg = load_db_config()
    if cfg is None:
        return None

    # ドライバ候補
    driver_candidates = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
    ]
    # 環境に入っている SQL Server 系ドライバも一応候補に追加
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
    """aliases.csv からエイリアス定義を読み込む。形式: old,new,display"""
    aliases = []

    if not csv_path.exists():
        log(f"[INFO] aliases.csv not found: {csv_path}")
        return aliases

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old = (row.get("old") or "").strip()
            new = (row.get("new") or "").strip()
            disp = (row.get("display") or "").strip()

            if not old and not new and not disp:
                continue

            names = set()
            if old:
                names.add(old)
            if new:
                names.add(new)

            if not disp:
                if new and old:
                    disp = f"{old}({new})"
                elif new:
                    disp = new
                elif old:
                    disp = old

            aliases.append((names, disp))

    log(f"[INFO] {len(aliases)} aliases loaded from CSV.")
    return aliases


def load_aliases_from_db(conn):
    """
    ACTRESS_DATA からエイリアス定義を読み込む。
    OLD_NAME / NEW_NAME / DISPLAY_NAME を使って CSV と同じ構造を作る。
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
            old = (old or "").strip()
            new = (new or "").strip()
            disp = (disp or "").strip()

            if not old and not new and not disp:
                continue

            names = set()
            if old:
                names.add(old)
            if new:
                names.add(new)

            if not disp:
                if new and old:
                    disp = f"{old}({new})"
                elif new:
                    disp = new
                elif old:
                    disp = old

            aliases.append((names, disp))

        log(f"[INFO] {len(aliases)} aliases loaded from DB.")
    except Exception as e:
        log(f"[ERROR] load_aliases_from_db failed: {e!r}")
    return aliases


def load_aliases(aliases_csv: Path, conn):
    """DB が使えれば DB、ダメなら CSV。"""
    if conn is not None:
        aliases = load_aliases_from_db(conn)
        if aliases:
            return aliases
        log("[WARN] DB returned no aliases. Fallback to CSV.")
    return load_aliases_from_csv(aliases_csv)


def build_alias_helpers(aliases):
    """
    - alias_names_sorted: スペース挿入に使う「名前一覧」（長さ順ソート）
    - name_to_display : トークン → display のマップ
    - known_tokens    : old/new と display の全部
    """
    alias_names_set = set()
    name_to_display = {}
    display_set = set()

    for names, disp in aliases:
        display_set.add(disp)
        for name in names:
            if not name:
                continue
            alias_names_set.add(name)
            if name not in name_to_display:
                name_to_display[name] = disp

    alias_names_sorted = sorted(alias_names_set, key=len, reverse=True)
    known_tokens = alias_names_set | display_set
    return alias_names_sorted, name_to_display, known_tokens


# ===================== 前処理系 =====================

def insert_spaces_for_aliases(text: str, alias_names_sorted):
    """
    DB 登録名の直後にスペースを挿入して、連結された名前列を切り分ける。
    ただし、カッコ隣接（みひな(永井みひな), (みひな)永井みひな 等）は対象外。
    """
    for name in alias_names_sorted:
        if not name:
            continue
        pattern = re.compile(
            rf'(?<![\(\（]){re.escape(name)}(?![\)\）\(\（])'
        )
        text = pattern.sub(name + " ", text)
    return text


def unify_aliases(text: str, name_to_display):
    """old/new を display に統一。"""
    tokens = text.split()
    unified = [name_to_display.get(tok, tok) for tok in tokens]
    return " ".join(unified)


def dedupe_space_separated_tokens(text: str):
    """スペース区切りのトークン重複を削除。"""
    tokens = text.split()
    seen = set()
    out = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return " ".join(out)


def sanitize_for_windows_filename(name: str) -> str:
    """
    Windows のファイル名に使えない文字を全角記号に変換し、
    制御文字と末尾の空白・ピリオドを削り、
    最後に MAX_FILENAME_LEN で丸める。
    """
    trans = str.maketrans({
        '\\': '＼',
        '/': '／',
        ':': '：',
        '*': '＊',
        '?': '？',
        '"': '”',
        '<': '＜',
        '>': '＞',
        '|': '｜',
    })
    name = name.translate(trans)
    # 制御文字を削除（LF 単体問題もここで潰す）
    name = re.sub(r'[\x00-\x1F]', '', name)
    # 末尾のスペース・ピリオドは禁止なので削る
    name = name.rstrip(" .")
    # 長すぎる場合は前側だけ残して丸める
    if len(name) > MAX_FILENAME_LEN:
        name = name[:MAX_FILENAME_LEN]
    return name


def normalize_and_tokenize(raw: str, alias_names_sorted, name_to_display):
    """
    1ブロック分のテキストに対して、整形～別名統一～重複削除までを実施。
    戻り値: (整形後テキスト, トークンリスト)
    """
    text = raw.strip()

    # 全角カッコ → 半角カッコ
    text = text.replace("（", "(").replace("）", ")")

    # 記号系をまずスペース扱いに
    text = text.replace("／", " ")
    text = text.replace("】・【", " ")

    # 改行もスペースに寄せる
    text = text.replace("\r\n", " ")
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")

    # その他の正規化
    text = text.replace("/", " ")
    text = text.replace(":", "：")
    text = text.replace("    ", " ")
    text = text.replace(", ", " ")
    text = text.replace(".", "")
    text = text.replace("　", " ")

    # DB / CSV にある名前で分割
    text = insert_spaces_for_aliases(text, alias_names_sorted)

    # 別名 → display に統一
    text = unify_aliases(text, name_to_display)

    # 特例: F**K → FUCK（このときだけ * を消す）
    text = text.replace("F**K", "FUCK")
    # それ以外の半角 * はすべて全角 ＊ にする
    text = text.replace("*", "＊")

    # カンマは区切りとみなす
    text = text.replace(",", " ")

    # 余計なスペース整理
    text = text.strip()
    text = re.sub(r"[ ]+", " ", text)

    # 同じトークンの重複削除
    text = dedupe_space_separated_tokens(text)

    tokens = text.split()
    # '#' 単体トークンは削除
    tokens = [t for t in tokens if t != "#"]
    text = " ".join(tokens)

    return text, tokens


def detect_alias_pairs_in_raw(raw_text: str):
    """
    生テキストから「名前(名前)」「(名前)名前」パターンを検出して (name1, name2) の組で返す。
    半角 / 全角カッコどちらも対象。
    """
    pat1 = re.compile(
        r"([^\s()（）]+?)[ \t]*[\(\（][ \t]*([^\(\)（）]+?)[ \t]*[\)\）]"
    )
    pat2 = re.compile(
        r"[\(\（][ \t]*([^\(\)（）]+?)[ \t]*[\)\）][ \t]*([^\s()（）]+)"
    )

    pairs = []

    # 例: みひな(永井みひな)
    for m in pat1.finditer(raw_text):
        a = m.group(1).strip()
        b = m.group(2).strip()
        if a and b:
            pairs.append((a, b))

    # 例: (みひな)永井みひな
    for m in pat2.finditer(raw_text):
        a = m.group(1).strip()
        b = m.group(2).strip()
        if a and b:
            pairs.append((a, b))

    return pairs


def dedupe_line_full_repeat(raw_text: str) -> str:
    """
    山田まりあ山田まりあ → 山田まりあ
    みたいな「行全体が同じ文字列2回」を圧縮。
    空白やカッコを含む行はスルー。
    """
    lines = raw_text.splitlines()
    out_lines = []

    for line in lines:
        s = line.strip()
        if not s:
            out_lines.append(line)
            continue

        # 空白を含む行は対象外
        if re.search(r"\s", s):
            out_lines.append(line)
            continue

        # カッコや記号を含む行も対象外
        if any(ch in s for ch in "()（）／【】"):
            out_lines.append(line)
            continue

        # 完全に同じ文字列が 2 回続く場合だけ圧縮
        n = len(s)
        if n % 2 == 0:
            half = s[: n // 2]
            if half * 2 == s:
                out_lines.append(half)
                continue

        out_lines.append(line)

    return "\n".join(out_lines)


# ===================== 変換のメインロジック =====================

def convert_text(raw_text: str, aliases, first_line_raw: str):
    """
    全体を整形して 1 行テキストを返す。
    返り値:
      final_text（末尾に '\\n' 付き → 実体は CRLF）
      new_names  （新規検出名）
      alias_pairs（パターンから見つけた別名ペア）
    """
    alias_names_sorted, name_to_display, known_tokens = build_alias_helpers(aliases)

    _, tokens = normalize_and_tokenize(
        raw_text, alias_names_sorted, name_to_display
    )

    # 1行目は DB / CSV 登録対象外（タイトル想定）
    first_line_tokens = set()
    if first_line_raw:
        _, first_tokens = normalize_and_tokenize(
            first_line_raw, alias_names_sorted, name_to_display
        )
        first_line_tokens = set(first_tokens)

    # () パターンから別名ペア抽出
    alias_pairs = detect_alias_pairs_in_raw(raw_text)
    alias_pair_names = set()
    for a, b in alias_pairs:
        alias_pair_names.add(a)
        alias_pair_names.add(b)

    # 新規名を洗い出し
    new_names = []
    seen_new = set()
    for tok in tokens:
        if any(ch in tok for ch in "()（）"):
            continue
        if tok in known_tokens:
            continue
        if tok in first_line_tokens:
            continue
        if tok in alias_pair_names:
            continue
        if tok in seen_new:
            continue
        seen_new.add(tok)
        new_names.append(tok)

    # ベース名を組み立て → Windows 用にサニタイズ（長さ丸め込み込み）
    base_line = " ".join(tokens)
    base_line = sanitize_for_windows_filename(base_line)

    # 拡張子 .mp4 を付与（既についていなければ）
    lower = base_line.lower()
    if not lower.endswith(".mp4"):
        base_line = base_line + ".mp4"

    # 行末に '\n' を付ける（Windows では CRLF になる）
    final_text = base_line + "\n"

    return final_text, new_names, alias_pairs


# ===================== DB / CSV 更新 =====================

def append_new_names_to_csv(csv_path: Path, new_names):
    """新規検出名を aliases.csv に追記（old だけの行）。"""
    if not new_names:
        return

    unique = []
    seen = set()
    for n in new_names:
        if n not in seen:
            seen.add(n)
            unique.append(n)

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
    """新規検出名を ACTRESS_DATA に INSERT（OLD_NAME のみ）。"""
    if not new_names or conn is None:
        return

    unique = []
    seen = set()
    for n in new_names:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    try:
        cur = conn.cursor()
        for name in unique:
            cur.execute(
                "SELECT COUNT(*) FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ?", (name,)
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
    """
    () から検出した別名ペアで aliases.csv を更新。
    ・old が既存ならその行の new を埋める
    ・どちらもなければ、短い方を old として new を追加
    """
    if not alias_pairs:
        return

    unique_pairs = []
    seen_keys = set()
    for a, b in alias_pairs:
        a = a.strip()
        b = b.strip()
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
                        "old": (row.get("old") or "").strip(),
                        "new": (row.get("new") or "").strip(),
                        "display": (row.get("display") or "").strip(),
                    }
                )

    # old → 行インデックス
    index_by_old = {}
    for i, row in enumerate(rows):
        old = row.get("old", "")
        if old and old not in index_by_old:
            index_by_old[old] = i

    def decide_old_new(a: str, b: str):
        """どちらを old/new にするか決める。"""
        in_a = a in index_by_old
        in_b = b in index_by_old

        if in_a and not in_b:
            return a, b
        if in_b and not in_a:
            return b, a

        # CSV に無い場合は短い方を old にする
        if len(a) < len(b):
            return a, b
        if len(b) < len(a):
            return b, a

        # 長さ同じならそのまま
        return a, b

    for a, b in unique_pairs:
        old_name, new_name = decide_old_new(a, b)

        if old_name in index_by_old:
            row = rows[index_by_old[old_name]]
            current_new = row.get("new", "")
            if not current_new or current_new == new_name:
                row["new"] = new_name
            else:
                # 衝突したらとりあえず新しい方で上書き
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
    """
    () から検出した別名ペアで ACTRESS_DATA を更新。
    ・old が既存ならその行の NEW_NAME を埋める
    ・どちらもなければ、短い方を OLD_NAME として NEW_NAME を追加
    """
    if not alias_pairs or conn is None:
        return

    unique_pairs = []
    seen_keys = set()
    for a, b in alias_pairs:
        a = a.strip()
        b = b.strip()
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
            row = cur.fetchone()
            return row

        def decide_old_new(a: str, b: str):
            """どちらを old/new にするか決める。"""
            row_a = exists(a)
            row_b = exists(b)

            if row_a and not row_b:
                return a, b
            if row_b and not row_a:
                return b, a

            if not row_a and not row_b:
                # DB に無い場合は短い方を old にする
                if len(a) < len(b):
                    return a, b
                if len(b) < len(a):
                    return b, a
                return a, b  # 同じ長さ

            # 両方存在する場合は a を優先
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
                current_new = (current_new or "").strip()
                if not current_new or current_new == new_name:
                    cur.execute(
                        "UPDATE dbo.ACTRESS_DATA SET NEW_NAME = ? WHERE ACTRESS_ID = ?",
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


# ===================== main =====================

def main():
    if len(sys.argv) < 2:
        print("使い方: python av_text_convert.py input.txt")
        log("[ERROR] no input file argument.")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        msg = f"入力ファイルが見つかりません: {input_path}"
        print(msg)
        log(f"[ERROR] {msg}")
        sys.exit(1)

    aliases_csv = SCRIPT_DIR / "aliases.csv"

    # DB 接続（失敗したら None で CSV フォールバック）
    conn = get_db_connection()

    # 入力文字コードは utf-8 → cp932 の順で試す
    text = None
    encoding_used = None
    for enc in ("utf-8", "cp932"):
        try:
            with input_path.open("r", encoding=enc) as f:
                text = f.read()
            encoding_used = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        msg = "input ファイルの文字コードを utf-8 / cp932 で読めませんでした。"
        print(msg)
        log(f"[ERROR] {msg}")
        sys.exit(1)

    log(f"[INFO] input loaded: {input_path} (encoding={encoding_used})")

    # 行全体が 2 回重複しているものを圧縮
    preprocessed = dedupe_line_full_repeat(text)

    # 1 行目（タイトル）は DB / CSV 登録対象外
    lines = preprocessed.splitlines()
    if lines:
        first_line_raw = lines[0]
    else:
        first_line_raw = ""

    aliases = load_aliases(aliases_csv, conn)

    converted, new_names, alias_pairs = convert_text(
        preprocessed, aliases, first_line_raw
    )

    output_path = input_path.with_name(
        input_path.stem + "_converted" + input_path.suffix
    )

    # 出力は SJIS 固定。SJIS に無い文字は消して書く。
    try:
        with output_path.open("w", encoding="cp932") as f:
            f.write(converted.encode("cp932", errors="ignore").decode("cp932"))
        log(f"[INFO] output written: {output_path}")
    except Exception as e:
        log(f"[ERROR] failed to write output: {e!r}")
        raise

    # DB / CSV 更新（()パターン → new、未知の名前 → old 追加）
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

    print(f"変換完了: {output_path} （input: {encoding_used}, output: cp932, CRLF, .mp4付き）")
    log("=== av_text_convert end ===")


if __name__ == "__main__":
    main()
