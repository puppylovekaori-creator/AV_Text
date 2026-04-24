# av_title_convert.py
# -*- coding: utf-8 -*-
"""
av_title_convert.py

タイトル単体変換（DB/CSV更新なし）
- %APPDATA%\sakura\avtext\title.txt の先頭1行を入力
- %APPDATA%\sakura\avtext\conv_converted.txt に cp932 で出力
- 多段エイリアス解決 / 異体字吸収は avtext_common.py の共通実装を使用
- 長さ超過は切り詰めず WARN のみ
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from avtext_common import (
    SimpleLogger,
    DbConfigLoader,
    DbConnector,
    AliasRepository,
    CharNormalizer,
    AliasResolver,
    TextNormalizer,
    FileTextIO,
)

MAX_FILENAME_LEN = 240


def get_base_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "sakura" / "avtext"
    # 念のためのフォールバック
    return Path.home() / "AppData" / "Roaming" / "sakura" / "avtext"


def detect_registered_names_in_title(
    title: str,
    candidate_names: Iterable[str],
    char_normalizer: CharNormalizer,
) -> list[str]:
    """
    タイトル文中に含まれる既登録名を長い順で検出（重複除去）。
    比較は normalize_for_match 後で行う。
    """
    found: list[str] = []
    seen_raw: set[str] = set()

    title_key = char_normalizer.normalize_for_match(title)

    for name in candidate_names:
        if not name:
            continue
        if name in seen_raw:
            continue
        name_key = char_normalizer.normalize_for_match(name)
        if not name_key:
            continue
        if name_key in title_key:
            seen_raw.add(name)
            found.append(name)

    return found


def resolve_tail_display(
    token: str,
    resolver: AliasResolver,
    char_normalizer: CharNormalizer,
) -> str | None:
    """
    末尾トークンが既知名 or display なら canonical display を返す。
    """
    if not token:
        return None

    # まず resolver で解決（old/new 等）
    disp = resolver.resolve_display(token)
    if disp:
        return disp

    # display 文字列そのものだった場合
    token_key = char_normalizer.normalize_for_match(token)
    name_to_display = resolver.get_name_to_display_map()
    for v in set(name_to_display.values()):
        if char_normalizer.normalize_for_match(v) == token_key:
            return v

    return None


def convert_title_only(
    title_line: str,
    resolver: AliasResolver,
    text_normalizer: TextNormalizer,
    char_normalizer: CharNormalizer,
    logger: SimpleLogger,
) -> tuple[str, list[str], list[str], list[str]]:
    """
    戻り値:
      (converted_text_with_newline, matched_names, tail_displays, extra_displays)
    """
    alias_names_sorted = resolver.get_alias_names_sorted()
    name_to_display = resolver.get_name_to_display_map()

    # 基本正規化（F**K -> FUCK, * -> ＊, 改行/空白整理 など）
    normalized_title = text_normalizer.normalize_title_text(title_line)

    # A(B) / (A)B を display へ寄せる（片側が既知なら）
    normalized_title = text_normalizer.canonicalize_parenthesized_alias_tokens(
        normalized_title,
        resolver,
    )

    tokens = normalized_title.split()

    tail_displays: list[str] = []
    tail_display_keys: set[str] = set()

    # 末尾連続トークンを display に置換
    i = len(tokens) - 1
    while i >= 0:
        disp = resolve_tail_display(tokens[i], resolver, char_normalizer)
        if not disp:
            break

        tokens[i] = disp
        disp_key = char_normalizer.normalize_for_match(disp)
        if disp_key not in tail_display_keys:
            tail_display_keys.add(disp_key)
            tail_displays.append(disp)

        i -= 1

    # 文中に含まれる登録名を検出（長い順）
    matched_names = detect_registered_names_in_title(
        normalized_title,
        alias_names_sorted,
        char_normalizer,
    )

    # display へ寄せて重複除去
    matched_displays: list[str] = []
    seen_disp_keys: set[str] = set()

    for n in matched_names:
        disp = resolver.resolve_display(n) or n
        disp_key = char_normalizer.normalize_for_match(disp)
        if disp_key and disp_key not in seen_disp_keys:
            seen_disp_keys.add(disp_key)
            matched_displays.append(disp)

    # 末尾に既にいるものは追加しない
    extra_displays: list[str] = []
    extra_keys: set[str] = set()

    for disp in matched_displays:
        disp_key = char_normalizer.normalize_for_match(disp)
        if disp_key in tail_display_keys:
            continue
        if disp_key in extra_keys:
            continue
        extra_keys.add(disp_key)
        extra_displays.append(disp)

    base = " ".join(tokens).strip()
    if extra_displays:
        base = (base + " " + " ".join(extra_displays)).strip()

    base = text_normalizer.sanitize_for_windows_filename(
        base,
        max_len=MAX_FILENAME_LEN,
        truncate=False,
        warn_only=True,
        logger=logger,
    )

    base = re.sub(r"[ ]+", " ", base).strip()

    if not base.lower().endswith(".mp4"):
        base += ".mp4"

    if len(base) > MAX_FILENAME_LEN:
        logger.log(
            f"[WARN] filename length over threshold after ext: "
            f"len={len(base)} > {MAX_FILENAME_LEN} (no truncation)"
        )

    return base + "\n", matched_names, tail_displays, extra_displays


def main() -> None:
    base_dir = get_base_dir()

    title_path = base_dir / "title.txt"
    output_path = base_dir / "conv_converted.txt"
    aliases_csv = base_dir / "aliases.csv"
    setting_ini = base_dir / "setting.ini"
    log_path = base_dir / "av_title_convert.log"

    logger = SimpleLogger(log_path)
    logger.log("=== av_title_convert start ===")
    logger.log(f"[INFO] BASE_DIR={base_dir}")
    logger.log(f"[INFO] TITLE_PATH={title_path}")
    logger.log(f"[INFO] OUTPUT_PATH={output_path}")

    file_io = FileTextIO()
    char_normalizer = CharNormalizer()
    text_normalizer = TextNormalizer()

    # DB接続（失敗時はCSVフォールバック）
    conn = None
    try:
        cfg = DbConfigLoader.load_from_ini(setting_ini)
        if cfg:
            connector = DbConnector(logger)
            conn = connector.connect(cfg)
        else:
            logger.log("[INFO] DB config unavailable. Use CSV aliases.")
    except Exception as e:
        logger.log(f"[WARN] DB setup failed, fallback to CSV: {e!r}")
        conn = None

    # エイリアス読み込み（DB優先）
    try:
        aliases = AliasRepository.load(conn, aliases_csv)
    except Exception as e:
        logger.log(f"[ERROR] alias load failed: {e!r}")
        aliases = []

    # resolver構築
    resolver = AliasResolver(aliases, logger, char_normalizer)
    resolver.build()

    # 入力読込
    if not title_path.exists():
        msg = f"title.txt が見つかりません: {title_path}"
        print(msg)
        logger.log(f"[ERROR] {msg}")
        logger.log("=== av_title_convert end ===")
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return

    try:
        title_line, enc = file_io.load_first_line_with_fallback(title_path)
        logger.log(f"[INFO] title loaded: {title_path} (encoding={enc})")
    except UnicodeError:
        msg = "title.txt の文字コードを utf-8 / cp932 で読めませんでした。"
        print(msg)
        logger.log(f"[ERROR] {msg}")
        logger.log("=== av_title_convert end ===")
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return
    except Exception as e:
        msg = f"title.txt 読み込み失敗: {e!r}"
        print(msg)
        logger.log(f"[ERROR] {msg}")
        logger.log("=== av_title_convert end ===")
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        return

    # 変換
    converted, matched_names, tail_displays, extra_displays = convert_title_only(
        title_line=title_line,
        resolver=resolver,
        text_normalizer=text_normalizer,
        char_normalizer=char_normalizer,
        logger=logger,
    )

    # 出力（cp932固定）
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        file_io.write_cp932(output_path, converted)
        logger.log(f"[INFO] output written: {output_path}")
    except Exception as e:
        logger.log(f"[ERROR] failed to write output: {e!r}")
        raise

    # クローズ
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass

    logger.log(f"[INFO] matched_names={matched_names}")
    logger.log(f"[INFO] tail_displays={tail_displays}")
    logger.log(f"[INFO] extra_displays={extra_displays}")

    print(
        f"変換完了: {output_path} "
        f"（input: {title_path} encoding={enc}, output: cp932, CRLF, .mp4付き）"
    )
    logger.log("=== av_title_convert end ===")


if __name__ == "__main__":
    main()