Read classical-playlist-manager-spec.md for application specification. Update document as needed to preserve continuity. 

Build python application within a virtual environment (venv/, not .venv/).

Document each major section using docstrings. 

Ask for clarifications as needed. Stage work so that you have everything upfront and can run long, unattended coding sessions. Break work up so that you can continue cleanly after running out of tokens or otherwise stopping the sessions. Make sure that status/progress is documented at the end of every session.

## Project Structure

- `main.py` — Entry point (GUI or CLI via `--cli`)
- `music_manager/core/` — Scanner, engine, database, config, serializers, overrides, integrity
- `music_manager/interfaces/` — GUI (`gui.py`), CLI (`cli.py`), file dialogs (`filedialog.py`)
- `config.json` — User config (gitignored; template at `config.example.json`)
- `gui_prefs.json` — Auto-managed GUI preferences (gitignored)

## Key Architecture Notes

- Database: SQLite via Peewee ORM (`music_manager/core/database.py`)
- Work detection precedence: override > MusicBrainz work ID > WORK tag > title-prefix heuristic > standalone
- Heuristic work detection (`scanner.py:_assign_by_heuristic`): requires minimum 3-word prefix, 5+ chars, movement markers, and contiguous track numbers
- `redetect_heuristic_works()` re-runs heuristic/standalone detection from DB data without rescanning files
- Non-destructive overrides survive rescans
- GUI uses CustomTkinter; file dialogs use zenity/kdialog on Linux, native on Win/Mac
- Profile names must be unique across all libraries
- Library scans are long-running (minutes for large collections) — never run them automatically

## Session Status (2026-06-15)

### Recently completed
- Heuristic work detection improvements: word-boundary prefix trimming, minimum 3-word prefix, contiguous track requirement
- Re-detect works feature (CLI `redetect` command + GUI button) — re-runs heuristic without full rescan
- Cross-platform file dialogs (zenity/kdialog/tkinter hybrid)
- Scan cancellation, tree filtering, expand/collapse, last-library memory
- Per-library Plex sections, profile uniqueness enforcement
- CLI `generate-all` command, integrity check popup
- Context menu fix (tk_popup instead of post)

### Pending/known issues
- Heuristic work detection still needs further tuning (some false groupings remain)
- The `_MIN_PREFIX_WORDS` constant (currently 3) may benefit from being configurable

