# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import locale
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


APP_NAME = "AV Text 専用入力エディタ"
DEFAULT_WATCH_INTERVAL_MS = 1200
DEFAULT_SAVE_DELAY_MS = 450
RELOAD_DEBOUNCE_MS = 250
ASYNC_POLL_MS = 120
DEFAULT_WINDOW_GEOMETRY = "1280x245"
LEGACY_WINDOW_GEOMETRY = "1180x820"
MIN_WINDOW_WIDTH = 860
MIN_WINDOW_HEIGHT = 220
MAX_WINDOW_WIDTH = 1400
MAX_WINDOW_HEIGHT = 255

FIELD_ORDER = ("title", "actress", "no")
FIELD_LABELS = {
    "title": "タイトル",
    "actress": "女優",
    "no": "品番",
}

MODE_SPECS = {
    "title_and_actress": {
        "label": "変換",
        "batch": "run_av_text_convert.bat",
        "status": "変換中",
    },
    "title_only": {
        "label": "タイトルのみ変換",
        "batch": "run_av_title_convert.bat",
        "status": "タイトルのみ変換中",
    },
    "no_title": {
        "label": "品番連番変換",
        "batch": "run_no_title_to_conv.bat",
        "status": "品番連番変換中",
    },
}

MONITORED_FILES = {
    "title": "title.txt",
    "actress": "actress.txt",
    "no": "no.txt",
    "result": "conv_converted.txt",
}


def default_runtime_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "sakura" / "avtext"
    return Path(__file__).resolve().parent.parent


def settings_home() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "AVTextInputPad"
    return Path.home() / "AppData" / "Local" / "AVTextInputPad"


@dataclass(frozen=True)
class FileSignature:
    exists: bool
    mtime_ns: int
    size: int


@dataclass
class AppSettings:
    runtime_dir: str
    watch_interval_ms: int = DEFAULT_WATCH_INTERVAL_MS
    save_delay_ms: int = DEFAULT_SAVE_DELAY_MS
    window_geometry: str = DEFAULT_WINDOW_GEOMETRY


@dataclass(frozen=True)
class RuntimePaths:
    base_dir: Path
    title_path: Path
    actress_path: Path
    no_path: Path
    result_path: Path
    convert_bat: Path
    title_only_bat: Path
    no_title_bat: Path

    @classmethod
    def from_base_dir(cls, base_dir: Path) -> "RuntimePaths":
        base_dir = Path(base_dir)
        return cls(
            base_dir=base_dir,
            title_path=base_dir / "title.txt",
            actress_path=base_dir / "actress.txt",
            no_path=base_dir / "no.txt",
            result_path=base_dir / "conv_converted.txt",
            convert_bat=base_dir / "run_av_text_convert.bat",
            title_only_bat=base_dir / "run_av_title_convert.bat",
            no_title_bat=base_dir / "run_no_title_to_conv.bat",
        )

    def path_for_key(self, key: str) -> Path:
        if key == "title":
            return self.title_path
        if key == "actress":
            return self.actress_path
        if key == "no":
            return self.no_path
        if key == "result":
            return self.result_path
        raise KeyError(key)

    def batch_for_mode(self, mode: str) -> Path:
        if mode == "title_and_actress":
            return self.convert_bat
        if mode == "title_only":
            return self.title_only_bat
        if mode == "no_title":
            return self.no_title_bat
        raise KeyError(mode)

    def validate_batches(self) -> list[Path]:
        missing: list[Path] = []
        for mode in MODE_SPECS:
            path = self.batch_for_mode(mode)
            if not path.exists():
                missing.append(path)
        return missing


class SimpleLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} {message}"
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")


class SettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings(runtime_dir=str(default_runtime_dir()))

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return AppSettings(runtime_dir=str(default_runtime_dir()))

        runtime_dir = str(payload.get("runtime_dir") or default_runtime_dir())
        watch_interval_ms = int(payload.get("watch_interval_ms") or DEFAULT_WATCH_INTERVAL_MS)
        save_delay_ms = int(payload.get("save_delay_ms") or DEFAULT_SAVE_DELAY_MS)
        raw_window_geometry = str(payload.get("window_geometry") or DEFAULT_WINDOW_GEOMETRY)
        window_geometry = normalize_window_geometry(raw_window_geometry)
        return AppSettings(
            runtime_dir=runtime_dir,
            watch_interval_ms=max(500, watch_interval_ms),
            save_delay_ms=max(150, save_delay_ms),
            window_geometry=window_geometry,
        )

    def save(self, settings: AppSettings) -> None:
        payload = {
            "runtime_dir": settings.runtime_dir,
            "watch_interval_ms": int(settings.watch_interval_ms),
            "save_delay_ms": int(settings.save_delay_ms),
            "window_geometry": settings.window_geometry,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )


def read_text_with_fallback(path: Path) -> tuple[str, str]:
    last_error = None
    for encoding in ("utf-8", "utf-8-sig", "cp932"):
        try:
            with path.open("r", encoding=encoding) as f:
                return f.read(), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    raise UnicodeError(f"{path} の文字コードを読めませんでした: {last_error!r}")


