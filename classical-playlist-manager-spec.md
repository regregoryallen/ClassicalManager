# Classical-Aware Music Playlist Manager — Technical Specification

**Status:** Build specification for Claude Code
**Target stack:** Python 3.10+, peewee (SQLite), mutagen, python-plexapi, customtkinter, argparse/typer

---

## 1. Purpose

A cross-platform (Linux/Windows) desktop application that catalogs a local music collection into a SQLite database and generates customizable playlists. Unlike track-only shufflers, it natively understands the hierarchy of classical metadata: multi-track **Works** (symphonies, concertos, sonatas) are kept grouped and internally ordered.

Generated playlists can be written **directly to a Plex server via the Plex API** or **exported to portable text formats** (M3U, JSON) for non-Plex use. Core logic is decoupled from the interfaces, exposing both a GUI and a CLI.

The application owns all classical grouping logic. **Plex is never asked to understand works** — it receives a flat, fully-ordered list. This deliberately sidesteps Plex's weak native classical handling.

---

## 2. Goals and scope

### In scope (V1)
- Scan multiple source folders per library into SQLite.
- Classical-aware data model: composers, works, movements, disc numbers, folder-based album identity.
- Overlay metadata corrections (DB-only; files untouched), exportable/importable as JSON, surviving a full DB rebuild.
- Playlist engine: include/exclude rules; Track / Work / Album shuffle modes; work-integrity policy; stop conditions.
- Output serializers: Plex (API), M3U (text), JSON (machine-readable / debug).
- Per-target path realization (base-path / prefix-rewrite rules).
- Diagnostics: dry-run preview, JSON debug dump with grouping provenance, post-scan health report, integrity checks, Plex path-match preflight.
- GUI (customtkinter) and CLI.

### Explicitly out of scope
- A general-purpose tag editor (use Picard/Kid3/Mp3tag for non-classical tag hygiene).
- Multiple Plex servers or multiple music sections.
- Smart / auto-updating playlists.

### Deferred to V2+
- **Tag write-back to files** (V2): committing overlay corrections into the audio files via mutagen, backed by per-file backups. The provenance field (§5.4) exists in V1 specifically to make this safe later.
- Additional export formats (PLS, XSPF) — added as new serializer implementations against the existing interface.
- Selection weighting / variety constraints (e.g. duration-weighting). *(Note: "Avoid Adjacent" separation — same composer, album, or musical form — has been implemented; see §7.6.)*

> **Implemented since V1 spec:**
> - Incremental scan via mtime/size change detection (originally deferred; now active).
> - Avoid Adjacent constraints preventing consecutive works by the same composer, album, or musical form (§7.6).

---

## 3. Architecture

```
music_manager/
├── core/
│   ├── __init__.py
│   ├── database.py        # peewee models, connection, FK pragma, migrations
│   ├── scanner.py         # mutagen extraction, work detection, disc parsing
│   ├── overrides.py       # overlay application, JSON export/import
│   ├── engine.py          # selection, shuffle modes, work-integrity policy
│   ├── integrity.py       # health report + integrity checks
│   ├── paths.py           # canonical path storage + per-target realization
│   └── serializers/
│       ├── __init__.py    # Serializer interface (ABC)
│       ├── m3u.py
│       ├── plex.py
│       └── json_dump.py
├── interfaces/
│   ├── __init__.py
│   ├── cli.py             # argparse/typer
│   └── gui.py             # customtkinter
├── config.json
└── main.py                # entry point / router
```

### Layering principle (the structural spine)
The **engine's only output is an ordered list of resolved Track rows** (a "resolved playlist"). Every output format is a **Serializer** consuming that same list. Plex vs. M3U vs. JSON is a choice of serializer, never a fork in the engine. This is the core extensibility seam — new formats are new `Serializer` subclasses and nothing else changes.

### Entry-point routing (`main.py`)
Route to the CLI when invoked with the explicit `--cli` flag (or any subcommand); launch the GUI when run with no arguments. The presence of `--cli` is the deciding signal — do **not** rely on "any argument present," so that `--help` and future GUI flags behave predictably.

---

## 4. Data model

