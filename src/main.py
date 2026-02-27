#!/usr/bin/env python3
"""
Shellman - TUI File Manager built with Textual.
Cross-platform: works on Windows, macOS, and Linux.

Install dependencies:
    pip install textual

Run:
    python main.py
"""

import os
import shutil
import stat
import platform
import subprocess
import zipfile
import tarfile
from datetime import datetime
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TextArea,
)


# ─────────────────────────── Constants ────────────────────────────

TRASH_DIR = Path.home() / ".shellman_trash"
SORT_MODES = ["name", "size", "modified", "type"]
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tar.gz", ".tar.bz2"}


# ─────────────────────────── Helpers ────────────────────────────

def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def file_permissions(path: Path) -> str:
    try:
        mode = path.stat().st_mode
        return stat.filemode(mode)
    except Exception:
        return "----------"


def file_modified(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def is_archive(path: Path) -> bool:
    """Check if a file is an extractable archive."""
    name = path.name.lower()
    return (
        name.endswith(".zip")
        or name.endswith(".tar")
        or name.endswith(".tar.gz")
        or name.endswith(".tgz")
        or name.endswith(".tar.bz2")
        or name.endswith(".tar.xz")
        or name.endswith(".gz")
        or name.endswith(".bz2")
    )


def open_with_default(path: Path) -> str | None:
    """Open a file with the OS default application. Returns error string or None."""
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return None
    except Exception as e:
        return str(e)


def get_git_status(directory: Path) -> dict[str, str]:
    """
    Run git status --porcelain in directory.
    Returns dict mapping top-level name -> single-char code:
      M = modified, A = added/staged, ? = untracked, D = deleted, R = renamed
    Returns empty dict if not a git repo or git unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return {}
        status_map: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            xy = line[:2]
            filepath = line[3:].strip()
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1]
            name = Path(filepath).parts[0] if Path(filepath).parts else filepath
            x, y = xy[0], xy[1]
            if xy.strip() == "??":
                code = "?"
            elif x in "A" or y == "A":
                code = "A"
            elif x == "M" or y == "M":
                code = "M"
            elif x == "D" or y == "D":
                code = "D"
            elif x == "R" or y == "R":
                code = "R"
            else:
                code = "~"
            status_map[name] = code
        return status_map
    except Exception:
        return {}


def disk_usage_str(path: Path) -> str:
    """Return short disk usage string for the drive containing path."""
    try:
        usage = shutil.disk_usage(path)
        used = human_size(usage.used)
        total = human_size(usage.total)
        pct = usage.used / usage.total * 100
        return f"  |  Disk: {used}/{total} ({pct:.0f}%)"
    except Exception:
        return ""


# ─────────────────────────── Undo Stack ────────────────────────────

class UndoStack:
    """Stores reversible file operations as (description, callable) pairs."""

    def __init__(self):
        self._stack: list[tuple[str, object]] = []

    def push(self, description: str, undo_fn) -> None:
        self._stack.append((description, undo_fn))

    def pop(self) -> "tuple[str, object] | None":
        return self._stack.pop() if self._stack else None

    def peek(self) -> "str | None":
        return self._stack[-1][0] if self._stack else None

    def clear(self) -> None:
        self._stack.clear()


# ──────────────────────────── Modals ────────────────────────────

class InputModal(ModalScreen):
    """Generic single-input modal."""

    CSS = """
    InputModal { align: center middle; }
    InputModal > Vertical {
        background: $surface; border: thick $primary;
        padding: 2 4; width: 60; height: auto;
    }
    InputModal Label { margin-bottom: 1; }
    InputModal Input { margin-bottom: 1; }
    InputModal Horizontal { height: auto; align: right middle; }
    InputModal Button { margin-left: 1; }
    """

    def __init__(self, title: str, placeholder: str = "", default: str = ""):
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title)
            yield Input(value=self._default, placeholder=self._placeholder, id="modal_input")
            with Horizontal():
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#modal_input", Input).focus()

    @on(Button.Pressed, "#ok")
    def confirm(self) -> None:
        self.dismiss(self.query_one("#modal_input", Input).value.strip())

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self) -> None:
        self.confirm()


class ConfirmModal(ModalScreen):
    """Yes / No confirmation modal."""

    CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > Vertical {
        background: $surface; border: thick $error;
        padding: 2 4; width: 60; height: auto;
    }
    ConfirmModal Label { margin-bottom: 1; text-style: bold; }
    ConfirmModal Horizontal { height: auto; align: right middle; }
    ConfirmModal Button { margin-left: 1; }
    """

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._message)
            with Horizontal():
                yield Button("Yes", variant="error", id="yes")
                yield Button("No", variant="default", id="no")

    @on(Button.Pressed, "#yes")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def cancel(self) -> None:
        self.dismiss(False)