def normalize_title_like(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    return " ".join(parts).strip()


def normalize_multiline(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n")


def normalize_input_text(key: str, text: str) -> str:
    if key in {"title", "no"}:
        return normalize_title_like(text)
    if key == "actress":
        return normalize_multiline(text)
    raise KeyError(key)


def write_input_file(path: Path, key: str, text: str) -> str:
    normalized = normalize_input_text(key, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(normalized)
        f.write("\n")
    return normalized


def safe_signature(path: Path) -> FileSignature:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return FileSignature(False, 0, 0)
    return FileSignature(True, stat.st_mtime_ns, stat.st_size)


def shorten_detail(text: str, limit: int = 180) -> str:
    raw = " ".join((text or "").replace("\r", "\n").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def decode_console_bytes(raw: bytes) -> tuple[str, str]:
    if not raw:
        return "", "empty"

    encodings: list[str] = ["utf-8", "utf-8-sig"]
    preferred = (locale.getpreferredencoding(False) or "").strip()
    if preferred:
        encodings.append(preferred)
    encodings.extend(["cp932", "mbcs"])

    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return raw.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            continue

    fallback = preferred or "utf-8"
    return raw.decode(fallback, errors="replace"), f"{fallback}/replace"


def parse_window_geometry(geometry: str) -> tuple[int, int] | None:
    raw = (geometry or "").strip()
    if not raw or "x" not in raw:
        return None

    size_part = raw.split("+", 1)[0]
    width_text, _, height_text = size_part.partition("x")
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError:
        return None

    return width, height


def normalize_window_geometry(geometry: str, fallback: str = DEFAULT_WINDOW_GEOMETRY) -> str:
    parsed = parse_window_geometry(geometry)
    if parsed is None:
        return fallback

    width, height = parsed
    if width <= 1 or height <= 1:
        return fallback
    legacy_width, legacy_height = parse_window_geometry(LEGACY_WINDOW_GEOMETRY) or (0, 0)
    if width == legacy_width and height == legacy_height:
        return fallback
    if width > MAX_WINDOW_WIDTH or height > MAX_WINDOW_HEIGHT:
        return fallback
    if width < MIN_WINDOW_WIDTH or height < MIN_WINDOW_HEIGHT:
        return fallback
    return geometry


def get_cursor_work_area() -> tuple[int, int, int, int]:
    if os.name != "nt":
        return (0, 0, 1920, 1080)

    import ctypes
    from ctypes import wintypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32
    MONITOR_DEFAULTTONEAREST = 2
    pt = POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return (0, 0, 1920, 1080)

    monitor = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return (0, 0, 1920, 1080)

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return (0, 0, 1920, 1080)

    work = info.rcWork
    return (work.left, work.top, work.right, work.bottom)


class AvTextInputPadApp:
    def __init__(self, root: tk.Tk, settings_store: SettingsStore, logger: SimpleLogger):
        self.root = root
        self.settings_store = settings_store
        self.logger = logger
        self.settings = settings_store.load()
        self.runtime_paths = RuntimePaths.from_base_dir(Path(self.settings.runtime_dir))

        self.queue: queue.Queue[tuple] = queue.Queue()
        self.watch_after_id: str | None = None
        self.save_after_id: str | None = None
        self.reload_after_id: str | None = None
        self.async_after_id: str | None = None
        self.active_mode: str | None = None
        self.is_applying_ui = False

        self.file_signatures: dict[str, FileSignature] = {
            key: FileSignature(False, 0, 0) for key in MONITORED_FILES
        }
        self.loaded_texts: dict[str, str] = {
            key: "" for key in MONITORED_FILES
        }
        self.pending_reload_keys: set[str] = set()
        self.pending_external_texts: dict[str, str] = {}
        self.dirty_fields: set[str] = set()

        self.status_var = tk.StringVar(value="待機中")
        self.detail_var = tk.StringVar(value="起動準備中")
        self.notice_var = tk.StringVar(value="")
        self.runtime_dir_var = tk.StringVar(value=str(self.runtime_paths.base_dir))
        self.no_var = tk.StringVar()

        self.button_map: dict[str, ttk.Button] = {}
        self.main_notebook: ttk.Notebook | None = None
        self.tab_frames: dict[str, ttk.Frame] = {}
        self.text_widgets: dict[str, ScrolledText] = {}
        self.result_widget: ScrolledText | None = None
        self.runtime_entry: ttk.Entry | None = None
        self.no_entry: ttk.Entry | None = None
        self.progress: ttk.Progressbar | None = None
        self.status_label: ttk.Label | None = None
        self.edit_context_menu: tk.Menu | None = None
        self.readonly_context_menu: tk.Menu | None = None
        self._context_target: tk.Misc | None = None

        self._build_ui()
        self._bind_events()
        self._build_context_menus()

    def _build_ui(self) -> None:
        self.root.title(APP_NAME)
        try:
            self.root.geometry(self.settings.window_geometry)
        except Exception:
            self.root.geometry(DEFAULT_WINDOW_GEOMETRY)
        self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.root.maxsize(
            min(self.root.winfo_screenwidth(), MAX_WINDOW_WIDTH),
            min(self.root.winfo_screenheight(), MAX_WINDOW_HEIGHT),
        )

        outer = ttk.Frame(self.root, padding=6)
        outer.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        runtime_frame = ttk.Frame(outer)
        runtime_frame.grid(row=0, column=0, sticky="ew")
        runtime_frame.columnconfigure(1, weight=1)

        ttk.Label(runtime_frame, text="ランタイム").grid(row=0, column=0, padx=(0, 6), pady=0, sticky="w")
        runtime_entry = ttk.Entry(runtime_frame, textvariable=self.runtime_dir_var)
        runtime_entry.grid(row=0, column=1, padx=(0, 6), pady=0, sticky="ew")
        self.runtime_entry = runtime_entry
        ttk.Button(runtime_frame, text="参照", command=self.choose_runtime_dir).grid(row=0, column=2, padx=(0, 4), pady=0)
        ttk.Button(runtime_frame, text="再読込", command=lambda: self.apply_runtime_dir(force_reload=True)).grid(row=0, column=3, pady=0)

        content = ttk.Frame(outer)
        content.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(content)
        notebook.grid(row=0, column=0, sticky="nsew")
        self.main_notebook = notebook

        actress_tab = ttk.Frame(notebook, padding=4)
        actress_tab.columnconfigure(0, weight=1)
        actress_tab.rowconfigure(0, weight=1)
        notebook.add(actress_tab, text="女優")
        self.tab_frames["actress"] = actress_tab
        actress_text = ScrolledText(actress_tab, height=8, wrap="word", undo=True)
        actress_text.grid(row=0, column=0, sticky="nsew")
        self.text_widgets["actress"] = actress_text

        title_tab = ttk.Frame(notebook, padding=4)
        title_tab.columnconfigure(0, weight=1)
        title_tab.rowconfigure(0, weight=1)
        notebook.add(title_tab, text="タイトル")
        self.tab_frames["title"] = title_tab
        title_text = ScrolledText(title_tab, height=8, wrap="word", undo=True)
        title_text.grid(row=0, column=0, sticky="nsew")
        self.text_widgets["title"] = title_text

        result_tab = ttk.Frame(notebook, padding=4)
        result_tab.columnconfigure(0, weight=1)
        result_tab.rowconfigure(0, weight=1)
        notebook.add(result_tab, text="変換結果")
        self.tab_frames["result"] = result_tab
        self.result_widget = ScrolledText(result_tab, wrap="word", undo=False, height=8)
        self.result_widget.grid(row=0, column=0, sticky="nsew")
        self.result_widget.configure(state="disabled")

        status_frame = ttk.Frame(outer)
        status_frame.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(2, weight=1)

        self.status_label = ttk.Label(status_frame, textvariable=self.status_var)
        self.status_label.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.detail_var).grid(row=0, column=1, padx=(0, 8), pady=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.notice_var, foreground="#8a2b06").grid(
            row=0,
            column=2,
            padx=(0, 8),
            pady=0,
            sticky="w",
        )
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=110)
        self.progress.grid(row=0, column=3, pady=0, sticky="e")

        buttons = ttk.Frame(outer)
        buttons.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        for col in range(10):
            buttons.columnconfigure(col, weight=0)
        buttons.columnconfigure(8, weight=1)

        self.button_map["title_and_actress"] = ttk.Button(buttons, text="変換", command=lambda: self.start_conversion("title_and_actress"))
        self.button_map["title_and_actress"].grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.button_map["title_only"] = ttk.Button(buttons, text="タイトルのみ変換", command=lambda: self.start_conversion("title_only"))
        self.button_map["title_only"].grid(row=0, column=1, padx=4, sticky="ew")
        self.button_map["no_title"] = ttk.Button(buttons, text="品番連番変換", command=lambda: self.start_conversion("no_title"))
        self.button_map["no_title"].grid(row=0, column=2, padx=4, sticky="ew")
        self.button_map["copy"] = ttk.Button(buttons, text="結果をコピー", command=self.copy_result)
        self.button_map["copy"].grid(row=0, column=3, padx=4, sticky="ew")
        self.button_map["open"] = ttk.Button(buttons, text="出力ファイルを開く", command=self.open_output_file)
        self.button_map["open"].grid(row=0, column=4, padx=4, sticky="ew")
        ttk.Label(buttons, text="品番").grid(row=0, column=5, padx=(8, 4), sticky="w")
        no_entry = ttk.Entry(buttons, textvariable=self.no_var, width=10)
        no_entry.grid(row=0, column=6, padx=(0, 8), sticky="w")
        self.no_entry = no_entry
        self.root.after(0, self.ensure_window_on_screen)

    def _bind_events(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-r>", lambda _e: self.apply_runtime_dir(force_reload=True))
        self.root.bind("<Return>", self._on_root_return, add=True)

        for key, widget in self.text_widgets.items():
            widget.bind("<<Modified>>", lambda _e, field=key: self.on_text_modified(field))

        self.no_var.trace_add("write", lambda *_args: self.on_entry_modified("no"))

    def _build_context_menus(self) -> None:
        self.edit_context_menu = tk.Menu(self.root, tearoff=False)
        self.edit_context_menu.add_command(label="元に戻す", command=self.context_undo)
        self.edit_context_menu.add_command(label="やり直す", command=self.context_redo)
        self.edit_context_menu.add_separator()
        self.edit_context_menu.add_command(label="切り取り", command=self.context_cut)
        self.edit_context_menu.add_command(label="コピー", command=self.context_copy)
        self.edit_context_menu.add_command(label="貼り付け", command=self.context_paste)
        self.edit_context_menu.add_command(label="削除", command=self.context_delete)
        self.edit_context_menu.add_separator()
        self.edit_context_menu.add_command(label="すべて選択", command=self.context_select_all)

        self.readonly_context_menu = tk.Menu(self.root, tearoff=False)
        self.readonly_context_menu.add_command(label="コピー", command=self.context_copy)
        self.readonly_context_menu.add_command(label="すべて選択", command=self.context_select_all)

        widgets: list[tuple[tk.Misc, bool]] = []
        widgets.extend((widget, False) for widget in self.text_widgets.values())
        if self.result_widget is not None:
            widgets.append((self.result_widget, True))
        if self.runtime_entry is not None:
            widgets.append((self.runtime_entry, False))
        if self.no_entry is not None:
            widgets.append((self.no_entry, False))

        for widget, readonly in widgets:
            self._bind_context_menu(widget, readonly=readonly)

    def _bind_context_menu(self, widget: tk.Misc, *, readonly: bool) -> None:
        widget.bind("<Button-3>", lambda event, ro=readonly: self.show_context_menu(event, readonly=ro), add=True)
        widget.bind("<Shift-F10>", lambda event, ro=readonly: self.show_context_menu(event, readonly=ro), add=True)
        widget.bind("<Menu>", lambda event, ro=readonly: self.show_context_menu(event, readonly=ro), add=True)

    def show_context_menu(self, event: tk.Event, *, readonly: bool) -> str:
        widget = event.widget
        self._context_target = widget
        try:
            widget.focus_force()
        except Exception:
            pass

        menu = self.readonly_context_menu if readonly else self.edit_context_menu
        if menu is None:
            return "break"

        x_root = getattr(event, "x_root", 0) or 0
        y_root = getattr(event, "y_root", 0) or 0
        if x_root <= 0 and y_root <= 0:
            try:
                x_root = widget.winfo_rootx() + 12
                y_root = widget.winfo_rooty() + 12
            except Exception:
                x_root, y_root = 10, 10

        menu.tk_popup(x_root, y_root)
        menu.grab_release()
        return "break"

    def _current_context_widget(self) -> tk.Misc | None:
        widget = self._context_target
        if widget is not None:
            return widget
        return self.root.focus_get()

    def context_cut(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        if isinstance(widget, (tk.Text, ScrolledText, tk.Entry, ttk.Entry)):
            widget.event_generate("<<Cut>>")

    def context_copy(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        if isinstance(widget, (tk.Text, ScrolledText, tk.Entry, ttk.Entry)):
            widget.event_generate("<<Copy>>")

    def context_paste(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        if isinstance(widget, (tk.Text, ScrolledText, tk.Entry, ttk.Entry)):
            widget.event_generate("<<Paste>>")

    def context_delete(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        try:
            if isinstance(widget, (tk.Text, ScrolledText)):
                widget.delete("sel.first", "sel.last")
            elif isinstance(widget, (tk.Entry, ttk.Entry)):
                start = int(widget.index("sel.first"))
                end = int(widget.index("sel.last"))
                widget.delete(start, end)
        except Exception:
            pass

    def context_select_all(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        if isinstance(widget, (tk.Text, ScrolledText)):
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
            widget.see("insert")
        elif isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.selection_range(0, "end")
            widget.icursor("end")

    def context_undo(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        try:
            if isinstance(widget, (tk.Text, ScrolledText)):
                widget.edit_undo()
            elif isinstance(widget, (tk.Entry, ttk.Entry)):
                widget.event_generate("<<Undo>>")
        except Exception:
            pass

    def context_redo(self) -> None:
        widget = self._current_context_widget()
        if widget is None:
            return
        try:
            if isinstance(widget, (tk.Text, ScrolledText)):
                widget.edit_redo()
            elif isinstance(widget, (tk.Entry, ttk.Entry)):
                widget.event_generate("<<Redo>>")
        except Exception:
            pass

    def _on_root_return(self, event: tk.Event) -> None:
        if event.widget is self.root:
            return
        if event.widget is None:
            return
        if str(event.widget) == str(self.root):
            return

    def start(self) -> None:
        self.apply_runtime_dir(force_reload=True)
        self.schedule_watch()
        self.schedule_async_pump()

    def choose_runtime_dir(self) -> None:
        selected = filedialog.askdirectory(
            title="ランタイムフォルダを選択",
            initialdir=self.runtime_dir_var.get() or str(default_runtime_dir()),
        )
        if not selected:
            return
        self.runtime_dir_var.set(selected)
        self.apply_runtime_dir(force_reload=True)

    def apply_runtime_dir(self, force_reload: bool = False) -> None:
        requested = Path(self.runtime_dir_var.get().strip() or str(default_runtime_dir()))
        requested = requested.expanduser()
        changed = requested != self.runtime_paths.base_dir
        if not changed and not force_reload:
            return

        self.flush_save_now(reason="ランタイム切替前")
        self.runtime_paths = RuntimePaths.from_base_dir(requested)
        self.runtime_dir_var.set(str(requested))
        self.pending_external_texts.clear()
        self.pending_reload_keys.clear()
        self.dirty_fields.clear()
        self.notice_var.set("")

        self._reload_all_from_disk(reason="ランタイム読込")
        self.settings.runtime_dir = str(requested)
        self.persist_settings()

    def persist_settings(self) -> None:
        try:
            self.root.update_idletasks()
            self.settings.window_geometry = normalize_window_geometry(
                self.root.winfo_geometry(),
                fallback=self.settings.window_geometry,
            )
        except Exception:
            pass
        self.settings_store.save(self.settings)

    def ensure_window_on_screen(self) -> None:
        try:
            self.root.update_idletasks()
            width = max(MIN_WINDOW_WIDTH, min(MAX_WINDOW_WIDTH, self.root.winfo_width()))
            height = max(MIN_WINDOW_HEIGHT, min(MAX_WINDOW_HEIGHT, self.root.winfo_height()))
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            left, top, right, bottom = get_cursor_work_area()
            visible_margin = 80

            fits_horizontally = (x + visible_margin) < right and (x + width - visible_margin) > left
            fits_vertically = (y + visible_margin) < bottom and (y + height - visible_margin) > top
            if fits_horizontally and fits_vertically:
                return

            work_width = max(width, right - left)
            work_height = max(height, bottom - top)
            new_x = left + max(0, (work_width - width) // 2)
            new_y = top + max(0, (work_height - height) // 2)
            self.root.geometry(f"{width}x{height}+{new_x}+{new_y}")
            self.root.update_idletasks()
        except Exception as exc:
            self.logger.log(f"window normalize skipped: {exc!r}")

    def select_tab(self, name: str) -> None:
        if self.main_notebook is None:
            return
        frame = self.tab_frames.get(name)
        if frame is None:
            return
        self.main_notebook.select(frame)

    def focus_copy_button(self) -> None:
        button = self.button_map.get("copy")
        if button is None:
            return
        try:
            button.focus_set()
        except Exception as exc:
            self.logger.log(f"[WARN] focus copy button failed: {exc!r}")

    def set_status(self, status: str, detail: str, *, busy: bool = False, error: bool = False) -> None:
        self.status_var.set(status)
        self.detail_var.set(detail)
        if self.progress is not None:
            if busy:
                self.progress.start(10)
            else:
                self.progress.stop()
        if self.status_label is not None:
            color = "#a40000" if error else "#1f1f1f"
            self.status_label.configure(foreground=color)

    def set_notice(self, text: str) -> None:
        self.notice_var.set(text)

    def on_text_modified(self, field: str) -> None:
        widget = self.text_widgets[field]
        if self.is_applying_ui:
            widget.edit_modified(False)
            return

        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self.mark_dirty(field)

    def on_entry_modified(self, field: str) -> None:
        if self.is_applying_ui:
            return
        self.mark_dirty(field)

    def mark_dirty(self, field: str) -> None:
        self.dirty_fields.add(field)
        self.schedule_save()
        self.set_status("保存待ち", f"{FIELD_LABELS[field]} を編集中", busy=False)

    def schedule_save(self) -> None:
        if self.save_after_id is not None:
            self.root.after_cancel(self.save_after_id)
        self.save_after_id = self.root.after(self.settings.save_delay_ms, self.flush_save_now)

    def flush_save_now(self, reason: str = "自動保存") -> None:
        if self.save_after_id is not None:
            self.root.after_cancel(self.save_after_id)
            self.save_after_id = None

        if not self.dirty_fields:
            self.apply_pending_external_if_safe()
            return

        try:
            self.set_status("保存中", f"{reason} で入力ファイルを書き込み中", busy=False)
            for field in list(FIELD_ORDER):
                if field not in self.dirty_fields:
                    continue
                path = self.runtime_paths.path_for_key(field)
                text = self.get_widget_value(field)
                normalized = write_input_file(path, field, text)
                self.loaded_texts[field] = normalized
                self.file_signatures[field] = safe_signature(path)
                self.dirty_fields.discard(field)
                self.logger.log(f"[SAVE] field={field} path={path}")
                self.pending_external_texts.pop(field, None)

            self.apply_pending_external_if_safe()
            self.set_status("待機中", "自動保存が完了しました", busy=False)
        except Exception as exc:
            self.logger.log(f"[ERROR] save failed: {exc!r}")
            self.set_status("エラー", f"保存失敗: {exc!r}", busy=False, error=True)

    def apply_pending_external_if_safe(self) -> None:
        if not self.pending_external_texts:
            return

        applied_fields: list[str] = []
        for field, text in list(self.pending_external_texts.items()):
            if field in self.dirty_fields:
                continue
            self.apply_widget_value(field, text)
            self.loaded_texts[field] = text
            self.pending_external_texts.pop(field, None)
            applied_fields.append(FIELD_LABELS[field])

        if applied_fields:
            self.set_notice("外部更新を反映: " + ", ".join(applied_fields))
        elif self.pending_external_texts:
            pending = ", ".join(FIELD_LABELS[key] for key in self.pending_external_texts)
            self.set_notice(f"外部更新を保留中: {pending}")
        else:
            self.set_notice("")

    def schedule_watch(self) -> None:
        if self.watch_after_id is not None:
            self.root.after_cancel(self.watch_after_id)
        self.watch_after_id = self.root.after(self.settings.watch_interval_ms, self.watch_files)

    def watch_files(self) -> None:
        changed: list[str] = []
        for key in MONITORED_FILES:
            signature = safe_signature(self.runtime_paths.path_for_key(key))
            if signature != self.file_signatures.get(key):
                changed.append(key)

        if changed:
            self.pending_reload_keys.update(changed)
            self.schedule_reload()

        self.schedule_watch()

    def schedule_reload(self) -> None:
        if self.reload_after_id is not None:
            self.root.after_cancel(self.reload_after_id)
        self.reload_after_id = self.root.after(RELOAD_DEBOUNCE_MS, self.process_pending_reload)

    def process_pending_reload(self) -> None:
        self.reload_after_id = None
        keys = list(self.pending_reload_keys)
        self.pending_reload_keys.clear()
        if not keys:
            return

        for key in keys:
            self._reload_single_key(key, from_watch=True)

        self.apply_pending_external_if_safe()

    def _reload_all_from_disk(self, reason: str) -> None:
        self.set_status("待機中", f"{reason} 中", busy=False)
        for key in MONITORED_FILES:
            self._reload_single_key(key, from_watch=False)
        self.apply_pending_external_if_safe()
        missing = self.runtime_paths.validate_batches()
        if missing:
            joined = ", ".join(str(path.name) for path in missing)
            self.set_notice(f"既存 BAT が不足: {joined}")
        else:
            self.set_notice("")
        self.set_status("待機中", f"{self.runtime_paths.base_dir} を監視中", busy=False)

    def _reload_single_key(self, key: str, *, from_watch: bool) -> None:
        path = self.runtime_paths.path_for_key(key)
        try:
            if path.exists():
                text, encoding = read_text_with_fallback(path)
                normalized = text.replace("\r\n", "\n").replace("\r", "\n")
                if key in FIELD_ORDER:
                    normalized = normalize_input_text(key, normalized)
                else:
                    normalized = normalized.rstrip("\n")
                self.logger.log(f"[LOAD] key={key} encoding={encoding} path={path}")
            else:
                normalized = ""
        except Exception as exc:
            self.logger.log(f"[ERROR] reload failed: key={key} error={exc!r}")
            self.set_status("エラー", f"{path.name} 読込失敗: {exc!r}", busy=False, error=True)
            return

        signature = safe_signature(path)
        self.file_signatures[key] = signature

        if key == "result":
            if normalized != self.loaded_texts.get(key, ""):
                self.set_result_text(normalized)
                self.loaded_texts[key] = normalized
                if from_watch:
                    self.set_status("完了", "変換結果を更新しました", busy=False)
            return

        current_widget = normalize_input_text(key, self.get_widget_value(key))
        previous_loaded = self.loaded_texts.get(key, "")
        if key in self.dirty_fields and normalized != current_widget:
            self.pending_external_texts[key] = normalized
            pending = ", ".join(FIELD_LABELS[name] for name in sorted(self.pending_external_texts))
            self.set_notice(f"外部更新を保留中: {pending}")
            return

        if normalized != previous_loaded or normalized != current_widget:
            self.apply_widget_value(key, normalized)
            self.loaded_texts[key] = normalized
            if from_watch:
                self.set_status("待機中", f"{FIELD_LABELS[key]} を外部更新で反映しました", busy=False)

        self.pending_external_texts.pop(key, None)

    def get_widget_value(self, field: str) -> str:
        if field == "no":
            return self.no_var.get()
        widget = self.text_widgets[field]
        return widget.get("1.0", "end-1c")

    def apply_widget_value(self, field: str, text: str) -> None:
        self.is_applying_ui = True
        try:
            if field == "no":
                self.no_var.set(text)
            else:
                widget = self.text_widgets[field]
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
                widget.edit_modified(False)
        finally:
            self.is_applying_ui = False

    def set_result_text(self, text: str) -> None:
        if self.result_widget is None:
            return
        self.result_widget.configure(state="normal")
        self.result_widget.delete("1.0", "end")
        self.result_widget.insert("1.0", text)
        self.result_widget.configure(state="disabled")

    def get_result_text(self) -> str:
        if self.result_widget is None:
            return ""
        return self.result_widget.get("1.0", "end-1c")

    def schedule_async_pump(self) -> None:
        if self.async_after_id is not None:
            self.root.after_cancel(self.async_after_id)
        self.async_after_id = self.root.after(ASYNC_POLL_MS, self.process_async_events)

    def process_async_events(self) -> None:
        self.async_after_id = None
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break
            self.handle_async_event(item)
        self.schedule_async_pump()

    def handle_async_event(self, item: tuple) -> None:
        kind = item[0]
        if kind == "convert_done":
            _, mode, returncode, stdout, stderr, elapsed_ms = item
            self.active_mode = None
            self.enable_buttons(True)
            self._reload_single_key("result", from_watch=False)
            if returncode == 0:
                detail = f"{MODE_SPECS[mode]['label']} 完了 ({elapsed_ms} ms)"
                self.set_status("完了", detail, busy=False)
                self.set_notice(shorten_detail(stdout) if stdout else "")
                self.select_tab("result")
                self.focus_copy_button()
            else:
                combined = stdout.strip() or stderr.strip() or f"exit={returncode}"
                detail = f"{MODE_SPECS[mode]['label']} 失敗"
                self.set_status("エラー", detail, busy=False, error=True)
                self.set_notice(shorten_detail(combined))
                self.logger.log(
                    f"[ERROR] convert failed mode={mode} rc={returncode} stdout={stdout!r} stderr={stderr!r}"
                )

    def enable_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self.button_map.values():
            button.configure(state=state)

    def start_conversion(self, mode: str) -> None:
        if self.active_mode is not None:
            self.set_notice("変換は同時実行できません。")
            return

        missing = self.runtime_paths.validate_batches()
        if missing:
            joined = ", ".join(path.name for path in missing)
            self.set_status("エラー", f"既存 BAT 不足: {joined}", busy=False, error=True)
            return

        self.flush_save_now(reason="変換前保存")
        self.active_mode = mode
        self.enable_buttons(False)
        self.set_notice("")
        self.set_status(MODE_SPECS[mode]["status"], f"{MODE_SPECS[mode]['label']} を実行中", busy=True)

        worker = threading.Thread(
            target=self._run_conversion_worker,
            args=(mode,),
            daemon=True,
        )
        worker.start()

    def _run_conversion_worker(self, mode: str) -> None:
        batch_path = self.runtime_paths.batch_for_mode(mode)
        started = time.perf_counter()
        proc = subprocess.run(
            ["cmd.exe", "/c", str(batch_path)],
            cwd=str(self.runtime_paths.base_dir),
            capture_output=True,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        stdout_text, stdout_encoding = decode_console_bytes(proc.stdout or b"")
        stderr_text, stderr_encoding = decode_console_bytes(proc.stderr or b"")
        self.logger.log(
            f"[RUN] mode={mode} rc={proc.returncode} elapsed_ms={elapsed_ms} "
            f"stdout_encoding={stdout_encoding} stderr_encoding={stderr_encoding}"
        )
        self.queue.put(
            (
                "convert_done",
                mode,
                proc.returncode,
                stdout_text,
                stderr_text,
                elapsed_ms,
            )
        )

    def copy_result(self) -> None:
        text = self.get_result_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.set_status("完了", "変換結果をクリップボードへコピーしました", busy=False)

    def open_output_file(self) -> None:
        path = self.runtime_paths.result_path
        if not path.exists():
            self.set_status("エラー", f"{path.name} が見つかりません", busy=False, error=True)
            return
        os.startfile(path)
        self.set_status("待機中", f"{path.name} を開きました", busy=False)

    def on_close(self) -> None:
        try:
            self.logger.log(f"[LIFECYCLE] on_close pid={os.getpid()}")
            self.flush_save_now(reason="終了前保存")
            self.persist_settings()
        finally:
            self.root.destroy()


class SmokeTestRunner:
    def __init__(self, app: AvTextInputPadApp, runtime_dir: Path):
        self.app = app
        self.root = app.root
        self.runtime_dir = Path(runtime_dir)
        self.orig_bytes: dict[str, bytes | None] = {}
        self.orig_norm: dict[str, str] = {}
        self.temp_values: dict[str, str] = {}
        self.last_result_signature = FileSignature(False, 0, 0)
        self.failures: list[str] = []

    def start(self) -> None:
        for key, name in MONITORED_FILES.items():
            path = self.runtime_dir / name
            self.orig_bytes[key] = path.read_bytes() if path.exists() else None

        for field in FIELD_ORDER:
            current = self.app.loaded_texts.get(field, "")
            self.orig_norm[field] = current

        self.last_result_signature = safe_signature(self.runtime_dir / MONITORED_FILES["result"])

        stamp = time.strftime("%H%M%S")
        self.temp_values = {
            "title": f"AV Text 入力テスト {stamp}",
            "actress": f"GUIテスト女優 {stamp}",
            "no": "12",
        }
        self.root.after(200, self.step_edit_and_save)

    def fail(self, message: str) -> None:
        self.failures.append(message)
        self.finalize()

    def succeed(self) -> None:
        self.finalize()

    def step_edit_and_save(self) -> None:
        for field, text in self.temp_values.items():
            self.app.apply_widget_value(field, text)
            self.app.mark_dirty(field)
        wait_ms = self.app.settings.save_delay_ms + 900
        self.root.after(wait_ms, self.check_saved_files)

    def check_saved_files(self) -> None:
        for field, text in self.temp_values.items():
            path = self.runtime_dir / MONITORED_FILES[field]
            disk_text, _enc = read_text_with_fallback(path)
            normalized = normalize_input_text(field, disk_text)
            if normalized != normalize_input_text(field, text):
                self.fail(f"{field} save mismatch")
                return
        self.step_external_update()

    def step_external_update(self) -> None:
        external = {
            "title": "外部更新タイトル",
            "actress": "外部更新女優",
            "no": "34",
        }
        for field, text in external.items():
            write_input_file(self.runtime_dir / MONITORED_FILES[field], field, text)
        wait_ms = self.app.settings.watch_interval_ms + RELOAD_DEBOUNCE_MS + 900
        self.root.after(wait_ms, self.check_external_reflection)

    def check_external_reflection(self) -> None:
        expected = {
            "title": "外部更新タイトル",
            "actress": "外部更新女優",
            "no": "34",
        }
        for field, text in expected.items():
            current = normalize_input_text(field, self.app.get_widget_value(field))
            if current != normalize_input_text(field, text):
                self.fail(f"{field} external reflection mismatch")
                return

        for field, text in self.orig_norm.items():
            self.app.apply_widget_value(field, text)
            self.app.mark_dirty(field)

        wait_ms = self.app.settings.save_delay_ms + 900
        self.root.after(wait_ms, lambda: self.start_conversion_and_wait("title_and_actress", self.check_title_and_actress))

    def start_conversion_and_wait(self, mode: str, callback) -> None:
        self.last_result_signature = safe_signature(self.runtime_dir / MONITORED_FILES["result"])
        self.app.start_conversion(mode)
        self.wait_until(
            lambda: self.app.active_mode is None,
            callback,
            timeout_ms=30000,
            timeout_message=f"{mode} timeout",
        )

    def wait_until(self, predicate, callback, *, timeout_ms: int, timeout_message: str) -> None:
        started = time.monotonic()

        def _poll() -> None:
            if predicate():
                callback()
                return
            if (time.monotonic() - started) * 1000 >= timeout_ms:
                self.fail(timeout_message)
                return
            self.root.after(120, _poll)

        _poll()

    def check_result_updated(self, mode: str) -> bool:
        result_sig = safe_signature(self.runtime_dir / MONITORED_FILES["result"])
        if not result_sig.exists:
            self.fail(f"{mode} result missing")
            return False
        if result_sig == self.last_result_signature:
            self.fail(f"{mode} result signature unchanged")
            return False
        result_text = self.app.get_result_text().strip()
        if not result_text:
            self.fail(f"{mode} result empty")
            return False
        return True

    def check_copy_button_focus(self, mode: str) -> bool:
        copy_button = self.app.button_map.get("copy")
        if copy_button is None:
            self.fail(f"{mode} copy button missing")
            return False
        focused = self.root.focus_get()
        if focused != copy_button:
            self.fail(f"{mode} copy focus missing")
            return False
        return True

    def check_notice_text(self, mode: str) -> bool:
        notice = self.app.notice_var.get().strip()
        if not notice:
            self.fail(f"{mode} notice empty")
            return False
        if ("変換完了:" not in notice) and ("出力完了:" not in notice):
            self.fail(f"{mode} notice unexpected")
            return False
        if "�" in notice:
            self.fail(f"{mode} notice mojibake")
            return False
        return True

    def check_title_and_actress(self) -> None:
        if not self.check_result_updated("title_and_actress"):
            return
        if not self.check_copy_button_focus("title_and_actress"):
            return
        if not self.check_notice_text("title_and_actress"):
            return
        self.start_conversion_and_wait("title_only", self.check_title_only)

    def check_title_only(self) -> None:
        if not self.check_result_updated("title_only"):
            return
        if not self.check_copy_button_focus("title_only"):
            return
        if not self.check_notice_text("title_only"):
            return
        self.start_conversion_and_wait("no_title", self.check_no_title)

    def check_no_title(self) -> None:
        if not self.check_result_updated("no_title"):
            return
        if not self.check_copy_button_focus("no_title"):
            return
        if not self.check_notice_text("no_title"):
            return
        self.app.copy_result()
        self.root.after(300, self.check_clipboard)

    def check_clipboard(self) -> None:
        try:
            clip = self.root.clipboard_get()
        except Exception as exc:
            self.fail(f"clipboard read failed: {exc!r}")
            return
        if clip.strip() != self.app.get_result_text().strip():
            self.fail("clipboard mismatch")
            return
        self.succeed()

    def finalize(self) -> None:
        try:
            for field, text in self.orig_norm.items():
                self.app.apply_widget_value(field, text)
            self.app.dirty_fields.clear()

            for key, raw in self.orig_bytes.items():
                path = self.runtime_dir / MONITORED_FILES[key]
                if raw is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as f:
                    f.write(raw)
            self.app._reload_all_from_disk(reason="スモークテスト後復元")
        finally:
            exit_code = 0 if not self.failures else 1
            if self.failures:
                self.app.logger.log(f"[SMOKE] failed: {'; '.join(self.failures)}")
            else:
                self.app.logger.log("[SMOKE] success")
            setattr(self.root, "_smoke_exit_code", exit_code)
            self.root.after(300, self.root.quit)
            self.root.after(350, self.root.destroy)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--runtime-dir", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))

    settings_dir = settings_home()
    logger = SimpleLogger(settings_dir / "logs" / "avtext_input_pad.log")
    store = SettingsStore(settings_dir / "settings.json")
    logger.log(f"[LIFECYCLE] process start pid={os.getpid()}")

    root = tk.Tk()
    app = AvTextInputPadApp(root, store, logger)
    app.start()
    logger.log(f"[LIFECYCLE] mainloop start pid={os.getpid()}")

    if args.runtime_dir:
        app.runtime_dir_var.set(args.runtime_dir)
        app.apply_runtime_dir(force_reload=True)

    if args.smoke_test:
        runner = SmokeTestRunner(app, Path(args.runtime_dir or app.runtime_paths.base_dir))
        root.after(250, runner.start)
        root.mainloop()
        logger.log(f"[LIFECYCLE] mainloop end pid={os.getpid()} smoke=1")
        return int(getattr(root, "_smoke_exit_code", 0))

    root.mainloop()
    logger.log(f"[LIFECYCLE] mainloop end pid={os.getpid()} smoke=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
