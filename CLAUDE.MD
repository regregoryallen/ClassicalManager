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
- MB work ID merging: tracks with different MB work IDs but the same WORK tag are merged into a single work
- WORK tag reading: ID3 `TXXX:Work` (any case), `TIT1`, `GRP1`; Vorbis `WORK`; MP4 `©wrk`
- Heuristic work detection (`scanner.py:_assign_by_heuristic`): requires minimum 3-word prefix, 5+ chars, movement markers, and contiguous track numbers
- `redetect_works()` re-runs all 5 detection steps from DB-stored tag data without rescanning files
- `scan_incremental()` compares file mtime/size to skip unchanged files, only processes additions/changes/deletions
- `__standalone__` override value for `work_group_key` forces tracks to standalone, bypassing all detection
- Non-destructive overrides survive rescans
- Track model stores raw tag data: `work_tag`, `mb_work_id`, `file_mtime`, `file_size`
- GUI uses CustomTkinter; file dialogs use zenity/kdialog on Linux, native on Win/Mac
- Profile names must be unique across all libraries
- Library scans are long-running (minutes for large collections) — never run them automatically

## Session Status (2026-06-16)

### Recently completed
- Cleanup/Overlay tab overhaul:
  - Works browser with source filter dropdown, live search, multi-select, expand/collapse
  - Right-click context menu: Details popup, Show Album, edit shortcuts, Make Standalone
  - Show Album popup: album metadata editing, works/tracks treeview with multi-select, per-track overrides
  - Hide 1-track checkbox, overrides search
- Work detection improvements:
  - TXXX:Work tag reading (mixed-case ID3 user-defined frame)
  - MB work ID merging when tracks share the same WORK tag
  - `__standalone__` override to suppress erroneous work tags
  - Delimiter-aware prefix matching, identical-title pre-pass, tighter Roman numeral regex, digit-dash markers
- Full redetect (`redetect_works`): re-runs all 5 detection steps from DB data
- Incremental scan (`scan_incremental` / CLI `scan-changes` / GUI "Scan Changes"): only processes new/changed/deleted files
- DB: `work_tag`, `mb_work_id`, `file_mtime`, `file_size` columns on Track with auto-migration
- Playlist builder: composer column, info column centering, right-click Details/Show Album context menu
- Live search with debounce on cleanup, overrides, and explorer tabs
- CLI: `--quiet` flag on scan, scan-changes, redetect, generate-all
- Stale data handling in playlist builder context menu

### Pending/known issues
- The `_MIN_PREFIX_WORDS` constant (currently 3) may benefit from being configurable
- Heuristic work names can retain structural words from the prefix (e.g. "Petrouchka (1947 ver): Scene") — cosmetic, correctable via overrides