class InfoModal(ModalScreen):
    """Display info about a file."""

    CSS = """
    InfoModal { align: center middle; }
    InfoModal > Vertical {
        background: $surface; border: thick $primary;
        padding: 2 4; width: 70; height: auto;
    }
    InfoModal Static { margin-bottom: 1; }
    InfoModal Button { margin-top: 1; }
    """

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        p = self._path
        try:
            st = p.stat()
            size = human_size(st.st_size) if p.is_file() else "-"
            created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
            modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            perms = file_permissions(p)
        except Exception as e:
            size = created = modified = perms = str(e)

        info = (
            f"Name:     {p.name}\n"
            f"Path:     {p}\n"
            f"Type:     {'Directory' if p.is_dir() else 'File'}\n"
            f"Size:     {size}\n"
            f"Perms:    {perms}\n"
            f"Created:  {created}\n"
            f"Modified: {modified}"
        )
        with Vertical():
            yield Label(f"ℹ  File Info: {p.name}")
            yield Static(info)
            yield Button("Close", variant="primary", id="close")

    @on(Button.Pressed, "#close")
    def close(self) -> None:
        self.dismiss(None)


class HelpModal(ModalScreen):
    """Full shortcut reference — press ? to open."""

    CSS = """
    HelpModal { align: center middle; }
    HelpModal > Vertical {
        background: $surface; border: thick $primary;
        padding: 1 3; width: 64; height: auto; max-height: 90%;
    }
    HelpModal #help_title {
        text-style: bold; margin-bottom: 1; color: $accent;
    }
    HelpModal Static {
        margin-bottom: 1;
    }
    HelpModal Button { margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "dismiss_help", "Close")]

    def compose(self) -> ComposeResult:
        shortcuts = [
            ("Navigation",   [
                ("Enter",       "Open directory"),
                ("Backspace",   "Go up one level"),
                ("Ctrl+L",      "Go to path"),
                ("H",           "Toggle hidden files"),
                ("F5",          "Refresh"),
            ]),
            ("Selection",    [
                ("Space",       "Select / deselect item"),
            ]),
            ("File Actions", [
                ("N",           "New file"),
                ("D",           "New directory"),
                ("R",           "Rename"),
                ("X",           "Delete (moved to trash)"),
                ("C",           "Copy"),
                ("T",           "Cut"),
                ("V",           "Paste"),
                ("U",           "Undo last operation"),
            ]),
            ("View",         [
                ("S",           "Cycle sort (name/size/modified/type)"),
                ("/",           "Filter files"),
                ("Escape",      "Clear filter"),
            ]),
            ("File Tools",   [
                ("E",           "Edit file"),
                ("O",           "Open with default app"),
                ("Z",           "Zip selected  /  Extract archive"),
                ("I",           "File info"),
            ]),
            ("Editor",       [
                ("Ctrl+S",      "Save file"),
                ("Escape",      "Close editor without saving"),
            ]),
            ("App",          [
                ("?",           "Show this help"),
                ("Q",           "Quit"),
            ]),
        ]

        lines = []
        for section, items in shortcuts:
            lines.append(f"[bold $accent]{section}[/]")
            for key, desc in items:
                lines.append(f"  [bold]{key:<12}[/]  {desc}")
            lines.append("")

        with Vertical():
            yield Label("Shellman — Keyboard Shortcuts", id="help_title")
            yield Static("\n".join(lines))
            yield Button("Close  (Esc)", variant="primary", id="close_help")

    def action_dismiss_help(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#close_help")
    def close(self) -> None:
        self.dismiss(None)


class EditModal(ModalScreen):
    """Full-screen file editor using TextArea."""

    CSS = """
    EditModal { align: center middle; }
    EditModal > Vertical {
        background: $surface; border: thick $accent;
        padding: 0; width: 95%; height: 95%;
    }
    EditModal #editor_title {
        background: $accent-darken-2; color: $text;
        text-style: bold; padding: 0 2; height: 1;
    }
    EditModal #editor_hint {
        background: $surface-darken-1; color: $text-muted;
        padding: 0 2; height: 1;
    }
    EditModal TextArea { height: 1fr; border: none; }
    EditModal #editor_buttons { height: auto; align: right middle; padding: 0 1; }
    EditModal Button { margin-left: 1; }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "close_editor", "Close"),
    ]

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        suffix = self._path.suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "javascript",
            ".html": "html", ".css": "css", ".json": "json",
            ".md": "markdown", ".yaml": "yaml", ".yml": "yaml",
            ".toml": "toml", ".bash": "bash", ".sh": "bash",
            ".rs": "rust", ".go": "go", ".c": "c", ".cpp": "cpp",
            ".sql": "sql", ".xml": "xml",
        }
        language = lang_map.get(suffix)
        try:
            content = self._path.read_text(errors="replace")
        except Exception as e:
            content = f"# Error reading file: {e}"

        with Vertical():
            yield Static(f"✏  Editing: {self._path}", id="editor_title")
            yield Static("  Ctrl+S = Save   Esc = Close without saving", id="editor_hint")
            if language:
                yield TextArea(content, language=language, id="editor_area", show_line_numbers=True)
            else:
                yield TextArea(content, id="editor_area", show_line_numbers=True)
            with Horizontal(id="editor_buttons"):
                yield Button("💾 Save  Ctrl+S", variant="success", id="save_btn")
                yield Button("✖ Close  Esc", variant="default", id="close_btn")

    def on_mount(self) -> None:
        self.query_one("#editor_area", TextArea).focus()

    def _do_save(self) -> bool:
        content = self.query_one("#editor_area", TextArea).text
        try:
            self._path.write_text(content)
            return True
        except Exception as e:
            self.dismiss(f"⚠  Save error: {e}")
            return False

    def action_save(self) -> None:
        if self._do_save():
            self.dismiss(f"✔  Saved: {self._path.name}")

    def action_close_editor(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save_btn")
    def on_save_pressed(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#close_btn")
    def on_close_pressed(self) -> None:
        self.action_close_editor()


# ───────────────────────── Status bar ───────────────────────────

class StatusBar(Static):
    message = reactive("")

    def render(self) -> str:
        return self.message


# ──────────────────────── Main App ──────────────────────────────

class FileManagerApp(App):
    """Shellman — TUI File Manager."""

    TITLE = "Shellman"
    SUB_TITLE = platform.system()

    CSS = """
    Screen { layout: vertical; }

    #main_container { layout: horizontal; height: 1fr; }

    #tree_panel {
        width: 30%; min-width: 20;
        border-right: solid $primary-darken-2;
        overflow: auto;
    }

    #right_panel { width: 1fr; layout: vertical; }

    #path_bar {
        height: 1; background: $primary-darken-3;
        color: $text; padding: 0 1; text-style: bold;
    }

    #filter_bar {
        height: 3; display: none;
        background: $surface; padding: 0 1;
    }

    #filter_bar.visible { display: block; }

    #sort_bar {
        height: 1; background: $surface-darken-2;
        color: $text-muted; padding: 0 1;
    }

    #file_table { height: 1fr; }

    #status_bar {
        height: 1; background: $surface-darken-1;
        color: $text-muted; padding: 0 1;
    }

    DirectoryTree { padding: 0; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new_file", "New File"),
        Binding("d", "new_dir", "New Dir"),
        Binding("r", "rename", "Rename"),
        Binding("x", "delete", "Delete"),
        Binding("c", "copy_item", "Copy"),
        Binding("t", "cut_item", "Cut"),
        Binding("v", "paste_item", "Paste"),
        Binding("e", "edit_file", "Edit"),
        Binding("o", "open_default", "Open"),
        Binding("i", "file_info", "Info"),
        Binding("h", "toggle_hidden", "Hidden"),
        Binding("z", "archive", "Archive"),
        Binding("u", "undo", "Undo"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("slash", "toggle_filter", "Search"),
        Binding("escape", "clear_filter", "Clear Search"),
        Binding("question_mark", "show_help", "Help"),
        Binding("f5", "refresh", "Refresh"),
        Binding("ctrl+l", "goto", "Go to Path"),
        Binding("backspace", "go_up", "Go Up"),
    ]

    current_dir: reactive[Path] = reactive(Path.home(), init=False)
    show_hidden: reactive[bool] = reactive(False, init=False)
    clipboard: reactive[Path | None] = reactive(None, init=False)
    clipboard_op: reactive[str] = reactive("copy")
    sort_mode: reactive[str] = reactive("name", init=False)
    filter_text: reactive[str] = reactive("", init=False)

    def __init__(self):
        super().__init__()
        self._row_entries: list[Path] = []
        self._selected: set[Path] = set()
        self._undo = UndoStack()
        self._git_status: dict[str, str] = {}
        self._filter_visible = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main_container"):
            with Vertical(id="tree_panel"):
                yield DirectoryTree(str(Path.home()), id="dir_tree")
            with Vertical(id="right_panel"):
                yield Static("", id="path_bar")
                yield Static("", id="sort_bar")
                yield Input(placeholder="Filter files... (Esc to clear)", id="filter_input")
                yield DataTable(id="file_table", cursor_type="row", zebra_stripes=True)
        yield StatusBar("", id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#file_table", DataTable)
        table.add_columns(" ", "G", " ", "Name", "Size", "Modified", "Permissions")
        # Hide filter bar initially
        self.query_one("#filter_input", Input).display = False
        self.current_dir = Path.home()

    # ──────────── Reactive watchers ────────────

    def watch_current_dir(self, new_dir: Path) -> None:
        self._selected.clear()
        self._git_status = get_git_status(new_dir)
        self.query_one("#path_bar", Static).update(f" 📂  {new_dir}")
        self.refresh_table()
        try:
            tree = self.query_one("#dir_tree", DirectoryTree)
            tree.path = str(new_dir)
        except Exception:
            pass

    def watch_clipboard(self, path: Path | None) -> None:
        if path:
            op = "✂ Cut" if self.clipboard_op == "cut" else "📋 Copied"
            self.set_status(f"{op}: {path.name}  — press [V] to paste")

    def watch_sort_mode(self, mode: str) -> None:
        self.query_one("#sort_bar", Static).update(
            f" Sort: {mode}  (press S to cycle)  |  Space = select  |  / = filter"
        )
        self.refresh_table()

    def watch_filter_text(self, text: str) -> None:
        self.refresh_table()

    # ──────────── UI helpers ────────────

    def set_status(self, msg: str) -> None:
        self.query_one("#status_bar", StatusBar).message = msg

    def _sort_entries(self, entries: list[Path]) -> list[Path]:
        mode = self.sort_mode
        if mode == "name":
            return sorted(entries, key=lambda p: (not p.is_dir(), p.name.lower()))
        elif mode == "size":
            def _size(p: Path) -> int:
                try:
                    return p.stat().st_size if p.is_file() else 0
                except Exception:
                    return 0
            return sorted(entries, key=lambda p: (not p.is_dir(), _size(p)))
        elif mode == "modified":
            def _mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except Exception:
                    return 0.0
            return sorted(entries, key=lambda p: (not p.is_dir(), -_mtime(p)))
        elif mode == "type":
            return sorted(entries, key=lambda p: (not p.is_dir(), p.suffix.lower(), p.name.lower()))
        return entries

    def refresh_table(self) -> None:
        table = self.query_one("#file_table", DataTable)
        table.clear()
        try:
            raw_entries = list(self.current_dir.iterdir())
        except PermissionError:
            self.set_status("⚠  Permission denied")
            return

        entries = self._sort_entries(raw_entries)

        # Apply hidden filter
        if not self.show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        # Apply text filter
        if self.filter_text:
            entries = [e for e in entries if self.filter_text.lower() in e.name.lower()]

        self._row_entries = []
        for entry in entries:
            # Selection indicator
            sel = "●" if entry in self._selected else " "

            # Git status
            git = self._git_status.get(entry.name, " ")

            icon = "📁" if entry.is_dir() else self._file_icon(entry)
            try:
                size = "-" if entry.is_dir() else human_size(entry.stat().st_size) if entry.exists() else "?"
            except (OSError, PermissionError):
                size = "?"
            modified = file_modified(entry)
            perms = file_permissions(entry)
            table.add_row(sel, git, icon, entry.name, size, modified, perms)
            self._row_entries.append(entry)

        count = len(self._row_entries)
        sel_count = len(self._selected)
        sel_note = f"  ({sel_count} selected)" if sel_count else ""
        filter_note = f"  [filter: '{self.filter_text}']" if self.filter_text else ""
        hidden_note = "" if self.show_hidden else "  (hidden excluded)"
        undo_note = f"  [undo: {self._undo.peek()}]" if self._undo.peek() else ""
        disk = disk_usage_str(self.current_dir)
        self.set_status(
            f"{count} items{sel_note}{filter_note}{hidden_note}{undo_note}{disk}"
        )

    def _file_icon(self, path: Path) -> str:
        suffix = path.suffix.lower()
        icons = {
            ".py": "🐍", ".js": "🟨", ".ts": "🔷", ".html": "🌐", ".css": "🎨",
            ".json": "📋", ".md": "📝", ".txt": "📄", ".pdf": "📕",
            ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".gif": "🖼", ".svg": "🖼",
            ".mp3": "🎵", ".wav": "🎵", ".flac": "🎵",
            ".mp4": "🎬", ".mkv": "🎬", ".avi": "🎬",
            ".zip": "🗜", ".tar": "🗜", ".gz": "🗜", ".rar": "🗜",
            ".exe": "⚙", ".sh": "⚙", ".bat": "⚙",
            ".db": "🗄", ".sqlite": "🗄",
            ".rs": "🦀", ".go": "🐹", ".c": "🔧", ".cpp": "🔧",
        }
        return icons.get(suffix, "📄")

    def selected_entry(self) -> "Path | None":
        table = self.query_one("#file_table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0 or table.row_count == 0:
            return None
        try:
            return self._row_entries[row_idx]
        except (IndexError, AttributeError):
            return None

    def _effective_targets(self) -> list[Path]:
        """Return selected paths if any, otherwise just the cursor row entry."""
        if self._selected:
            return list(self._selected)
        entry = self.selected_entry()
        return [entry] if entry else []

    # ──────────── Key handler for Space (bulk select) ────────────

    def on_key(self, event) -> None:
        if event.key == "space":
            table = self.query_one("#file_table", DataTable)
            if table.has_focus:
                entry = self.selected_entry()
                if entry:
                    if entry in self._selected:
                        self._selected.discard(entry)
                    else:
                        self._selected.add(entry)
                    self.refresh_table()
                    # Move cursor down
                    if table.cursor_row < table.row_count - 1:
                        table.move_cursor(row=table.cursor_row + 1)
                event.stop()

    # ──────────── Tree navigation ────────────

    @on(DirectoryTree.DirectorySelected)
    def on_dir_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.current_dir = Path(str(event.path))

    # ──────────── Table navigation ────────────

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        entry = self.selected_entry()
        if entry and entry.is_dir():
            self.current_dir = entry

    # ──────────── Filter input ────────────

    @on(Input.Changed, "#filter_input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value

    @on(Input.Submitted, "#filter_input")
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        # Return focus to table after confirming filter
        self.query_one("#file_table", DataTable).focus()

    # ──────────── Actions ────────────

    def action_show_help(self) -> None:
        self.push_screen(HelpModal())

    def action_go_up(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            self.current_dir = parent

    def action_refresh(self) -> None:
        self._git_status = get_git_status(self.current_dir)
        self.refresh_table()
        self.set_status("Refreshed.")

    def action_toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.refresh_table()

    def action_cycle_sort(self) -> None:
        idx = SORT_MODES.index(self.sort_mode)
        self.sort_mode = SORT_MODES[(idx + 1) % len(SORT_MODES)]
        self.set_status(f"Sort: {self.sort_mode}")

    def action_toggle_filter(self) -> None:
        fi = self.query_one("#filter_input", Input)
        if fi.display:
            fi.display = False
            self.filter_text = ""
            fi.value = ""
            self.query_one("#file_table", DataTable).focus()
        else:
            fi.display = True
            fi.focus()

    def action_clear_filter(self) -> None:
        fi = self.query_one("#filter_input", Input)
        if fi.display:
            fi.display = False
            self.filter_text = ""
            fi.value = ""
            self.query_one("#file_table", DataTable).focus()

    def action_goto(self) -> None:
        def handle(result: str | None) -> None:
            if result:
                p = Path(result).expanduser()
                if p.is_dir():
                    self.current_dir = p
                else:
                    self.set_status(f"⚠  Not a directory: {result}")

        self.push_screen(InputModal("Go to Path:", placeholder="/path/to/dir", default=str(self.current_dir)), handle)

    def action_new_file(self) -> None:
        def handle(result: str | None) -> None:
            if result:
                target = self.current_dir / result
                try:
                    target.touch(exist_ok=False)
                    self.refresh_table()
                    self.set_status(f"✔  Created file: {result}")
                    # Undo: delete the new file
                    self._undo.push(f"create {result}", lambda t=target: t.unlink(missing_ok=True))
                except FileExistsError:
                    self.set_status(f"⚠  File already exists: {result}")
                except Exception as e:
                    self.set_status(f"⚠  Error: {e}")

        self.push_screen(InputModal("New File Name:"), handle)

    def action_new_dir(self) -> None:
        def handle(result: str | None) -> None:
            if result:
                target = self.current_dir / result
                try:
                    target.mkdir(parents=False, exist_ok=False)
                    self.refresh_table()
                    self.set_status(f"✔  Created directory: {result}")
                    # Undo: remove the new directory
                    self._undo.push(f"mkdir {result}", lambda t=target: t.rmdir())
                except FileExistsError:
                    self.set_status(f"⚠  Directory already exists: {result}")
                except Exception as e:
                    self.set_status(f"⚠  Error: {e}")

        self.push_screen(InputModal("New Directory Name:"), handle)

    def action_rename(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return

        def handle(result: str | None) -> None:
            if result and result != entry.name:
                target = self.current_dir / result
                try:
                    entry.rename(target)
                    self.refresh_table()
                    self.set_status(f"✔  Renamed to: {result}")
                    # Undo: rename back
                    self._undo.push(f"rename {entry.name}", lambda t=target, o=entry: t.rename(o))
                except Exception as e:
                    self.set_status(f"⚠  Error: {e}")

        self.push_screen(InputModal("Rename to:", default=entry.name), handle)

    def action_delete(self) -> None:
        targets = self._effective_targets()
        if not targets:
            self.set_status("⚠  No item selected.")
            return

        label = targets[0].name if len(targets) == 1 else f"{len(targets)} items"

        def handle(confirmed: bool) -> None:
            if confirmed:
                TRASH_DIR.mkdir(parents=True, exist_ok=True)
                undo_moves: list[tuple[Path, Path]] = []
                for entry in targets:
                    try:
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        trash_path = TRASH_DIR / f"{ts}_{entry.name}"
                        shutil.move(str(entry), str(trash_path))
                        undo_moves.append((trash_path, entry))
                    except Exception as e:
                        self.set_status(f"⚠  Error deleting {entry.name}: {e}")
                        return
                self._selected.clear()
                self.refresh_table()
                self.set_status(f"✔  Deleted: {label}  (press U to undo)")

                def _undo_delete(moves=undo_moves):
                    for trash_path, original in moves:
                        shutil.move(str(trash_path), str(original))

                self._undo.push(f"delete {label}", _undo_delete)

        self.push_screen(
            ConfirmModal(f"Delete {label}?\nItems are moved to ~/.shellman_trash and can be undone."),
            handle,
        )

    def action_copy_item(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        self.clipboard = entry
        self.clipboard_op = "copy"

    def action_cut_item(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        self.clipboard = entry
        self.clipboard_op = "cut"
        self.set_status(f"✂  Cut: {entry.name}  — navigate to destination and press V to move")

    def action_paste_item(self) -> None:
        if not self.clipboard:
            self.set_status("⚠  Clipboard is empty. Use [C] to copy or [T] to cut first.")
            return
        src = self.clipboard
        dst = self.current_dir / src.name
        if dst == src:
            self.set_status("⚠  Source and destination are the same.")
            return
        try:
            if self.clipboard_op == "cut":
                shutil.move(str(src), str(dst))
                original_src = src
                self.clipboard = None
                self.set_status(f"✔  Moved: {src.name}")
                # Undo: move back
                self._undo.push(f"move {src.name}", lambda d=dst, o=original_src: shutil.move(str(d), str(o)))
            else:
                if src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
                self.set_status(f"✔  Copied: {src.name}")
                # Undo: delete the copy
                self._undo.push(
                    f"copy {src.name}",
                    lambda d=dst: shutil.rmtree(str(d)) if d.is_dir() else d.unlink(missing_ok=True),
                )
            self.refresh_table()
        except Exception as e:
            self.set_status(f"⚠  Error: {e}")

    def action_undo(self) -> None:
        op = self._undo.pop()
        if not op:
            self.set_status("⚠  Nothing to undo.")
            return
        description, undo_fn = op
        try:
            undo_fn()
            self.refresh_table()
            self.set_status(f"↩  Undone: {description}")
        except Exception as e:
            self.set_status(f"⚠  Undo failed: {e}")

    def action_file_info(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        self.push_screen(InfoModal(entry))

    def action_edit_file(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        if entry.is_dir():
            self.set_status("⚠  Cannot edit a directory.")
            return

        def handle(result: str | None) -> None:
            if result:
                self.set_status(result)
                self.refresh_table()

        self.push_screen(EditModal(entry), handle)

    def action_open_default(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        err = open_with_default(entry)
        if err:
            self.set_status(f"⚠  Could not open: {err}")
        else:
            self.set_status(f"✔  Opened: {entry.name}")

    def action_archive(self) -> None:
        entry = self.selected_entry()
        targets = self._effective_targets()

        # If cursor is on a single archive file and nothing is selected → extract
        if entry and is_archive(entry) and not self._selected:
            self._extract_archive(entry)
            return

        # Otherwise zip the targets (or the cursor entry if no selection)
        if not targets:
            self.set_status("⚠  No items selected to zip. Use Space to select files.")
            return

        def handle(result: str | None) -> None:
            if not result:
                return
            name = result if result.endswith(".zip") else result + ".zip"
            out_path = self.current_dir / name
            try:
                with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for t in targets:
                        if t.is_dir():
                            for f in t.rglob("*"):
                                zf.write(f, f.relative_to(t.parent))
                        else:
                            zf.write(t, t.name)
                self._selected.clear()
                self.refresh_table()
                self.set_status(f"✔  Created archive: {name}")
                # Undo: delete the zip
                self._undo.push(f"zip {name}", lambda p=out_path: p.unlink(missing_ok=True))
            except Exception as e:
                self.set_status(f"⚠  Archive error: {e}")

        default_name = targets[0].stem if len(targets) == 1 else "archive"
        self.push_screen(InputModal("Archive name:", default=default_name), handle)

    def _extract_archive(self, path: Path) -> None:
        dest = self.current_dir / path.stem
        try:
            name = path.name.lower()
            if name.endswith(".zip"):
                with zipfile.ZipFile(path, "r") as zf:
                    zf.extractall(dest)
            elif name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
                with tarfile.open(path, "r:*") as tf:
                    tf.extractall(dest)
            elif name.endswith(".gz"):
                import gzip
                dest = self.current_dir / path.stem
                with gzip.open(path, "rb") as gz, open(dest, "wb") as out:
                    shutil.copyfileobj(gz, out)
            else:
                self.set_status(f"⚠  Unsupported archive format: {path.suffix}")
                return
            self.refresh_table()
            self.set_status(f"✔  Extracted: {path.name}  →  {dest.name}")
            # Undo: delete extracted output
            self._undo.push(
                f"extract {path.name}",
                lambda d=dest: shutil.rmtree(str(d)) if d.is_dir() else d.unlink(missing_ok=True),
            )
        except Exception as e:
            self.set_status(f"⚠  Extraction error: {e}")


if __name__ == "__main__":
    FileManagerApp().run()