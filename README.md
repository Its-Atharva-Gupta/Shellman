# Shellman

![Uploading demo2.gif…]()


A fast, lightweight, terminal-based file manager and editor built with [Textual](https://github.com/Textualize/textual). Runs on Linux, macOS, and Windows.

---

## Features

- Dual-panel layout — directory tree on the left, file list on the right
- Edit any text file directly in the terminal with syntax highlighting for 15+ languages
- Create, rename, delete, copy, cut, and move files and directories
- Bulk selection — select multiple files with Space and operate on all at once
- Undo — every operation is reversible, deletes go to a trash folder
- Git integration — see modified, staged, untracked, and deleted files at a glance
- Archive support — zip selected files or extract any archive in place
- File search — filter the current directory in real time
- Sort by name, size, date modified, or file type
- Open any file with the default system application
- Disk usage indicator in the status bar
- Full keyboard shortcut reference accessible at any time with `?`

---

## Installation

### Linux (Debian / Ubuntu / Pop!_OS)

Download `shellman_amd64.deb` from the [Releases](https://github.com/Its-Atharva-Gupta/TUI-Based-File-Manager/releases) page, then:

```bash
sudo apt install ./shellman_amd64.deb
```

### Linux (Fedora / RHEL)

Download `shellman_amd64.rpm` from the [Releases](https://github.com/Its-Atharva-Gupta/TUI-Based-File-Manager/releases) page, then:

```bash
sudo dnf install ./shellman_amd64.rpm
```

### Linux (Arch)

No dedicated package is provided for Arch. Build from source using the instructions below, or copy the binary manually:

```bash
sudo cp shellman_amd64 /usr/local/bin/shellman
sudo chmod +x /usr/local/bin/shellman
```

### macOS

Download `shellman_macos` from the [Releases](https://github.com/Its-Atharva-Gupta/TUI-Based-File-Manager/releases) page, then:

```bash
sudo cp shellman_macos /usr/local/bin/shellman
sudo chmod +x /usr/local/bin/shellman
```

### Windows

Download `shellman_amd64.exe` from the [Releases](https://github.com/Its-Atharva-Gupta/TUI-Based-File-Manager/releases) page. No installation needed — run it directly from a terminal:

```
shellman_amd64.exe
```

---

## Keyboard Shortcuts

Press `?` inside the app to open the full shortcut reference at any time.

| Key       | Action                                      |
|-----------|---------------------------------------------|
| Enter     | Open directory                              |
| Backspace | Go up one level                             |
| Ctrl+L    | Go to path                                  |
| H         | Toggle hidden files                         |
| F5        | Refresh                                     |
| Space     | Select / deselect item (bulk select)        |
| N         | New file                                    |
| D         | New directory                               |
| R         | Rename                                      |
| X         | Delete (moved to ~/.shellman_trash)         |
| C         | Copy                                        |
| T         | Cut                                         |
| V         | Paste                                       |
| U         | Undo last operation                         |
| E         | Edit file                                   |
| O         | Open with default app                       |
| Z         | Zip selected files / Extract archive        |
| I         | File info                                   |
| S         | Cycle sort (name / size / modified / type)  |
| /         | Filter files in current directory           |
| Escape    | Clear filter                                |
| ?         | Show all keyboard shortcuts                 |
| Q         | Quit                                        |

### Inside the editor

| Key    | Action              |
|--------|---------------------|
| Ctrl+S | Save file           |
| Escape | Close without saving|

---

## Git Status Indicators

When inside a git repository, the G column in the file list shows the status of each file:

| Symbol | Meaning   |
|--------|-----------|
| M      | Modified  |
| A      | Staged    |
| ?      | Untracked |
| D      | Deleted   |
| R      | Renamed   |

---

## Run from Source

Requires Python 3.9 or later.

```bash
git clone https://github.com/Its-Atharva-Gupta/TUI-Based-File-Manager.git
cd TUI-Based-File-Manager
pip install textual
python src/main.py
```

---

## Build from Source

If a prebuilt binary is not available for your platform or architecture, you can build one yourself. Requires Python 3.9+ and pip.

```bash
git clone https://github.com/Its-Atharva-Gupta/TUI-Based-File-Manager.git
cd TUI-Based-File-Manager
chmod +x scripts/build.sh
./scripts/build.sh
```

The script will automatically detect your operating system, install the required build tools, and produce a binary in the `dist/` folder.

---

## Dependencies

- [Textual](https://github.com/Textualize/textual) - TUI framework
- [Rich](https://github.com/Textualize/rich) - Terminal formatting (pulled in by Textual)

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Author

Developed by [Its-Atharva-Gupta](https://github.com/Its-Atharva-Gupta).
