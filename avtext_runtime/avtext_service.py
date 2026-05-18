# -*- coding: utf-8 -*-
"""
avtext_service.py

AV Text 変換処理の共通サービス層。

目的:
- 既存 one-shot スクリプトと常駐 daemon の両方から同じ処理を使う
- DB 接続 / alias / normalize rules をキャッシュし、高速化する
- 失敗時は one-shot へ安全に戻せる構造にする
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from avtext_common import (
    SimpleLogger,
    DbConfigLoader,
    DbConnector,
    AliasRepository,
    FilenameNormalizeRepository,
    FilenameNormalizeProcessor,
    CharNormalizer,
    AliasResolver,
    AliasTextProcessor,
    TextNormalizer,
    FileTextIO,
    normalize_output_text,
    filter_ignored_actress_lines,
    get_text_excluding_first_line,
    dedupe_line_full_repeat,
    has_people_separators,
    safe_close,
)


MODE_TITLE_AND_ACTRESS = "title_and_actress"
MODE_TITLE_ONLY = "title_only"
MODE_NO_TITLE = "no_title"
VALID_MODES = {MODE_TITLE_AND_ACTRESS, MODE_TITLE_ONLY, MODE_NO_TITLE}

MAX_FILENAME_LEN = 240


@dataclass
class CommandResult:
    code: int
    message: str
    output_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code == 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "output_path": self.output_path,
            "meta": dict(self.meta or {}),
        }


@dataclass(frozen=True)
class TableSignature:
    row_count: int
    max_updated_at: str
    max_identity: int


@dataclass
class DbUpdateStats:
    alias_updated: int = 0
    alias_inserted: int = 0
    new_names_inserted: int = 0

    @property
    def changed(self) -> bool:
        return (self.alias_updated + self.alias_inserted + self.new_names_inserted) > 0


def get_base_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "sakura" / "avtext"
    return Path(__file__).resolve().parent


def get_log_path(base_dir: Path, mode: str) -> Path:
    if mode == MODE_TITLE_AND_ACTRESS:
        return base_dir / "av_text_convert.log"
    if mode == MODE_TITLE_ONLY:
        return base_dir / "av_title_convert.log"
    if mode == MODE_NO_TITLE:
        return base_dir / "no_title_to_conv.log"
    return base_dir / "avtext_service.log"


def build_logger(base_dir: Path, mode: str) -> SimpleLogger:
    return SimpleLogger(get_log_path(base_dir, mode))


def dedupe_space_separated_tokens(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def detect_alias_pairs_in_raw(raw_text: str, char_normalizer: CharNormalizer) -> list[tuple[str, str]]:
    raw_text = normalize_output_text(char_normalizer, raw_text)

    pat1 = re.compile(r"([^\s()（）]+?)[ \t]*[\(（][ \t]*([^\(\)（）]+?)[ \t]*[\)）]")
    pat2 = re.compile(r"[\(（][ \t]*([^\(\)（）]+?)[ \t]*[\)）][ \t]*([^\s()（）]+)")

    pairs: list[tuple[str, str]] = []

    for m in pat1.finditer(raw_text):
        a = normalize_output_text(char_normalizer, m.group(1).strip())
        b = normalize_output_text(char_normalizer, m.group(2).strip())
        if a and b:
            pairs.append((a, b))

    for m in pat2.finditer(raw_text):
        a = normalize_output_text(char_normalizer, m.group(1).strip())
        b = normalize_output_text(char_normalizer, m.group(2).strip())
        if a and b:
            pairs.append((a, b))

    return pairs


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


def _normalize_unique_names(
    names: list[str],
    char_normalizer: CharNormalizer,
) -> list[str]:
    unique: list[str] = []
    seen_keys: set[str] = set()

    for name in names:
        normalized = normalize_output_text(char_normalizer, (name or "").strip())
        if not normalized:
            continue

        key = char_normalizer.normalize_for_match(normalized)
        if not key or key in seen_keys:
            continue

        seen_keys.add(key)
        unique.append(normalized)

    return unique


def _normalize_unique_alias_pairs(
    alias_pairs: list[tuple[str, str]],
    char_normalizer: CharNormalizer,
) -> list[tuple[str, str]]:
    unique_pairs: list[tuple[str, str]] = []
    seen_pair_keys: set[tuple[str, str]] = set()

    for a, b in alias_pairs:
        a_out = normalize_output_text(char_normalizer, (a or "").strip())
        b_out = normalize_output_text(char_normalizer, (b or "").strip())
        if not a_out or not b_out:
            continue

        a_key = char_normalizer.normalize_for_match(a_out)
        b_key = char_normalizer.normalize_for_match(b_out)
        if not a_key or not b_key:
            continue

        pair_key = tuple(sorted((a_key, b_key)))
        if pair_key in seen_pair_keys:
            continue

        seen_pair_keys.add(pair_key)
        unique_pairs.append((a_out, b_out))

    return unique_pairs


def build_safe_filename(
    base_title: str,
    idx: int,
    text_normalizer: TextNormalizer,
    filename_normalizer: FilenameNormalizeProcessor | None = None,
) -> tuple[str, list]:
    suffix = f" {idx:02d}.mp4"

    base = text_normalizer.normalize_title_text(base_title)
    pending_items = []
    if filename_normalizer is not None:
        base, pending_items = filename_normalizer.normalize_text(base, "title_only")
    base = text_normalizer.sanitize_for_windows_filename(
        base,
        max_len=0,
        truncate=False,
        warn_only=False,
    )

    if not base:
        base = "no_title"

    allow = MAX_FILENAME_LEN - len(suffix)
    if allow < 1:
        base = "no_title"
        allow = max(1, MAX_FILENAME_LEN - len(suffix))

    if len(base) > allow:
        base = base[:allow].rstrip(" .")

    return base + suffix, pending_items


def convert_text(
    first_line_raw: str,
    registration_text: str,
    *,
    processor: AliasTextProcessor,
    filename_normalizer: FilenameNormalizeProcessor | None,
    char_normalizer: CharNormalizer,
    text_normalizer: TextNormalizer,
    logger: SimpleLogger,
    exclude_first_line_tokens_for_new_names: bool,
) -> tuple[str, list[str], list[tuple[str, str]], list]:
    known_tokens = processor.resolver.get_known_tokens()
    known_token_keys = {
        char_normalizer.normalize_for_match(k)
        for k in known_tokens
        if k
    }

    people_is_already_separated = has_people_separators(registration_text)
    use_strong_split_for_people = not people_is_already_separated

    resolved_first_line, title_tail_displays, title_extra_displays = processor.analyze_title_displays(first_line_raw)
    if title_tail_displays:
        logger.log(f"[INFO] title tail resolved={title_tail_displays}")
    title_tail_keys = {
        char_normalizer.normalize_for_match(display)
        for display in title_tail_displays
        if display
    }

    if title_extra_displays:
        logger.log(f"[INFO] title body displays={title_extra_displays}")

    title_base = resolved_first_line.strip()
    registration_output_text = ""

    tokens_reg: list[str] = []
    if registration_text:
        _, tokens_reg = processor.normalize_and_tokenize(
            registration_text,
            for_registration=True,
            strong_split=use_strong_split_for_people,
        )

    tokens_rest = list(tokens_reg)

    if title_tail_displays and tokens_rest:
        removed_tokens: list[str] = []
        filtered_tokens_rest: list[str] = []

        for tok in tokens_rest:
            tok_key = char_normalizer.normalize_for_match(tok)
            if tok_key in title_tail_keys:
                removed_tokens.append(tok)
                continue
            filtered_tokens_rest.append(tok)

        if removed_tokens:
            logger.log(f"[INFO] removed overlapping registration tokens={removed_tokens}")
            tokens_rest = filtered_tokens_rest

    if title_extra_displays:
        registration_keys = {
            char_normalizer.normalize_for_match(tok)
            for tok in tokens_rest
            if tok
        }
        appended_title_displays: list[str] = []
        for display in title_extra_displays:
            display_key = char_normalizer.normalize_for_match(display)
            if display_key in registration_keys:
                continue
            appended_title_displays.append(display)

        if appended_title_displays:
            logger.log(f"[INFO] appended title displays={appended_title_displays}")
            tokens_rest = dedupe_space_separated_tokens(tokens_rest + appended_title_displays)

    pending_items = []
    if title_base and filename_normalizer is not None:
        title_base, title_pending = filename_normalizer.normalize_text(title_base, "title_only")
        pending_items.extend(title_pending)

    if tokens_rest:
        registration_output_text = " ".join(tokens_rest).strip()
        if filename_normalizer is not None:
            registration_output_text, registration_pending = filename_normalizer.normalize_text(
                registration_output_text,
                "registration",
            )
            pending_items.extend(registration_pending)

    parts: list[str] = []
    if title_base:
        parts.append(title_base)
    if registration_output_text:
        parts.append(registration_output_text)

    base_line = " ".join(parts).strip()
    if not base_line and tokens_reg:
        base_line = " ".join(tokens_reg).strip()

    first_line_token_keys: set[str] = set()
    if resolved_first_line:
        _, first_tokens = processor.normalize_and_tokenize(
            resolved_first_line,
            for_registration=False,
        )
        first_line_token_keys = {
            char_normalizer.normalize_for_match(t) for t in first_tokens if t
        }

    alias_pairs = detect_alias_pairs_in_raw(registration_text, char_normalizer)
    alias_pair_name_keys: set[str] = set()
    for a, b in alias_pairs:
        if a:
            alias_pair_name_keys.add(char_normalizer.normalize_for_match(a))
        if b:
            alias_pair_name_keys.add(char_normalizer.normalize_for_match(b))

    new_names: list[str] = []
    seen_new_keys: set[str] = set()

    for tok in tokens_reg:
        tok_out = normalize_output_text(char_normalizer, tok)
        tok_key = char_normalizer.normalize_for_match(tok_out)

        if not is_plausible_name_token(tok_out):
            continue
        if tok_key in known_token_keys:
            continue
        if exclude_first_line_tokens_for_new_names and tok_key in first_line_token_keys:
            continue
        if tok_key in alias_pair_name_keys:
            continue
        if tok_key in seen_new_keys:
            continue

        seen_new_keys.add(tok_key)
        new_names.append(tok_out)

    base_line = text_normalizer.sanitize_for_windows_filename(
        base_line,
        max_len=MAX_FILENAME_LEN,
        truncate=False,
        warn_only=True,
        logger=logger,
    )

    if not base_line.lower().endswith(".mp4"):
        base_line += ".mp4"

    if len(base_line) > MAX_FILENAME_LEN:
        logger.log(
            f"[WARN] filename length over threshold after ext: "
            f"len={len(base_line)} > {MAX_FILENAME_LEN} (no truncation)"
        )

    final_text = base_line + "\n"
    logger.log(f"[INFO] people_is_already_separated={people_is_already_separated}")
    logger.log(f"[INFO] registration_text_len={len(registration_text)}")
    return final_text, new_names, alias_pairs, pending_items


def convert_title_only(
    title_line: str,
    processor: AliasTextProcessor,
    text_normalizer: TextNormalizer,
    logger: SimpleLogger,
    filename_normalizer: FilenameNormalizeProcessor | None = None,
) -> tuple[str, list[str], list[str], list]:
    base, tail_displays, extra_displays = processor.analyze_title_displays(title_line)

    if extra_displays:
        base = (base + " " + " ".join(extra_displays)).strip()

    pending_items = []
    if filename_normalizer is not None:
        base, pending_items = filename_normalizer.normalize_text(base, "title_only")

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

    return base + "\n", tail_displays, extra_displays, pending_items


class AvTextRuntimeService:
    def __init__(self, base_dir: Path, daemon_logger: Optional[SimpleLogger] = None):
        self.base_dir = Path(base_dir)
        self.setting_ini = self.base_dir / "setting.ini"
        self.file_io = FileTextIO()
        self.char_normalizer = CharNormalizer()
        self.text_normalizer = TextNormalizer(char_normalizer=self.char_normalizer)
        self.daemon_logger = daemon_logger
        self.conn = None
        self._alias_signature: Optional[TableSignature] = None
        self._rules_signature: Optional[TableSignature] = None
        self._alias_processor: Optional[AliasTextProcessor] = None
        self._filename_normalizer: Optional[FilenameNormalizeProcessor] = None

    def _dlog(self, msg: str) -> None:
        if self.daemon_logger:
            self.daemon_logger.log(msg)

    def close(self, logger: Optional[SimpleLogger] = None) -> None:
        safe_close(self.conn, logger or self.daemon_logger)
        self.conn = None
        self._alias_processor = None
        self._filename_normalizer = None
        self._alias_signature = None
        self._rules_signature = None

    def _load_db_config(self):
        return DbConfigLoader.load_from_ini(self.setting_ini)

    def ensure_connection(self, logger: SimpleLogger, *, required: bool) -> object | None:
        if self.conn is not None:
            try:
                cur = self.conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                return self.conn
            except Exception as e:
                logger.log(f"[WARN] cached DB connection invalid, reconnecting: {e!r}")
                self.close(logger)

        cfg = self._load_db_config()
        if not cfg:
            if required:
                raise RuntimeError(f"DB設定が見つかりません: {self.setting_ini}")
            return None

        conn = DbConnector(logger).connect(cfg)
        if conn is None and required:
            raise RuntimeError("DB接続に失敗しました。DBが起動しているか確認してください。")
        self.conn = conn
        return self.conn

    def _fetch_signature(
        self,
        logger: SimpleLogger,
        *,
        sql: str,
        required: bool,
    ) -> Optional[TableSignature]:
        conn = self.ensure_connection(logger, required=required)
        if conn is None:
            return None

        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        if not row:
            return TableSignature(0, "", 0)

        row_count = int(row[0] or 0)
        max_updated = row[1]
        max_identity = int(row[2] or 0)

        if max_updated is None:
            max_updated_text = ""
        else:
            max_updated_text = str(max_updated)

        return TableSignature(row_count, max_updated_text, max_identity)

    def get_actress_signature(self, logger: SimpleLogger) -> TableSignature:
        sig = self._fetch_signature(
            logger,
            sql=(
                "SELECT COUNT(*), "
                "MAX(COALESCE(UPDATED_AT, CREATED_AT)), "
                "MAX(ACTRESS_ID) "
                "FROM dbo.ACTRESS_DATA"
            ),
            required=True,
        )
        if sig is None:
            raise RuntimeError("ACTRESS_DATA signature not available")
        return sig

    def get_rules_signature(self, logger: SimpleLogger) -> Optional[TableSignature]:
        try:
            return self._fetch_signature(
                logger,
                sql=(
                    "SELECT COUNT(*), "
                    "MAX(UPDATED_AT), "
                    "MAX(RULE_ID) "
                    "FROM dbo.FILENAME_NORMALIZE_RULES"
                ),
                required=False,
            )
        except Exception as e:
            logger.log(f"[WARN] get_rules_signature failed: {e!r}")
            return None

    def get_alias_processor(self, logger: SimpleLogger, *, force: bool = False) -> AliasTextProcessor:
        signature = self.get_actress_signature(logger)
        if (
            (not force)
            and self._alias_processor is not None
            and self._alias_signature == signature
        ):
            return self._alias_processor

        conn = self.ensure_connection(logger, required=True)
        alias_repo = AliasRepository(logger=logger, char_normalizer=self.char_normalizer)
        aliases = alias_repo.load_from_db(conn)
        resolver = AliasResolver(aliases, logger, self.char_normalizer)
        resolver.build()
        self._alias_processor = AliasTextProcessor(resolver, self.text_normalizer, self.char_normalizer)
        self._alias_signature = signature
        return self._alias_processor

    def get_filename_normalizer(
        self,
        logger: SimpleLogger,
        *,
        force: bool = False,
    ) -> FilenameNormalizeProcessor:
        signature = self.get_rules_signature(logger)
        if (
            (not force)
            and self._filename_normalizer is not None
            and self._rules_signature == signature
        ):
            return self._filename_normalizer

        conn = self.ensure_connection(logger, required=False)
        normalize_repo = FilenameNormalizeRepository(logger=logger)
        rules = normalize_repo.load_rules_from_db(conn)
        self._filename_normalizer = FilenameNormalizeProcessor(rules, logger=logger)
        self._rules_signature = signature
        return self._filename_normalizer

    def invalidate_alias_cache(self) -> None:
        self._alias_processor = None
        self._alias_signature = None

    def invalidate_rules_cache(self) -> None:
        self._filename_normalizer = None
        self._rules_signature = None

    def apply_db_updates(
        self,
        logger: SimpleLogger,
        new_names: list[str],
        alias_pairs: list[tuple[str, str]],
    ) -> DbUpdateStats:
        conn = self.ensure_connection(logger, required=True)
        stats = DbUpdateStats()

        unique_names = _normalize_unique_names(new_names, self.char_normalizer)
        unique_pairs = _normalize_unique_alias_pairs(alias_pairs, self.char_normalizer)

        if not unique_names and not unique_pairs:
            return stats

        try:
            cur = conn.cursor()
            cur.execute("SELECT ACTRESS_ID, OLD_NAME, NEW_NAME FROM dbo.ACTRESS_DATA")
            rows = cur.fetchall()

            old_rows_by_key: dict[str, dict[str, object]] = {}
            known_name_keys: set[str] = set()

            def remember_row(actress_id, old_name: str, new_name: str) -> None:
                old_out = normalize_output_text(self.char_normalizer, old_name)
                new_out = normalize_output_text(self.char_normalizer, new_name)

                old_key = self.char_normalizer.normalize_for_match(old_out)
                new_key = self.char_normalizer.normalize_for_match(new_out)

                if old_key:
                    old_rows_by_key[old_key] = {
                        "actress_id": actress_id,
                        "old_name": old_out,
                        "new_name": new_out,
                    }
                    known_name_keys.add(old_key)

                if new_key:
                    known_name_keys.add(new_key)

            for actress_id, old_name, new_name in rows:
                remember_row(actress_id, old_name or "", new_name or "")

            def fetch_row_by_old_name(name: str):
                key = self.char_normalizer.normalize_for_match(name)
                if not key:
                    return None
                return old_rows_by_key.get(key)

            def choose_old_new(a: str, b: str) -> tuple[str, str]:
                row_a = fetch_row_by_old_name(a)
                row_b = fetch_row_by_old_name(b)

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

            for a, b in unique_pairs:
                old_name, new_name = choose_old_new(a, b)
                row = fetch_row_by_old_name(old_name)

                if row:
                    current_new = normalize_output_text(self.char_normalizer, row.get("new_name", ""))
                    if (not current_new) or (
                        self.char_normalizer.normalize_for_match(current_new)
                        != self.char_normalizer.normalize_for_match(new_name)
                    ):
                        cur.execute(
                            "UPDATE dbo.ACTRESS_DATA "
                            "SET NEW_NAME = ?, UPDATED_AT = SYSDATETIME() "
                            "WHERE ACTRESS_ID = ?",
                            (new_name, row.get("actress_id")),
                        )
                        remember_row(row.get("actress_id"), row.get("old_name", old_name), new_name)
                        stats.alias_updated += 1
                    continue

                cur.execute(
                    "INSERT INTO dbo.ACTRESS_DATA (OLD_NAME, NEW_NAME) VALUES (?, ?)",
                    (old_name, new_name),
                )
                cur.execute(
                    "SELECT ACTRESS_ID, OLD_NAME, NEW_NAME FROM dbo.ACTRESS_DATA WHERE OLD_NAME = ?",
                    (old_name,),
                )
                inserted_row = cur.fetchone()
                if inserted_row:
                    remember_row(inserted_row[0], inserted_row[1] or "", inserted_row[2] or "")
                else:
                    remember_row(None, old_name, new_name)
                stats.alias_inserted += 1

            for name in unique_names:
                name_key = self.char_normalizer.normalize_for_match(name)
                if not name_key or name_key in known_name_keys:
                    continue

                cur.execute(
                    "INSERT INTO dbo.ACTRESS_DATA (OLD_NAME) VALUES (?)",
                    (name,),
                )
                known_name_keys.add(name_key)
                old_rows_by_key[name_key] = {
                    "actress_id": None,
                    "old_name": name,
                    "new_name": "",
                }
                stats.new_names_inserted += 1

            conn.commit()
            logger.log(
                "[INFO] DB updates applied: "
                f"alias_updated={stats.alias_updated}, "
                f"alias_inserted={stats.alias_inserted}, "
                f"new_names_inserted={stats.new_names_inserted}"
            )
        except Exception as e:
            logger.log(f"[ERROR] apply_db_updates failed: {e!r}")
            raise

        if stats.changed:
            self.invalidate_alias_cache()

        return stats

    def _write_output(self, output_path: Path, converted: str, logger: SimpleLogger) -> None:
        self.file_io.write_cp932(output_path, converted)
        logger.log(f"[INFO] output written: {output_path}")

    def run_title_and_actress(
        self,
        logger: SimpleLogger,
        extra_args: list[str] | None = None,
    ) -> CommandResult:
        extra_args = list(extra_args or [])
        logger.log("=== av_text_convert start ===")

        input_path: Optional[Path] = None
        is_arg_mode = len(extra_args) >= 1
        if is_arg_mode:
            input_path = Path(extra_args[0])

        try:
            self.ensure_connection(logger, required=True)
        except Exception as e:
            msg = str(e)
            logger.log(f"[ERROR] {msg}")
            logger.log("=== av_text_convert end ===")
            return CommandResult(1, msg)

        if is_arg_mode:
            if not input_path or not input_path.exists():
                msg = f"入力ファイルが見つかりません: {input_path}"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)

            try:
                text, encoding_used = self.file_io.load_text_with_fallback(input_path)
            except UnicodeError:
                msg = "input ファイルの文字コードを utf-8 / cp932 で読めませんでした。"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)
            except Exception as e:
                msg = f"input ファイル読み込み失敗: {e!r}"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)

            logger.log(f"[INFO] input loaded: {input_path} (encoding={encoding_used})")

            preprocessed = dedupe_line_full_repeat(text)
            lines = preprocessed.splitlines()
            first_line_raw = lines[0] if lines else ""

            registration_text = get_text_excluding_first_line(preprocessed)
            registration_text, skipped_unknown_lines = filter_ignored_actress_lines(registration_text)
            if skipped_unknown_lines:
                logger.log(f"[INFO] skipped unknown placeholder lines in registration_text: {skipped_unknown_lines}")

            source_desc = f"{input_path} (encoding={encoding_used})"
            output_path = input_path.with_name(input_path.stem + "_converted" + input_path.suffix)
            exclude_first_line_tokens_for_new_names = True
        else:
            title_path = self.base_dir / "title.txt"
            actress_path = self.base_dir / "actress.txt"

            if not title_path.exists():
                msg = f"title.txt が見つかりません: {title_path}"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)

            if not actress_path.exists():
                msg = f"actress.txt が見つかりません: {actress_path}"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)

            try:
                title_text, enc_title = self.file_io.load_text_with_fallback(title_path)
            except UnicodeError:
                msg = "title.txt の文字コードを utf-8 / cp932 で読めませんでした。"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)
            except Exception as e:
                msg = f"title.txt 読み込み失敗: {e!r}"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)

            try:
                actress_text, enc_act = self.file_io.load_text_with_fallback(actress_path)
            except UnicodeError:
                msg = "actress.txt の文字コードを utf-8 / cp932 で読めませんでした。"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)
            except Exception as e:
                msg = f"actress.txt 読み込み失敗: {e!r}"
                logger.log(f"[ERROR] {msg}")
                logger.log("=== av_text_convert end ===")
                return CommandResult(1, msg)

            logger.log(f"[INFO] title loaded:  {title_path} (encoding={enc_title})")
            logger.log(f"[INFO] actress loaded: {actress_path} (encoding={enc_act})")

            title_lines = title_text.splitlines()
            title_line = title_lines[0].rstrip("\r\n") if title_lines else ""
            combined = title_line + "\n" + actress_text
            preprocessed = dedupe_line_full_repeat(combined)
            lines = preprocessed.splitlines()
            first_line_raw = lines[0] if lines else ""

            registration_text = get_text_excluding_first_line(preprocessed)
            registration_text, skipped_unknown_lines = filter_ignored_actress_lines(registration_text)
            if skipped_unknown_lines:
                logger.log(f"[INFO] skipped unknown placeholder lines in actress/registration_text: {skipped_unknown_lines}")

            source_desc = f"title.txt({enc_title}) + actress.txt({enc_act})"
            output_path = self.base_dir / "conv_converted.txt"
            exclude_first_line_tokens_for_new_names = False

        try:
            filename_normalizer = self.get_filename_normalizer(logger)
            processor = self.get_alias_processor(logger)

            _, pre_new_names, pre_alias_pairs, _ = convert_text(
                first_line_raw=first_line_raw,
                registration_text=registration_text,
                processor=processor,
                filename_normalizer=None,
                char_normalizer=self.char_normalizer,
                text_normalizer=self.text_normalizer,
                logger=logger,
                exclude_first_line_tokens_for_new_names=exclude_first_line_tokens_for_new_names,
            )

            stats = DbUpdateStats()
            if pre_new_names or pre_alias_pairs:
                stats = self.apply_db_updates(logger, pre_new_names, pre_alias_pairs)

            if stats.changed:
                processor = self.get_alias_processor(logger, force=True)

            converted, new_names, alias_pairs, pending_items = convert_text(
                first_line_raw=first_line_raw,
                registration_text=registration_text,
                processor=processor,
                filename_normalizer=filename_normalizer,
                char_normalizer=self.char_normalizer,
                text_normalizer=self.text_normalizer,
                logger=logger,
                exclude_first_line_tokens_for_new_names=exclude_first_line_tokens_for_new_names,
            )

            normalize_repo = FilenameNormalizeRepository(logger=logger)
            normalize_repo.record_pending(self.conn, pending_items)

            self._write_output(output_path, converted, logger)
        except Exception as e:
            logger.log(f"[ERROR] title_and_actress failed: {e!r}")
            logger.log("=== av_text_convert end ===")
            return CommandResult(1, f"変換処理に失敗しました: {e!r}", str(output_path))

        logger.log(f"[INFO] new_names={new_names}")
        logger.log("=== av_text_convert end ===")

        return CommandResult(
            0,
            f"変換完了: {output_path} （input: {source_desc}, output: cp932, CRLF, .mp4付き）",
            str(output_path),
            {
                "db_changed": stats.changed,
                "alias_updated": stats.alias_updated,
                "alias_inserted": stats.alias_inserted,
                "new_names_inserted": stats.new_names_inserted,
                "new_names": list(new_names),
                "alias_pairs": list(alias_pairs),
            },
        )

    def run_title_only(
        self,
        logger: SimpleLogger,
        extra_args: list[str] | None = None,
    ) -> CommandResult:
        del extra_args
        logger.log("=== av_title_convert start ===")

        title_path = self.base_dir / "title.txt"
        output_path = self.base_dir / "conv_converted.txt"

        try:
            self.ensure_connection(logger, required=True)
        except Exception as e:
            msg = str(e)
            logger.log(f"[ERROR] {msg}")
            logger.log("=== av_title_convert end ===")
            return CommandResult(1, msg)

        if not title_path.exists():
            msg = f"title.txt が見つかりません: {title_path}"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== av_title_convert end ===")
            return CommandResult(1, msg)

        try:
            title_line, enc = self.file_io.load_first_line_with_fallback(title_path)
            logger.log(f"[INFO] title loaded: {title_path} (encoding={enc})")
        except UnicodeError:
            msg = "title.txt の文字コードを utf-8 / cp932 で読めませんでした。"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== av_title_convert end ===")
            return CommandResult(1, msg)
        except Exception as e:
            msg = f"title.txt 読み込み失敗: {e!r}"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== av_title_convert end ===")
            return CommandResult(1, msg)

        try:
            processor = self.get_alias_processor(logger)
            filename_normalizer = self.get_filename_normalizer(logger)

            converted, tail_displays, extra_displays, pending_items = convert_title_only(
                title_line=title_line,
                processor=processor,
                text_normalizer=self.text_normalizer,
                logger=logger,
                filename_normalizer=filename_normalizer,
            )

            normalize_repo = FilenameNormalizeRepository(logger=logger)
            normalize_repo.record_pending(self.conn, pending_items)
            self._write_output(output_path, converted, logger)
        except Exception as e:
            logger.log(f"[ERROR] title_only failed: {e!r}")
            logger.log("=== av_title_convert end ===")
            return CommandResult(1, f"変換処理に失敗しました: {e!r}", str(output_path))

        logger.log(f"[INFO] tail_displays={tail_displays}")
        logger.log(f"[INFO] extra_displays={extra_displays}")
        logger.log("=== av_title_convert end ===")

        return CommandResult(
            0,
            f"変換完了: {output_path} （input: {title_path} encoding={enc}, output: cp932, CRLF, .mp4付き）",
            str(output_path),
            {
                "tail_displays": list(tail_displays),
                "extra_displays": list(extra_displays),
            },
        )

    def run_no_title(
        self,
        logger: SimpleLogger,
        extra_args: list[str] | None = None,
    ) -> CommandResult:
        del extra_args
        logger.log("=== no_title_to_conv start ===")

        no_path = self.base_dir / "no.txt"
        title_path = self.base_dir / "title.txt"
        out_path = self.base_dir / "conv_converted.txt"

        try:
            self.ensure_connection(logger, required=False)
        except Exception as e:
            logger.log(f"[WARN] DB init failed in no_title_to_conv: {e!r}")

        try:
            filename_normalizer = self.get_filename_normalizer(logger)
        except Exception as e:
            logger.log(f"[ERROR] get_filename_normalizer failed: {e!r}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, f"変換前準備に失敗しました: {e!r}", str(out_path))

        if not no_path.exists():
            msg = f"no.txt が見つかりません: {no_path}"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)
        if not title_path.exists():
            msg = f"title.txt が見つかりません: {title_path}"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)

        try:
            no_line, _ = self.file_io.load_first_line_with_fallback(no_path)
            title_line, _ = self.file_io.load_first_line_with_fallback(title_path)
        except UnicodeError:
            msg = "no.txt または title.txt の文字コードを utf-8 / cp932 で読めませんでした。"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)
        except Exception as e:
            msg = f"入力ファイル読み込み失敗: {e!r}"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)

        if not no_line:
            msg = "no.txt が空です。"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)
        if not title_line:
            msg = "title.txt が空です。"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)

        if not re.fullmatch(r"\d+", no_line):
            msg = "no.txt は数字のみの1行でお願いします。例: 1234"
            logger.log(f"[ERROR] {msg}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, msg)

        expected = "".join(str(i) for i in range(1, len(no_line) + 1))
        warn_message = ""
        if no_line != expected:
            warn_message = (
                f"[WARN] no.txt が典型的な連番（{expected}）ではありません。"
                f" 文字数={len(no_line)} 本として処理します。"
            )
            logger.log(warn_message)

        count = len(no_line)
        lines: list[str] = []
        pending_items: list[Any] = []
        for i in range(1, count + 1):
            line, line_pending = build_safe_filename(
                title_line,
                i,
                self.text_normalizer,
                filename_normalizer=filename_normalizer,
            )
            lines.append(line)
            pending_items.extend(line_pending)

        text = "\n".join(lines) + "\n"
        try:
            self.file_io.write_cp932(out_path, text)
            normalize_repo = FilenameNormalizeRepository(logger=logger)
            normalize_repo.record_pending(self.conn, pending_items)
        except Exception as e:
            logger.log(f"[ERROR] no_title failed: {e!r}")
            logger.log("=== no_title_to_conv end ===")
            return CommandResult(1, f"出力書き込み失敗: {e!r}", str(out_path))
        logger.log("=== no_title_to_conv end ===")

        message = f"出力完了: {out_path} （{count} 行）"
        if warn_message:
            message = warn_message + "\n" + message
        return CommandResult(0, message, str(out_path), {"count": count})

    def run_mode(self, mode: str, extra_args: list[str] | None = None) -> CommandResult:
        mode = (mode or "").strip()
        logger = build_logger(self.base_dir, mode)
        if mode == MODE_TITLE_AND_ACTRESS:
            return self.run_title_and_actress(logger, extra_args)
        if mode == MODE_TITLE_ONLY:
            return self.run_title_only(logger, extra_args)
        if mode == MODE_NO_TITLE:
            return self.run_no_title(logger, extra_args)
        return CommandResult(2, f"unknown mode: {mode}")


def run_one_shot(mode: str, extra_args: list[str] | None = None) -> CommandResult:
    base_dir = get_base_dir()
    service = AvTextRuntimeService(base_dir)
    try:
        return service.run_mode(mode, extra_args)
    finally:
        service.close()
