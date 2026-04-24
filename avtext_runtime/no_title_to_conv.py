# -*- coding: utf-8 -*-
"""
no_title_to_conv.py

仕様（シンプル版 + ファイル名サニタイズ追加）
- 同じフォルダにある no.txt と title.txt を読む
- no.txt は必ず1行で「1234」のような連番文字列
  例: 1234 -> 4本分として扱う
- title.txt は既存運用のものをそのまま流用（先頭1行をタイトルとして使用）
- conv_converted.txt に以下形式で出力
    <title> 01.mp4
    <title> 02.mp4
    ...
- 出力文字コードは cp932（SJIS互換）
- 改行は CRLF（OSに依存させず固定）
- タイトルはファイル名にできない文字を全角等へ置換し、制御文字除去などの最低限サニタイズを行う
"""

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
NO_PATH = SCRIPT_DIR / "no.txt"
TITLE_PATH = SCRIPT_DIR / "title.txt"
OUT_PATH = SCRIPT_DIR / "conv_converted.txt"

# Windowsファイル名として安全側に寄せるための上限（拡張子込みで240文字目安）
MAX_FILENAME_LEN = 240


def read_first_line(path: Path) -> str:
    # utf-8 / cp932 の順で読む
    last_err = None
    for enc in ("utf-8", "cp932"):
        try:
            with path.open("r", encoding=enc) as f:
                lines = f.read().splitlines()
            return lines[0].strip() if lines else ""
        except Exception as e:
            last_err = e
    raise RuntimeError(f"failed to read {path}: {last_err!r}")


def normalize_title_text(raw: str) -> str:
    """
    タイトルの軽い正規化（既存スクリプトの流儀を踏襲）
    - 改行類はスペースへ
    - 全角スペースを半角へ
    - "*" は全角へ（ファイル名NG対策）
    - 連続スペースを1つへ
    """
    text = raw.strip()
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = text.replace("　", " ")

    # 既存運用の癖に寄せる（必要最低限）
    text = text.replace("F**K", "FUCK")
    text = text.replace("*", "＊")

    text = re.sub(r"[ ]+", " ", text).strip()
    return text


def sanitize_for_windows_filename(name: str) -> str:
    """
    Windowsのファイル名に使えない文字を置換し、危険な制御文字等を除去。
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
    # 制御文字（0x00-0x1F）を除去
    name = re.sub(r'[\x00-\x1F]', '', name)
    # 末尾のスペース・ドットはWindowsで厄介なので削る
    name = name.rstrip(" .")
    return name


def build_safe_filename(base_title: str, idx: int) -> str:
    """
    「<title> 01.mp4」を作り、長さ制限も加味して安全にする。
    """
    suffix = f" {idx:02d}.mp4"

    base = normalize_title_text(base_title)
    base = sanitize_for_windows_filename(base)

    # 空になったら保険（ファイル名として成立させる）
    if not base:
        base = "no_title"

    # 全体でMAX_FILENAME_LEN以内に収める（拡張子が欠けないようにbase側を詰める）
    allow = MAX_FILENAME_LEN - len(suffix)
    if allow < 1:
        # ここまで厳しい状況は通常起きないが、最低限 suffix は維持
        base = "no_title"
        allow = max(1, MAX_FILENAME_LEN - len(suffix))

    if len(base) > allow:
        base = base[:allow].rstrip(" .")

    return base + suffix


def main() -> int:
    if not NO_PATH.exists():
        print(f"no.txt が見つかりません: {NO_PATH}")
        return 1
    if not TITLE_PATH.exists():
        print(f"title.txt が見つかりません: {TITLE_PATH}")
        return 1

    no_line = read_first_line(NO_PATH)
    title_line = read_first_line(TITLE_PATH)

    if not no_line:
        print("no.txt が空です。")
        return 1
    if not title_line:
        print("title.txt が空です。")
        return 1

    # no.txt の形式チェック
    if not re.fullmatch(r"\d+", no_line):
        print("no.txt は数字のみの1行でお願いします。例: 1234")
        return 1

    # 「1234のような連番」を想定して、可能なら厳密チェック
    expected = "".join(str(i) for i in range(1, len(no_line) + 1))
    if no_line != expected:
        print(
            f"[WARN] no.txt が典型的な連番（{expected}）ではありません。"
            f" 文字数={len(no_line)} 本として処理します。"
        )

    count = len(no_line)

    lines = []
    for i in range(1, count + 1):
        lines.append(build_safe_filename(title_line, i))

    # 文字列は '\n' で組み立て、open(newline='\r\n') で CRLF を固定
    text = "\n".join(lines) + "\n"

    with OUT_PATH.open("w", encoding="cp932", errors="ignore", newline="\r\n") as f:
        f.write(text)

    print(f"出力完了: {OUT_PATH} （{count} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