### 4.1 Global rules
- **POSIX path storage.** All stored paths use forward slashes regardless of host OS. OS-specific separators are applied only at output time, per target (§8).
- **Album = Folder.** A source subfolder is treated as exactly one album. Album identity is keyed on the folder, not on tags (robust against inconsistent tags).
- **Ordering is always `(disc_number, track_number)`**, never `track_number` alone.
- **Duration is stored as integer milliseconds** (`duration_ms`), matching Plex; converted to integer seconds for `#EXTINF`.
- Enable SQLite foreign keys on every connection (`PRAGMA foreign_keys = ON`).

### 4.2 Tables

**Libraries**
| field | type | notes |
|---|---|---|
| id | PK | |
| name | text | e.g. "Main Collection", "Christmas Music" |

> Library + source-folder definitions are authoritative **in the DB** (managed via GUI/CLI). `config.json` holds only the *active* library pointer plus target/connection settings — this removes the original spec's config-vs-DB duplication.

**SourceFolders**
| field | type | notes |
|---|---|---|
| id | PK | |
| library_id | FK → Libraries | |
| root_path | text (POSIX) | canonical root as seen by the scanning host |

**Composers**
| field | type | notes |
|---|---|---|
| id | PK | |
| library_id | FK → Libraries | |
| name | text | display form as tagged |
| sort_name | text, nullable | e.g. "Beethoven, Ludwig van" |
| norm_key | text | normalized key for dedup/matching |

**Albums**
| field | type | notes |
|---|---|---|
| id | PK | |
| library_id | FK → Libraries | |
| folder_id | FK → SourceFolders | |
| album_key | text | **= the containing folder's relative path** (album identity) |
| title | text | from tags; folder name as fallback |
| album_artist | text, nullable | distinct from track artist |
| year | int, nullable | |
| musicbrainz_album_id | text, nullable | |

> Uniqueness: `(library_id, album_key)`. Because each distinct recording lives in its own folder, the "12 different Beethoven 5ths" problem disappears.

**Works**
| field | type | notes |
|---|---|---|
| id | PK | |
| album_id | FK → Albums | a work belongs to one album |
| composer_id | FK → Composers, nullable | canonical filter target |
| work_name | text | |
| work_sequence | int, nullable | position of the work within the album (for Album-mode ordering) |
| work_source | text | provenance: `override` / `mb_workid` / `work_tag` / `heuristic` / `standalone` |
| musicbrainz_work_id | text, nullable | |

**Tracks**
| field | type | notes |
|---|---|---|
| id | PK | |
| library_id | FK → Libraries | |
| folder_id | FK → SourceFolders | |
| album_id | FK → Albums | |
| work_id | FK → Works, nullable | |
| composer_id | FK → Composers, nullable | from the file's composer tag |
| title | text | |
| relative_path | text (POSIX) | relative to the SourceFolder root |
| disc_number | int (default 1) | |
| disc_total | int, nullable | |
| track_number | int | |
| movement_number | int, nullable | for in-work ordering |
| duration_ms | int | |
| musicbrainz_recording_id | text, nullable | |

**PlaylistProfiles** (saved playlist definitions)
| field | type | notes |
|---|---|---|
| id | PK | |
| library_id | FK → Libraries | |
| name | text | e.g. "Sunday Classical" |
| shuffle_mode | text | `track` / `work` / `album` |
| work_integrity | text | `enforce` / `respect_selection` (default derived from mode, §7.3) |
| length_mode | text | `count` / `duration` / `all` |
| length_value | int, nullable | track count, or seconds, per length_mode |
| seed | int, nullable | optional, for reproducible shuffles |
| no_repeat_tracks | bool (default true) | drop duplicate tracks within one playlist |
| separate_composers | bool (default false) | avoid adjacent works by same composer |
| separate_albums | bool (default false) | avoid adjacent works from same album |
| separate_forms | bool (default false) | avoid adjacent works of same musical form |

**ProfileRules** (the include/exclude stacks)
| field | type | notes |
|---|---|---|
| id | PK | |
| profile_id | FK → PlaylistProfiles | |
| rule_type | text | `include` / `exclude` |
| target_level | text | `composer` / `album` / `work` / `track` |
| target_id | int | id of the referenced entity |

**ProfilePins** (pinned works at fixed positions)
| field | type | notes |
|---|---|---|
| id | PK | |
| profile_id | FK → PlaylistProfiles | |
| work_id | int | id of the pinned work |
| position | int | 1–5; unique per (profile, position) |

