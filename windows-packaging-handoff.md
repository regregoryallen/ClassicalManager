# Windows Packaging — Handoff for Claude Code

**Repo:** github.com/regregoryallen/ClassicalManager
**Status:** App runs on Windows via manual venv setup. This is a handoff for a *deferred* task — making Windows setup friendlier by scripting it. Pick up here when the owner is ready.

**Working style to respect:** Propose the script contents and file placement for review *before* writing or committing. Work in checkpoints. Don't guess — verify against the actual repo files (`main.py`, `requirements.txt`, `config.example.json`, `USERGUIDE.md`) before acting.

---

## Decision

Build **Tier 1 only: batch-based setup and run scripts.** Do **not** build the standalone `.exe` (Tier 2) or installer (Tier 3) yet — those are deferred and have a prerequisite (see "Before any freeze/installer").

Batch (`.bat`/`.cmd`) was chosen deliberately over PowerShell: batch files aren't governed by PowerShell's execution policy, which was the only friction point in manual setup.

---

## Findings from the investigation (don't re-derive these)

- **Python is not present on a clean Windows box** — installing it is a required first step, not optional. Install from python.org with "Add python.exe to PATH" checked and "tcl/tk and IDLE" left checked (that's Tkinter, which customtkinter needs).
- **Repo requires Python 3.12+.** Note: earlier spec text referenced 3.10+ — reconcile the docs if it matters.
- **All deps in `requirements.txt` are pure-Python** — `pip install` needs no C build tools on Windows.
- **Tkinter ships with the python.org installer**, so there is no Windows equivalent of the Linux `python3-tk` step.
- **Execution policy was the only manual-setup friction.** `Set-ExecutionPolicy RemoteSigned -Scope Process` (session-only, reverts on window close) resolved it. Batch scripts avoid this entirely.
- The README Quick Start is Linux-only (`cp`, `source venv/bin/activate`, `python3`). The USERGUIDE already has the Windows venv activate line.

---

## Tasks (Tier 1)

1. **`setup.bat`** at repo root:
   - Detect Python and verify version >= 3.12; if missing or too old, print a clear message linking to python.org (optionally offer `winget install Python.Python.3.12` — confirm the package id with `winget search Python.Python` first).
   - Create the venv (`python -m venv venv`) if it doesn't already exist.
   - Activate it and run `pip install -r requirements.txt`.
   - Copy `config.example.json` to `config.json` **only if `config.json` does not already exist** (never clobber an existing config).
   - Print clear success/failure with next-step guidance.

2. **`run.bat`** at repo root:
   - Activate the venv and launch `python main.py`, passing through arguments so `run.bat --cli scan ...` works.
   - If the venv or deps are missing, print a clear error telling the user to run `setup.bat` first.

3. **README:** add a dedicated **Windows** section — the install-Python step, `copy` vs `cp`, the venv activate line, and a one-liner pointing at `setup.bat` / `run.bat`. Keep the existing Linux Quick Start intact.

**Acceptance check:** On a clean Windows user account with Python freshly installed, double-clicking `setup.bat` then `run.bat` brings up the GUI, and `run.bat --cli scan ...` works from a terminal.

---

## Before any freeze/installer (prerequisite — also deferred)

`config.json`, the SQLite DB (`music_manager.db`), and `gui_prefs.json` currently live in the working/project directory. That's fine for a cloned repo, but it breaks for a frozen or installed app that may run from a read-only or unpredictable location (e.g. Program Files).

Relocate user-writable data to a per-user directory — `%APPDATA%\ClassicalManager\` on Windows — via the `platformdirs` package, which maps to `~/.config` on Linux so it stays cross-platform. **Do this before Tier 2/3.**

---

## Deferred — Tier 2/3 (context only, not now)

- **Tier 2, standalone `.exe` (PyInstaller):** use `--onedir` (not `--onefile`) with `--collect-all customtkinter` (or `--add-data` the customtkinter package directory), because customtkinter bundles `.json`/`.otf` data files that PyInstaller does not auto-include. Must be built **on Windows** — PyInstaller does not cross-compile from the Ubuntu dev box.
- **Tier 3, installer:** wrap the PyInstaller `dist` folder with Inno Setup or InstallForge for Start Menu shortcuts and an uninstaller.

---

## References

- CustomTkinter packaging docs (onedir + add-data requirement): https://customtkinter.tomschimansky.com/documentation/packaging/
- PyInstaller usage docs: https://pyinstaller.org/
- Repo entry point and deps: `main.py`, `requirements.txt`, `config.example.json`, `USERGUIDE.md`
