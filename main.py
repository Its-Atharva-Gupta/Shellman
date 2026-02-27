#!/usr/bin/env python3
"""
TUI File Manager built with Textual.
Cross-platform: works on Windows, macOS, and Linux.

Install dependencies:
    pip install textual

Run:
    python file_manager.py
"""

import os
import shutil
import stat
import platform
from datetime import datetime
from pathlib import Path

from textual import on, work
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
from textual.coordinate import Coordinate


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


# ──────────────────────────── Modals ────────────────────────────

class InputModal(ModalScreen):
    """Generic single-input modal."""

    CSS = """
    InputModal {
        align: center middle;
    }
    InputModal > Vertical {
        background: $surface;
        border: thick $primary;
        padding: 2 4;
        width: 60;
        height: auto;
    }
    InputModal Label {
        margin-bottom: 1;
    }
    InputModal Input {
        margin-bottom: 1;
    }
    InputModal Horizontal {
        height: auto;
        align: right middle;
    }
    InputModal Button {
        margin-left: 1;
    }
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
        value = self.query_one("#modal_input", Input).value.strip()
        self.dismiss(value)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self) -> None:
        self.confirm()


class ConfirmModal(ModalScreen):
    """Yes / No confirmation modal."""

    CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        background: $surface;
        border: thick $error;
        padding: 2 4;
        width: 60;
        height: auto;
    }
    ConfirmModal Label {
        margin-bottom: 1;
        text-style: bold;
    }
    ConfirmModal Horizontal {
        height: auto;
        align: right middle;
    }
    ConfirmModal Button {
        margin-left: 1;
    }
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
    InfoModal {
        align: center middle;
    }
    InfoModal > Vertical {
        background: $surface;
        border: thick $primary;
        padding: 2 4;
        width: 70;
        height: auto;
    }
    InfoModal Static {
        margin-bottom: 1;
    }
    InfoModal Button {
        margin-top: 1;
    }
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


# ──────────────────────────── Editor Modal ──────────────────────────────

class EditModal(ModalScreen):
    """Full-screen file editor using TextArea."""

    CSS = """
    EditModal {
        align: center middle;
    }
    EditModal > Vertical {
        background: $surface;
        border: thick $accent;
        padding: 0;
        width: 95%;
        height: 95%;
    }
    EditModal #editor_title {
        background: $accent-darken-2;
        color: $text;
        text-style: bold;
        padding: 0 2;
        height: 1;
    }
    EditModal #editor_hint {
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 2;
        height: 1;
    }
    EditModal TextArea {
        height: 1fr;
        border: none;
    }
    EditModal #editor_buttons {
        height: auto;
        align: right middle;
        padding: 0 1;
    }
    EditModal Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "close_editor", "Close"),
    ]

    def __init__(self, path: Path):
        super().__init__()
        self._path = path
        self._original: str = ""

    def compose(self) -> ComposeResult:
        # Detect language for syntax highlighting
        suffix = self._path.suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "javascript",
            ".html": "html", ".css": "css", ".json": "json",
            ".md": "markdown", ".yaml": "yaml", ".yml": "yaml",
            ".toml": "toml", ".bash": "bash", ".sh": "bash",
            ".rs": "rust", ".go": "go", ".c": "c", ".cpp": "cpp",
            ".sql": "sql", ".xml": "xml",
        }
        language = lang_map.get(suffix, None)

        try:
            content = self._path.read_text(errors="replace")
        except Exception as e:
            content = f"# Error reading file: {e}"
        self._original = content

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

    # ── save helper ──

    def _do_save(self) -> bool:
        """Write content to disk. Returns True on success."""
        content = self.query_one("#editor_area", TextArea).text
        try:
            self._path.write_text(content)
            return True
        except Exception as e:
            # Bubble the error message back to the app via dismiss value
            self.dismiss(f"⚠  Save error: {e}")
            return False

    # ── bindings ──

    def action_save(self) -> None:
        if self._do_save():
            self.dismiss(f"✔  Saved: {self._path.name}")

    def action_close_editor(self) -> None:
        self.dismiss(None)

    # ── buttons ──

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
    """Textual TUI File Manager."""

    TITLE = "✦ TUI File Manager"
    SUB_TITLE = platform.system()

    CSS = """
    Screen {
        layout: vertical;
    }

    #main_container {
        layout: horizontal;
        height: 1fr;
    }

    #tree_panel {
        width: 30%;
        min-width: 20;
        border-right: solid $primary-darken-2;
        overflow: auto;
    }

    #right_panel {
        width: 1fr;
        layout: vertical;
    }

    #path_bar {
        height: 1;
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }

    #file_table {
        height: 1fr;
    }

    #status_bar {
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
    }

    DirectoryTree {
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new_file", "New File"),
        Binding("d", "new_dir", "New Dir"),
        Binding("r", "rename", "Rename"),
        Binding("x", "delete", "Delete"),
        Binding("c", "copy_item", "Copy"),
        Binding("v", "paste_item", "Paste"),
        Binding("e", "edit_file", "Edit"),          # ← NEW
        Binding("i", "file_info", "Info"),
        Binding("h", "toggle_hidden", "Hidden"),
        Binding("f5", "refresh", "Refresh"),
        Binding("ctrl+l", "goto", "Go to Path"),
        Binding("backspace", "go_up", "Go Up"),
    ]

    current_dir: reactive[Path] = reactive(Path.home(), init=False)
    show_hidden: reactive[bool] = reactive(False, init=False)
    clipboard: reactive[Path | None] = reactive(None, init=False)
    clipboard_op: reactive[str] = reactive("copy")  # "copy" or "cut"

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main_container"):
            with Vertical(id="tree_panel"):
                yield DirectoryTree(str(Path.home()), id="dir_tree")
            with Vertical(id="right_panel"):
                yield Static("", id="path_bar")
                yield DataTable(id="file_table", cursor_type="row", zebra_stripes=True)
        yield StatusBar("", id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#file_table", DataTable)
        table.add_columns("", "Name", "Size", "Modified", "Permissions")
        # Set reactive here so watcher fires exactly once, after columns exist
        self.current_dir = Path.home()

    # ──────────── Reactive watchers ────────────

    def watch_current_dir(self, new_dir: Path) -> None:
        self.query_one("#path_bar", Static).update(f" 📂  {new_dir}")
        self.refresh_table()
        # Sync tree
        try:
            tree = self.query_one("#dir_tree", DirectoryTree)
            tree.path = str(new_dir)
        except Exception:
            pass

    def watch_clipboard(self, path: Path | None) -> None:
        if path:
            op = "✂ Cut" if self.clipboard_op == "cut" else "📋 Copied"
            self.set_status(f"{op}: {path.name}  — press [V] to paste")
        else:
            self.set_status("")

    # ──────────── UI helpers ────────────

    def set_status(self, msg: str) -> None:
        self.query_one("#status_bar", StatusBar).message = msg

    def refresh_table(self) -> None:
        table = self.query_one("#file_table", DataTable)
        table.clear()
        try:
            entries = sorted(
                self.current_dir.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            self.set_status("⚠  Permission denied")
            return

        count = 0
        self._row_entries: list[Path] = []
        for entry in entries:
            if not self.show_hidden and entry.name.startswith("."):
                continue
            icon = "📁" if entry.is_dir() else self._file_icon(entry)
            try:
                size = "-" if entry.is_dir() else human_size(entry.stat().st_size) if entry.exists() else "?"
            except (OSError, PermissionError):
                size = "?"
            modified = file_modified(entry)
            perms = file_permissions(entry)
            table.add_row(icon, entry.name, size, modified, perms)
            self._row_entries.append(entry)
            count += 1

        hidden_note = "" if self.show_hidden else "  (hidden files excluded)"
        self.set_status(f"{count} items in {self.current_dir}{hidden_note}")

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

    # ──────────── Actions ────────────

    def action_go_up(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            self.current_dir = parent

    def action_refresh(self) -> None:
        self.refresh_table()
        self.set_status("Refreshed.")

    def action_toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.refresh_table()

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
                except Exception as e:
                    self.set_status(f"⚠  Error: {e}")

        self.push_screen(InputModal("Rename to:", default=entry.name), handle)

    def action_delete(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return

        def handle(confirmed: bool) -> None:
            if confirmed:
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    else:
                        entry.unlink()
                    self.refresh_table()
                    self.set_status(f"✔  Deleted: {entry.name}")
                except Exception as e:
                    self.set_status(f"⚠  Error: {e}")

        self.push_screen(
            ConfirmModal(f"Delete '{entry.name}'?\nThis cannot be undone."),
            handle,
        )

    def action_copy_item(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        self.clipboard = entry
        self.clipboard_op = "copy"

    def action_paste_item(self) -> None:
        if not self.clipboard:
            self.set_status("⚠  Clipboard is empty. Use [C] to copy first.")
            return
        src = self.clipboard
        dst = self.current_dir / src.name
        if dst == src:
            self.set_status("⚠  Source and destination are the same.")
            return
        try:
            if self.clipboard_op == "cut":
                shutil.move(str(src), str(dst))
                self.clipboard = None
                self.set_status(f"✔  Moved: {src.name}")
            else:
                if src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
                self.set_status(f"✔  Copied: {src.name}")
            self.refresh_table()
        except Exception as e:
            self.set_status(f"⚠  Error: {e}")

    def action_file_info(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        self.push_screen(InfoModal(entry))

    # ── NEW: edit action ──────────────────────────────────────────────────────

    def action_edit_file(self) -> None:
        entry = self.selected_entry()
        if not entry:
            self.set_status("⚠  No item selected.")
            return
        if entry.is_dir():
            self.set_status("⚠  Cannot edit a directory.")
            return

        def handle(result: str | None) -> None:
            # result is either a status message string or None (closed without saving)
            if result:
                self.set_status(result)
                self.refresh_table()  # update modified timestamp in the table

        self.push_screen(EditModal(entry), handle)


if __name__ == "__main__":
    FileManagerApp().run()