**Overrides** (overlay corrections — see §6)
| field | type | notes |
|---|---|---|
| id | PK | |
| library_id | FK → Libraries | |
| scope | text | `track` / `album` |
| match_mb_id | text, nullable | MB recording id (track) / album id (album) |
| match_relative_path | text, nullable | track relpath, or album folder relpath |
| field | text | overridden field name (see §6.2) |
| value | text | corrected value |
| updated_at | datetime | |

> At least one of `match_mb_id` / `match_relative_path` must be present.

---

## 5. Scanner (ingestion)

### 5.1 Crawl
Walk each `SourceFolder.root_path` with `pathlib`. For each audio file, extract embedded tags via mutagen (ID3 / Vorbis / MP4). Store `relative_path` POSIX-normalized relative to the folder root.

### 5.2 Album = folder
All tracks in the same leaf folder belong to one album, identified by `album_key` = the folder's relative path. Populate album `title` / `album_artist` / `year` from tags, falling back to the folder name for title.

### 5.3 Disc number derivation (in priority order)
1. A real `DISCNUMBER` / `disctotal` tag, if present.
2. Else parse a `D-TT` prefix from the track-number string or filename (`1-01` → disc 1, track 1; `2-05` → disc 2, track 5).
3. Else default to disc 1.

The DB stores clean `disc_number` / `track_number`; the user's `D-TT` filenames are a parsing input, not the source of truth. No library reorganization is required.

### 5.4 Work detection (precedence — stop at first match)
0. **Manual override** (`work_group_key`, §6) — highest authority.
1. **`MUSICBRAINZ_WORKID`** — group tracks sharing the id.
2. **`WORK` tag** (Vorbis `WORK`; MP4 `©wrk`; ID3 iTunes grouping `GRP1`/`TIT1`) — group by work name; order within the work by `MOVEMENT` / `MOVEMENTNAME`.
3. **Title-prefix heuristic** (fallback only): within a single album/disc, group tracks sharing a common title prefix before a movement delimiter, requiring ≥2 tracks and a recognized movement marker (roman numeral, "No.", movement word). Conservative — when in doubt, leave ungrouped.
4. Otherwise a **standalone single-track work**.

Record which rule fired in `Works.work_source` for every work (drives review UI and debugging). Movement tags read: `MOVEMENTNAME`, `MOVEMENT` (number), `MOVEMENTTOTAL` (Vorbis); `©mvn`/`©mvi` (MP4); `MVNM`/`MVIN` (ID3).

### 5.5 Composer
Populate `Track.composer_id` from the composer tag (`COMPOSER` / `TCOM` / `©wrt`). After grouping, assign each `Work.composer_id` from the modal composer of its tracks. Dedup composers by `norm_key`; allow manual merge in the cleanup UI.

---

## 6. Overlay & overrides

### 6.1 Model
Scanned tags populate the DB. User corrections are stored **only** as `Overrides` records — **audio files are never modified in V1.** When building the working view of any entity, raw scanned values are overlaid with matching override values.

**Rebuild-safe by construction:** a full re-scan or DB rebuild reconstructs all entities from files + tags, then re-applies overrides. Manual work is preserved as long as the overrides survive (they are exportable JSON, §6.3).

### 6.2 What can be overridden
- **Track scope:** `composer`, `work_group_key` (manual work grouping — the highest-precedence work source, §5.4 step 0), `work_name`, `disc_number`, `track_number`, `movement_number`, `title`.
- **Album scope:** `album_title`, `album_artist`, `year`.

### 6.3 Matching, export, import
- **Apply order:** match an override to its entity by `match_mb_id` first, then by `match_relative_path`. Store **both** when available so an override survives a change to either.
- **Export:** serialize the `Overrides` table to a JSON file (records with match keys + field + value).
- **Import:** upsert records from that JSON, then re-apply. Import + re-apply after a rebuild restores all manual grouping/metadata work.

---

## 7. Playlist engine

### 7.1 Selection
1. Assemble base population: all tracks in the active library scope.
2. Apply **inclusions** (whitelist at composer / album / work / track level).
3. Apply **exclusions** (blacklist at composer / album / work / track level).

Internally, selection resolves to a **set of included track IDs**.

### 7.2 Shuffle modes
- **Track mode** — shuffle included tracks individually.
- **Work mode** — shuffle the *works* present in the selection (a standalone track is a single-track work). When a work is drawn, emit its tracks back-to-back ordered by `(disc_number, movement_number/track_number)`.
- **Album mode** — shuffle the *albums* present in the selection. Emit each album's tracks ordered by `(disc_number, work_sequence, track_number)`.

> Note: Work mode draws uniformly over works, so long works occupy more playlist *time* than short ones at equal draw probability. This is intended; revisit only if duration-weighting is added in V2.

**Avoid Adjacent (separation constraint):** After shuffling, a best-effort pass reorders works to prevent consecutive entries by the same composer, from the same album, or of the same musical form, according to the profile's `separate_composers`, `separate_albums`, and `separate_forms` flags. This is a soft constraint — when avoidance is impossible (e.g. one composer dominates the selection), the engine keeps the best arrangement it can find.

### 7.3 Work-integrity policy
A single policy governs how partially-selected works are expanded, with mode-driven defaults:

- **`enforce`** — any work with ≥1 selected track is played *whole*, in order. **Default for Work and Album modes.**
- **`respect_selection`** — emit exactly the selected tracks; a work may appear partially. **Default for Track mode.**

**UI behavior:**
- In Work/Album mode, attempting to exclude a single movement is disallowed: offer "exclude the entire work" or "switch to Track mode to drop individual movements."
- In Track mode, individual track include/exclude is freely allowed (supports hand-picking a subset of a work's movements).

Filtering granularity (this policy) and shuffle granularity (the mode) are independent concepts — keep them distinct in the implementation.

### 7.4 Stop conditions & ordering
- `length_mode = count` → stop after N tracks.
- `length_mode = duration` → stop once accumulated `duration_ms` ≥ target.
- `length_mode = all` → emit the entire selection.
- If `no_repeat_tracks`, never emit the same track twice.
- If `seed` is set, the shuffle is deterministic and reproducible (debugging aid).

### 7.5 Output
The engine returns an ordered list of resolved Track rows, each annotated with its work, album, composer, computed order key, and the inclusion rule that admitted it (for the JSON debug serializer, §9).

### 7.6 Pin to position
After shuffling, pinned works (from `ProfilePins`) are inserted at their designated positions (1–5) at the start of the playlist. Pinned works are automatically included in the selection even if no include rule covers them. Tracks of a pinned work are ordered naturally (disc_number, movement_number). Position 1 = first work, position 2 = after the first work ends, etc.

---

## 8. Output / serializers

### 8.1 Serializer interface
An abstract base (`Serializer`) takes a resolved playlist (ordered Track rows) + a target config and produces output. Implementations: `M3USerializer`, `PlexSerializer`, `JSONSerializer`. PLS/XSPF are future implementations of the same interface.

### 8.2 Path realization (per target)
Canonical absolute POSIX path = `SourceFolder.root_path` + "/" + `Track.relative_path`. Each target realizes it:
- An ordered list of **prefix-rewrite rules** (`source_prefix → target_prefix`) applied to the canonical path.
- OS separator normalization applied **last** (so no mixed-separator output).
- **Roger's current setup = zero rules** (identical mounts on generator and Plex hosts → identity).

This replaces the original single global find/replace, which produced mixed separators and could not handle multiple mounts.

### 8.3 M3U serializer
- Extended M3U, UTF-8, extension `.m3u`.
- `#EXTM3U` header; per entry `#EXTINF:<seconds>,<display>` then the realized path.
- `<seconds>` = `round(duration_ms / 1000)`.
- Default display: `Composer – Work: Movement` when a work is present, else `Artist – Title` (make the template configurable).
- M3U target supports `path_style = absolute` (with optional base) or `relative_to_playlist` (most portable for arbitrary players).
- Overwrites the same-named `.m3u` on regeneration.

### 8.4 Plex serializer
- **Primary strategy — m3u handoff:** write a temporary M3U whose realized paths match what Plex has indexed, then call
  `plex.createPlaylist(title=<name>, section=<music section>, m3ufilepath=<temp.m3u>)`.
- **Fallback strategy — item match:** build a `realized_path → Plex Track` index by walking the music section once (each track exposes its file via `Media.Part.file`), match each engine track to a `ratingKey`, then `plex.createPlaylist(title=<name>, items=[tracks])`. Use when path matching proves unreliable.
- **Regeneration overwrites by title:** locate the existing playlist of the same name and update its items in place using `removeItems()` + `addItems()`, preserving the Plex playlist ID for external integrations (e.g. Music Assistant in Home Assistant). New playlists are created normally.
- **Connection:** base URL + token; **read the token from an environment variable or a separate secrets file, never store it in `config.json` in plaintext.**

### 8.5 JSON serializer
Emits the fully-resolved playlist as structured JSON: per entry — track, album, work (+ `work_source`), composer, disc/track/movement, computed order key, and the inclusion rule that admitted it. Serves double duty as the machine-readable export **and** the primary ordering/grouping diagnostic (§9).

---

## 9. Diagnostics & integrity

### 9.1 Dry-run / preview
Resolve a profile to its ordered list **without** writing to Plex or disk; render it (GUI) or emit JSON (CLI). The first-line tool for "why is this track here / why is it ordered this way."

### 9.2 Post-scan health report
After a scan, summarize: files scanned, albums / works / tracks counted, and problem lists — tracks with no composer, works formed by `heuristic` (need review), missing or zero `duration_ms` (would break `#EXTINF`), and files that failed to parse.

### 9.3 Integrity checks (on demand)
- **Orphans:** DB tracks whose files no longer exist.
- **Unscanned:** files on disk not present in the DB.
- **Duplicates:** the same file under two source folders; the same recording (by MB recording id, else `(album, disc, track)`) appearing twice.
- **Cross-folder works:** a work whose tracks span more than one folder — should be impossible under Album=Folder, so it's a useful canary for tagging or grouping errors.
- **Referential integrity:** rely on SQLite FK enforcement plus app-level checks.

### 9.4 Plex path-match preflight
Before a full push, sample N tracks and confirm Plex resolves their realized paths. Surfaces the path-correspondence problem early instead of producing a silently-empty playlist.

---

## 10. GUI (customtkinter)

> **Treeview note for the implementer:** customtkinter has no native tree widget. Use a styled `ttk.Treeview` (themed via `ttk.Style` to approximate the customtkinter palette) or a vetted community add-on (e.g. CTkTreeview). Plan for the visual seam this introduces.

- **Sidebar:** active-library selector; total track / work / album metrics; a "Rescan Library" button (runs the scan on a **background thread** with a progress indicator — the scan must not block the UI).
- **Tab 1 — Explorer & Rules:** browsable/searchable tables of Albums and Works. Right-click context menu to add an element to the Include or Exclude stack (granularity gated by the active shuffle mode per §7.3).
- **Tab 2 — Playlist Builder:** select shuffle mode, work-integrity policy, length/stop condition, seed; "Preview (dry-run)", "Export to M3U", and "Push to Plex" actions.
- **Tab 3 — Cleanup (overlay):** review works flagged `heuristic`; reassign/merge/split works (writes `work_group_key` overrides); edit composer/disc/movement/album fields (overrides); merge duplicate composers; export/import overrides JSON. **Classical fields only** — not a general tag editor.

---

## 11. CLI

```bash
# Rescan a library
python main.py --cli scan --library "Main Collection"

# Preview a profile without writing anything (dry-run → JSON)
python main.py --cli preview --profile "Sunday Classical"

# Generate + export to M3U
python main.py --cli generate --profile "Sunday Classical" --format m3u --output /playlists/sunday.m3u

# Generate + push to Plex (overwrites same-named playlist)
python main.py --cli generate --profile "Sunday Classical" --target plex

# Overrides
python main.py --cli overrides export --library "Main Collection" --output overrides.json
python main.py --cli overrides import --library "Main Collection" --input overrides.json

# Integrity / health
python main.py --cli integrity --library "Main Collection"

# Webhook service for remote job submission (Home Assistant, etc.)
python main.py --cli webhook [--library "Main Collection"] [--port 5588] [-v]

# Global --config flag (works with any command, placed before --cli)
python main.py --config /path/to/alt-config.json --cli generate-all --library "Main Collection" --target plex
```

---

## 12. Configuration (`config.json`)

```json
{
  "active_library": 1,
  "targets": {
    "plex": {
      "base_url": "http://plex-host:32400",
      "token_env": "PLEX_TOKEN",
      "music_section": "Music",
      "path_rules": []
    },
    "m3u": {
      "path_style": "absolute",
      "base_path": "",
      "path_rules": []
    }
  },
  "cron": {
    "library": "Main Collection",
    "mode": "plex",
    "profile": "",
    "m3u_output_dir": "~/Playlists",
    "verbosity": "-q"
  },
  "webhook": {
    "host": "0.0.0.0",
    "port": 5588,
    "library": "Main Collection",
    "allowed_commands": ["plex", "scan", "scan+plex", "scan+m3u", "m3u"]
  }
}
```

- Library and source-folder definitions live in the DB (not here) — config holds only the active-library pointer and target/connection settings.
- `path_rules` empty = identity (current setup). Each rule is `{ "find": "<source_prefix>", "replace": "<target_prefix>" }`, applied in order.
- `cron` section (optional): settings read by the cron companion script. Mode is one of: `plex`, `m3u`, `scan`, `scan+plex`, `scan+m3u`.
- `webhook` section (optional): settings for the webhook HTTP service. `allowed_commands` restricts which commands can be submitted via the API.
- Global `--config PATH` flag allows any CLI command (or the GUI) to use an alternate config file.
- Validate `config.json` on load with clear, specific error messages.

### §12.1 Webhook Service

A lightweight HTTP service (`http.server` from stdlib, zero dependencies) that accepts remote commands to trigger CLI operations in a background thread. Designed for Home Assistant integration.

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/jobs` | Submit a job (`{"command": "plex"}`, optional `"quiet": true`) — returns 202 on success, 409 if busy, 400 if invalid |
| GET | `/api/jobs/current` | Currently running job or 404 |
| GET | `/api/jobs/last` | Last completed job (includes `exit_code`, `output`) or 404 |
| GET | `/api/health` | Liveness check with library name and allowed commands |

**Job semantics:** At most one job runs at a time. Jobs execute CLI commands via `subprocess.run()` in a background thread. The `--config` flag is passed through to subprocess calls if set.

---

## 13. Non-functional requirements

- **SQLite FK pragma** enabled on every connection.
- **Logging** with levels; structured where practical; a verbose flag for diagnostics.
- **Error handling:** scans and Plex pushes degrade gracefully (skip + report a bad file/track, don't abort the run).
- **Testing (required).** Unit tests for: work-detection precedence (every branch), disc-prefix parsing, path realization + rewrite rules (including no mixed separators), each serializer, and override matching (MB-id vs relative-path, plus a rebuild round-trip). At least one integration test: scan a fixture library → dry-run JSON → assert ordering and grouping.
- **Packaging:** runnable on a headless Linux utility server (CLI) and on Windows (GUI); keep GUI imports lazy so CLI runs without a display.

---

## 14. Suggested build order (verification checkpoints)

Each phase ends at a point where output can be verified against the real library before proceeding.

- **Phase 0 — Scaffold.** Project layout, config load + validation, peewee models + schema, FK pragma. *Checkpoint:* empty DB created, config validates.
- **Phase 1 — Scanner + integrity.** Crawl, tag extraction, album=folder, disc parsing, work detection (+provenance), composer, health report, integrity checks. *Checkpoint:* scan the real library; review the health report; verify a known multi-disc set parses correctly and works group as expected.
- **Phase 2 — Overlay/overrides.** Overrides table, apply order, JSON export/import, rebuild round-trip. *Checkpoint:* correct a heuristic work grouping, export, rebuild the DB from files, import, confirm the correction is restored.
- **Phase 3 — Engine + JSON serializer.** Selection, modes, integrity policy, stop conditions, seed; JSON debug output. *Checkpoint:* run all three modes; inspect JSON ordering + provenance; confirm `enforce` vs `respect_selection` behavior.
- **Phase 4 — M3U + Plex serializers.** Path realization, M3U output, Plex m3u-handoff, path preflight, overwrite-by-name. *Checkpoint:* push a small playlist to Plex and confirm it matches; confirm regeneration overwrites; confirm the text M3U plays in another player.
- **Phase 5 — GUI.** Sidebar + background scan, Explorer/Rules, Playlist Builder, Cleanup panel. *Checkpoint:* complete a full scan → review → build → preview → push workflow entirely through the GUI.
