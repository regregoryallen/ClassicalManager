# Classical Music Playlist Manager — User Guide

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Initial Setup](#initial-setup)
4. [Getting Started](#getting-started)
5. [The Sidebar](#the-sidebar)
6. [Explorer & Rules Tab](#explorer--rules-tab)
7. [Playlist Builder Tab](#playlist-builder-tab)
8. [Cleanup / Overlay Tab](#cleanup--overlay-tab)
9. [Settings](#settings)
10. [Command-Line Interface](#command-line-interface)
11. [Usage Patterns](#usage-patterns)
12. [Configuration Reference](#configuration-reference)
13. [Troubleshooting](#troubleshooting)

---

## Overview

Classical Music Playlist Manager is a desktop application for managing and generating
playlists from classical music collections. Unlike general-purpose playlist tools, it
understands multi-movement works, composers, and how tracks relate within a
composition — so a symphony's movements stay together in a shuffled playlist.

Key capabilities:

- **Automatic work detection** from MusicBrainz IDs, WORK tags, or title-prefix heuristics
- **Work-aware shuffling** that keeps movements together in the correct order
- **Additive selection** at album, work, or track level with specificity-based exceptions
- **Export to M3U, JSON, or Plex** with configurable path rewriting
- **Non-destructive metadata overrides** to correct grouping without modifying audio files
- **Multiple libraries** for distinct collections (e.g., classical, holiday music)
- **Pin to position** to fix specific works at positions 1–5 at the start of a playlist
- **GUI and CLI** — the GUI for interactive work, the CLI for scripting and cron jobs

The application works with locally stored audio files — ripped CDs, purchased downloads, or any music collection on disk. It is not a streaming service client and does not connect to Spotify, Apple Music, or similar platforms. Files downloaded from those services are supported like any other audio files.

---

## Installation

### Prerequisites

- Python 3.12 or later
- Tkinter (ships with the python.org installer; on Ubuntu/Debian: `sudo apt install python3-tk`)
- Optional on Linux: `zenity` (GNOME) or `kdialog` (KDE) for native file dialogs

### Download

Download and extract the
[latest zip from GitHub](https://github.com/regregoryallen/ClassicalManager/archive/refs/heads/master.zip),
then follow the platform-specific instructions below. The extracted folder will
be named `ClassicalManager-master` — you can rename it to `ClassicalManager` if
you prefer.

Alternatively, if you have Git installed:
```bash
git clone https://github.com/regregoryallen/ClassicalManager.git
```

### Windows

**Install Python** from [python.org](https://www.python.org/downloads/). During
installation, check **"Add python.exe to PATH"** and leave **"tcl/tk and IDLE"**
checked (Tkinter, which the GUI requires, is included via that option).

Open the extracted folder and either use the batch scripts or set up manually:

#### Automated (recommended)

1. Double-click **`setup.bat`** — it checks your Python version, creates a virtual
   environment, installs dependencies, copies the config template, and offers to
   create a desktop shortcut.
2. Double-click **`run.bat`** (or the desktop shortcut) to launch the GUI.
3. For CLI usage, open a terminal in the folder:
   ```
   run.bat --cli scan --library "My Collection"
   ```

#### Manual

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python main.py
```

### Linux / macOS

On Ubuntu/Debian, install Tkinter if it is not already present:

```bash
sudo apt install python3-tk
```

Then open a terminal in the extracted folder and run:

```bash
cd ClassicalManager-master
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python main.py
```

### Dependencies

| Package | Purpose |
|---------|---------|
| customtkinter | Modern-looking GUI framework |
| peewee | SQLite ORM for the database |
| mutagen | Audio file metadata extraction |
| PlexAPI | Plex server integration (optional) |
| typer / rich | Command-line interface |

---

## Initial Setup

### 1. Configure Plex (optional)

If you plan to push playlists to a Plex server, open `config.json` (or use
**Settings** in the app) and fill in:

- **Server URL**: Your Plex server address (e.g., `http://192.168.1.100:32400`)
- **Token**: Your Plex authentication token
  ([how to find it](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/))
- **Music Section**: The name of your Plex music library (e.g., `Music`)
- **Path Rules**: If your music files are at different paths on the Plex server vs.
  your local machine, add find/replace rules (see [Settings](#settings))

### 2. Configure M3U Export (optional)

In the same config file or Settings dialog:

- **Path Style**: `absolute` (full file paths) or `relative_to_playlist` (paths
  relative to the M3U file's location)
- **Base Path**: Optional prefix prepended to absolute paths
- **Path Rules**: Find/replace rules for path translation, same format as Plex

### 3. Database Location

By default, the database is stored as `music_manager.db` in the project directory.
To change this, open **Settings** and set a new path. The change takes effect after
restarting the app.

---

## Getting Started

### Step 1: Create a Library

A library is a named collection of music with its own source folders, profiles, and
settings. You might have one for your main collection and another for holiday music.

1. Click **New** in the sidebar
2. Enter a name (e.g., "My Classical Collection")

### Step 2: Add Source Folders

Source folders are the root directories containing your music files. Every audio file
under these folders will be discovered during scanning.

1. Click **Add Folder**
2. Navigate to your music directory and select it
3. Repeat for additional folders if your collection spans multiple locations

### Step 3: Scan the Library

Click **Rescan Library**. The scanner will:

- Discover all supported audio files (MP3, FLAC, OGG, OPUS, M4A, WAV, WMA, AAC, etc.)
- Extract metadata: title, artist, album, composer, genre, conductor, ensemble,
  track/disc numbers, duration
- Read MusicBrainz identifiers if present
- Group tracks into albums (one album per folder)
- Detect multi-movement works using metadata and heuristics

The progress bar shows scanning progress. Large collections may take several minutes.
Click **Cancel Scan** to abort at any time.

When complete, the **Metrics** section in the sidebar shows counts of albums, works,
tracks, and composers found.

### Step 4: Browse Your Library

Switch to the **Explorer & Rules** tab:

- The left pane lists all albums with genre, year, and track count
- Click an album to see its works and tracks in the right pane
- The "Source" column shows how each work was detected:
  `mb_workid`, `work_tag`, `heuristic`, or `standalone`

### Step 5: Build a Playlist

Switch to the **Playlist Builder** tab:

1. In the Library pane (left), select albums, works, or tracks
2. Click **Add >>** (or double-click) to include them
3. The Playlist pane (right) shows what's included
4. Adjust settings: shuffle mode, work integrity, length limits
5. Click **Preview** to see the resolved playlist
6. Click **Export M3U**, **Export JSON**, or **Push to Plex**

### Step 6: Save Your Profile

Enter a name in the Profile field and click **Save**. Your rules and settings are
stored in the database and can be reloaded anytime with **Load**.

---

## The Sidebar

The sidebar (left panel) is always visible and manages library-level operations.

### Library Selector

The dropdown at the top lists all libraries. Selecting one loads its data into all
tabs.

### Library Management

| Button | Action |
|--------|--------|
| **New** | Create a library (prompts for name) |
| **Rename** | Rename the active library |
| **Delete** | Delete the library and all its data (confirmation required) |
| **Export Lib** | Export one or more libraries to JSON files (picker dialog when multiple libraries exist) |
| **Import Lib** | Load a library from a JSON file (handles name collisions automatically) |

### Metrics

Displays live counts for the active library: Albums, Works, Tracks, Composers.
Updated automatically after scans.

### Rescan Library

Rescans all source folders, rebuilding albums, works, and tracks from file metadata.
Overrides are preserved across rescans. During scanning, the button changes to
**Cancel Scan**.

### Scan Changes

Runs an incremental scan that only processes new, changed, or deleted files by
comparing each file's modification time and size against stored values. Much faster
than a full rescan for day-to-day updates.

Requires one prior full scan. Work detection re-runs only on albums that had changes.

### Re-detect Works

Re-runs all five work detection steps (override, MusicBrainz, WORK tag, heuristic,
standalone) using tag data already in the database, without rescanning files from disk.
Useful after editing overrides or when detection logic has been updated.

### Source Folders

Lists the root directories for the active library.

- **Add Folder**: Opens a directory picker to add a new source folder
- **Remove Folder**: Removes the selected folder (tracks from removed folders
  become orphans until the next rescan)

### Plex Section

An entry field to map this library to a specific Plex music library section, overriding
the default from config.json. Leave blank to use the default from Settings.

### Import Old Playlists

Imports plain-text playlist files (one album directory name per line). Each file
becomes a profile with album-level selections for matched albums. Useful for
migrating from a simpler playlist system.

### Bottom Buttons

- **Library Integrity Check**: Checks for orphaned tracks, unscanned files,
  duplicates, and cross-folder works
- **Track Similarity**: Opens the standalone Track Similarity Finder, where you pick
  seed tracks directly and browse audio-similar matches (see
  [Find Similar Tracks](#find-similar-tracks))
- **Profile Summary**: Sortable table of all profiles with counts and durations
- **Settings**: Opens the configuration dialog (see [Settings](#settings))
- **View Logs**: Shows application log output for the current session
- **Help**: Opens the in-app help window (see below)

### In-App Help

The **Help** button in the sidebar opens a searchable help window covering setup,
all tabs, settings, CLI usage, common patterns, and troubleshooting. The help window
stays open alongside the main app so you can refer to it while working.

Each tab also has a **?** button in its top-right corner that opens the help window
directly to the relevant section. If the help window is already open, clicking any
**?** button navigates to that section without opening a second window. A navigation
bar at the top of the help window lets you jump between all sections.

---

## Explorer & Rules Tab

This tab provides a browsable view of your library and lets you set include/exclude
rules.

### Album List (left pane)

- All albums sorted by title
- Columns: Album, Genre, Year, Tracks
- Use the filter field to narrow by album title, artist, or track metadata (genre,
  performer, conductor, ensemble). Filtering is live as you type.

### Works & Tracks (right pane)

Click an album to see its works and tracks in a hierarchical view.

- Columns: Name, Source (detection method), Composer, Tracks
- Works contain their constituent tracks as children

### Context Menus

Right-click any item for:

- **Play** (tracks only): Opens the audio file in your system's default player
- **Add Album/Work/Track**: Add to the playlist selection
- **Exclude Album/Work/Track**: Create an exception within a broader add

### Selections Display

The bottom section shows all active selections for the current profile. Select an
entry and click **Remove** to delete it. Selections are shared with the Playlist Builder tab.

---

## Playlist Builder Tab

The main workspace for creating playlists.

### Profile Management (top row)

- **Profile name**: Enter a name for your playlist profile
- **Load**: Pick from saved profiles to restore settings and rules
- **Save**: Save current settings and rules under the profile name
- **Delete**: Remove one or more saved profiles
- **Profile Summary**: Sortable table of all profiles with album, work, track,
  composer counts, and total duration

### Settings (second row)

| Setting | Values | Description |
|---------|--------|-------------|
| **Shuffle** | `track`, `work`, `album` | Unit of shuffling (see below) |
| **Integrity** | `enforce`, `respect_selection` | How partial works are handled |
| **Length** | `all`, `count`, `duration` | Playlist length limit |
| **Length value** | number or H:MM | Track count or duration (seconds, H:MM, or H:MM:SS) |
| **Seed** | number | Fixed seed for reproducible shuffles |
| **No repeats** | checkbox | Remove duplicate tracks |
| **Avoid adjacent** | checkboxes | Prevent consecutive items sharing the same composer, album, or musical form |

#### Shuffle Modes

- **track**: Fully random track order. Movements may be separated.
- **work**: Shuffle works as units. Movements within a work stay in order.
  Best for classical listening.
- **album**: Shuffle albums as units. Works and tracks within each album stay in
  their original order.

#### Work Integrity

- **enforce**: If any track from a work is selected, include the entire work in
  correct movement order. Ensures you never hear just one movement of a symphony.
- **respect_selection**: Play exactly what was selected, even if it means partial works.

#### Avoid Adjacent

Three optional constraints that prevent consecutive items from sharing the same attribute after shuffling:

- **Same Composer**: No two adjacent works by the same composer.
- **Same Album**: No two adjacent works from the same album.
- **Same Form**: No two adjacent works of the same musical form (e.g., two symphonies or two string quartets back-to-back).

These are best-effort: if the playlist is dominated by one composer, album, or form, some adjacencies are unavoidable. Works without a detected form (standalone tracks, non-classical music) never conflict on the form dimension, so they act as natural separators.

### Library Pane (left)

Browse the full library in a hierarchical tree: Albums > Works > Tracks.

- **Columns**: Name, Composer, Genre, Info (track count or duration)
- **Color coding**: Blue = included, Amber = partially included, Gray = excluded.
  A container (album or work) is blue when *every* track under it is included —
  including when you have added all of its children individually — and amber only
  when some, but not all, of its content is included.
- **Filter**: Type to narrow the view (case-insensitive, live filtering). Matches
  against name, composer, genre, performer, conductor, and ensemble at any level.
  Parents and children of matching items stay visible.
- **Hide 1-track**: Hides standalone (single-track) works. A gold warning appears
  when enabled to note that playlist items may be hidden.
- **+/−**: Expand or collapse all tree nodes (expands to work level, not individual
  tracks)
- **Column sorting**: Double-click any column header to sort; click again to reverse.
  An arrow indicator (▲/▼) appears next to the sorted column. Numeric values are
  sorted numerically.
- **Adding items**: Select one or more items and click **Add >>**, or double-click
  to toggle include/exclude state. Double-clicking an included item removes it;
  double-clicking an excluded or unselected item includes it.
- **Right-click**: Context menu with **Play** (tracks), **Details** (metadata popup),
  **Show Album** (full album view with editing), and **Show in profiles...** (list
  all saved profiles that include the selected item)

### Playlist Pane (right)

Shows only the items that will appear in your playlist. Tree expansion, sort order,
and scroll position are preserved when items are added or removed.

- **Filter**: Same text filter as the library pane, matching against the same fields
- **Column sorting**: Same double-click-to-sort behavior
- **Removing items**: Select and click **<< Remove**, or double-click
- **Right-click**: Same context menu as the library pane

### Action Buttons (bottom)

| Button | Description |
|--------|-------------|
| **Preview** | Dry-run showing the resolved playlist with track details and total duration |
| **Export M3U** | Save as an M3U playlist file |
| **Export JSON** | Save as a JSON file with full metadata |
| **Push to Plex** | Create or update a playlist on your Plex server (updates in place, preserving the playlist ID) |
| **Find Unused** | Populate the builder with all tracks not included in any saved profile. Creates an unnamed profile so you can browse, preview, and decide where items belong. |
| **Find Similar** | Find tracks that sound similar to your current selections (see below). Requires an audio analysis pass the first time. |

### Find Similar Tracks

**Find Similar** builds a Pandora-style search from your current selections. Every
track you have selected acts as a *seed*; the tool ranks the rest of the library by
audio similarity and lets you accept the matches you like back into the profile.
Accepting tracks widens the seed set, so the search broadens as you go.

The first time you run it, the library must be analyzed (a one-time audio pass per
track; the app prompts and shows progress). Analysis results are cached, so later
searches are fast.

Results appear in a popup with these controls:

- **Max results**: How many matches to return.
- **Volatility max**: Optional filter. Volatility measures how much a track varies
  internally (soft-to-loud, sparse-to-dense). Tick the checkbox next to the slider to
  *enable* the filter — moving the slider alone does nothing until it is enabled.
  Lower values keep more even, consistent tracks.
- **Blend**: Slides between *nearest* (rank by the single closest seed) and *consensus*
  (favor tracks that many seeds agree are close).

Each result row shows:

- **Match**: A percentage that is high when a track is as close to your seeds as your
  seeds already are to one another, decaying as it gets looser. It is self-calibrating
  per search, so it stays meaningful regardless of how broad your seed set is.
  Color-coded green (strong), amber (loose), red (weak).
- **Agreement**: How many of your seeds consider the track a close match (e.g. `12/31`).
- **Volatility**: The track's internal-variation score.

Actions:

- **Accept Selected / Accept All**: Add result tracks to the profile as track-level
  selections.
- **Re-search (include accepted)**: Re-run using the widened seed set.
- **Right-click** a result for **Play** or **Details** (metadata popup) to audition and
  inspect before accepting.

A standalone **Track Similarity Finder** is also available from the sidebar, where you
pick seed tracks directly rather than from the current profile.

### Pin to Position

You can pin specific works to fixed positions (1–5) at the start of a generated
playlist. This ensures a curated opening sequence regardless of shuffle settings.

1. In the **Playlist pane**, right-click a work
2. Select **Pin to position...** and choose a position (1–5)
3. The work is prefixed with **[#N]** and shown in orchid color

Pinned works are automatically added — no separate selection is needed. If a pinned
work isn't otherwise in the selection, it is added automatically.

To remove a pin, right-click the work and select **Remove pin**.

Pins are saved with the profile and persist across sessions.

---

## Cleanup / Overlay Tab

Review, correct, and manage work groupings and metadata overrides.

### Works Browser

The top section lists works with filtering and search controls:

- **Source dropdown**: Filter by detection method — All Works, Heuristic, Standalone,
  Override, MB Work ID, or Work Tag
- **Search field**: Live filtering by work name, album title, or composer
- **Hide 1-track**: Hides standalone works to focus on multi-track groupings
  (enabled by default)
- **+/−**: Expand or collapse all tree nodes
- **Multi-select**: Ctrl+click or Shift+click to select multiple works

Works are shown hierarchically with their tracks as children. Columns: Name, Source,
Album, Tracks, Composer.

### Right-Click Context Menu

- **Play** (tracks only): Opens the audio file in your system's default player
- **Details**: Read-only popup showing all work and track metadata (names, paths,
  MB IDs, durations, and per-track volatility once analyzed) with copy buttons
- **Show Album**: Opens the album popup (see below)
- **Set Work Name / Group Key / Composer**: Focuses the corresponding edit field
- **Make Standalone**: Sets `__standalone__` group key for all tracks in the selected
  work(s), suppressing erroneous groupings on the next re-detect

### Edit Section

Operates on all selected works:

- **Set Work Name**: Set the work name for selected tracks. Tracks sharing the same
  work name are grouped into a single work on re-detect or rescan.
- **Make Standalone**: Marks tracks as standalone, forcing each track into
  its own work and bypassing all detection. Useful for suppressing incorrect WORK
  tags or MB work IDs.
- **Set Composer**: Override the composer for all tracks in the selected works
- **Show Album**: Opens the album popup for the selected work's album

### Show Album Popup

A detailed album view for inspecting and editing:

- **Album header**: Edit album title, artist, and year (creates album-scope overrides)
- **Works/Tracks tree**: All works with tracks as children; multi-select enabled.
  Right-click a track to **Play** it.
- **Track actions**: Set Group Key, Work Name, or Composer for selected tracks.
  **Make Standalone** sets `__standalone__` for selected tracks.
- Selection count shows how many tracks are currently selected

### Current Overrides

The bottom section lists all metadata overrides for the active library with a live
search field.

Overrides are non-destructive: they modify database values without touching your
audio files and survive rescans (applied automatically after each scan).

Supported override fields:

| Scope | Fields |
|-------|--------|
| Track | composer, work_name, disc_number, track_number, movement_number, title, genre, performer, conductor, ensemble |
| Album | album_title, album_artist, year |

Use **Export Overrides JSON** and **Import Overrides JSON** to back up or share
your corrections.

---

## Settings

The Settings dialog (accessible from the sidebar) configures application-wide options.
All changes are saved to `config.json`.

### Database

- **Database File**: Path to the SQLite database. Both the GUI and CLI read this from
  `config.json`. Changing the path requires a restart. To move the database, copy the
  `.db` file (and any `-wal`/`-shm` files) to the new location, then update this
  setting.

### Plex

- **Server URL**: Plex server address (e.g., `http://192.168.1.100:32400`)
- **Token**: Plex authentication token (stored in config.json)
- **Token Env Var**: Name of an environment variable holding the token (e.g.,
  `PLEX_TOKEN`). Preferred over a plaintext token for security.
- **Default Section**: Default Plex music library name. Overridden by the per-library
  Plex Section field in the sidebar.

### Plex Path Rules

If your music files are at different paths on the Plex server vs. your local machine,
add rewrite rules. Format: one rule per line, `find -> replace`.

Example — local path `/home/user/Music`, Plex sees `/mnt/MediaLib/Music`:
```
/home/user/Music -> /mnt/MediaLib/Music
```

All paths are stored internally with forward slashes, even on Windows. Use forward
slashes in the `find` portion:
```
C:/Users/jane/Music -> /volume1/Music
```

### M3U Export

- **Path Style**: `absolute` for full paths, `relative_to_playlist` for paths
  relative to the M3U file's location
- **Base Path**: Optional prefix for absolute paths
- **Path Rules**: Same find/replace format as Plex, applied to M3U output paths.
  Use forward slashes on all platforms.

---

## Command-Line Interface

The CLI provides the same core functionality for scripting and automation.

```bash
# Linux/macOS — activate your virtual environment first
source venv/bin/activate
python main.py --cli <command> [options]
```

```
:: Windows — use run.bat or activate manually
run.bat --cli <command> [options]

:: or
venv\Scripts\activate
python main.py --cli <command> [options]
```

### Commands

#### scan
Full rescan of a library's source folders.
```
python main.py --cli scan --library "My Collection" [-v] [-q]
```

#### scan-changes
Incremental scan: only processes new, changed, or deleted files. Compares file
modification time and size against stored values. Much faster than a full rescan.
Requires one prior full scan.
```
python main.py --cli scan-changes --library "My Collection" [-v] [-q]
```

#### redetect
Re-run all work detection steps from tag data already in the database, without
reading audio files.
```
python main.py --cli redetect --library "My Collection" [-v] [-q]
```

#### preview
Dry-run a profile without writing files.
```
python main.py --cli preview --profile "Sunday Classical" [-v]
```

#### generate
Generate and export a playlist.
```
python main.py --cli generate --profile "Sunday" --format m3u --output playlist.m3u
python main.py --cli generate --profile "Sunday" --format json --output playlist.json
python main.py --cli generate --profile "Sunday" --target plex
```

#### generate-all
Generate playlists for all profiles in a library.
```
python main.py --cli generate-all --library "My Collection" --output-dir ./playlists [-q]
python main.py --cli generate-all --library "My Collection" --target plex [-q]
```

#### integrity
Run integrity checks on a library. Reports orphaned tracks, unscanned files,
duplicates, and cross-folder works.
```
python main.py --cli integrity --library "My Collection" [-v]
```

#### overrides
Export or import metadata overrides.
```
python main.py --cli overrides export --library "My Collection" --output overrides.json
python main.py --cli overrides import --library "My Collection" --input overrides.json
```

#### webhook
Start the webhook HTTP service for remote job submission (e.g., from Home
Assistant). See [Webhook Service](#webhook-service) below for full details.
```
python main.py --cli webhook [--library "My Collection"] [--host 0.0.0.0] [--port 5588] [-v]
```

### Global Options

| Flag | Description |
|------|-------------|
| `--config PATH` | Use a custom config.json file (default: `<install_dir>/config.json`) |

The `--config` flag works with any command (including the GUI). It must appear
before `--cli`:

```bash
python main.py --config /path/to/alt-config.json --cli generate-all --library "My Collection" --target plex
```

### Common Flags

| Flag | Description |
|------|-------------|
| `-v` / `--verbose` | Debug-level logging |
| `-q` / `--quiet` | Suppress progress output; errors only (ideal for cron jobs) |
| `-h` / `--help` | Print usage summary |

---

## Usage Patterns

### Building an All-Composer Playlist

1. Go to the **Playlist Builder** tab
2. Type the composer's name in the Library **Filter** box (e.g., "Beethoven")
3. Select all visible albums and click **Add >>**
4. Set Shuffle to **work**, Integrity to **enforce**
5. Preview and export

### Creating a Time-Limited Playlist

1. Add your desired albums/works to the playlist
2. Set Length to **duration** and enter a value: `1:00` for one hour, `2:30` for
   2.5 hours, or a plain number for seconds (e.g., `3600`)
3. Set a **Seed** value for a reproducible selection
4. Export

### Filtering by Genre or Performer

Use the filter field in the Playlist Builder to search by genre (e.g., "chamber"),
performer, conductor, or ensemble name. The filter matches against all of these
metadata fields, not just the displayed name.

### Managing Multiple Plex Sections

1. Create separate libraries (e.g., "Classical", "Christmas")
2. Set the **Plex Section** field in the sidebar to the corresponding Plex library
   name for each
3. Playlists automatically target the correct Plex section when pushed

### Correcting Work Grouping

If the scanner grouped tracks incorrectly:

1. Go to the **Cleanup / Overlay** tab
2. Use the **Source** dropdown to filter by detection method
3. Find the work and right-click > **Show Album** to see the full album context
4. To merge tracks into one work: select tracks, set the same **Group Key** for all
5. To split an incorrect grouping: select the work(s) and click **Make Standalone**
6. Click **Re-detect Works** in the sidebar to apply

### Suppressing Erroneous Work Tags

Some files have incorrect WORK tags (e.g., "PMEDIA" from bulk tagging tools):

1. Switch the Source dropdown to **Work Tag** or **MB Work ID**
2. Multi-select the incorrect works (Ctrl+click or Shift+click)
3. Click **Make Standalone**
4. Click **Re-detect Works** to apply

### Migrating from Simple Playlists

If you have text files listing album directories (one per line):

1. Click **Import Old Playlists** in the sidebar
2. Select your text files
3. Each file becomes a profile with album-level selections for matched albums
4. Load the profile in the Playlist Builder to review and adjust

### Backing Up Your Library

**Export Lib** exports libraries to JSON files. When multiple libraries exist, a
picker dialog lets you choose which ones to export (with All/None buttons).
Multiple libraries are saved as separate files in a chosen directory.
**Import Lib** restores a library from a JSON file on the same or a different
machine. Source folders must exist at the same paths (or be updated after import)
for rescanning to work.

### Sharing a Database Across Systems

You can place the database on a shared drive (set `db_path` in `config.json`) and
access it from multiple machines — but only run the app on one machine at a time.
SQLite does not support concurrent access over network filesystems.

If the app cannot open the database (locked by another instance, network share
unmounted), it shows a diagnostic message. The GUI offers the option to fall back
to the local default database; the CLI exits with an error.

If source folders are at different paths on each machine (e.g., `/mnt/Music` on
Linux vs. `M:/Music` on Windows), scan from only one machine. The other machine
can generate playlists using path rules to translate paths for its target.

---

## Configuration Reference

### config.json

```json
{
  "active_library": 1,
  "db_path": "/path/to/music_manager.db",
  "targets": {
    "plex": {
      "base_url": "http://server:32400",
      "token": "your-token",
      "token_env": "PLEX_TOKEN",
      "music_section": "Music",
      "path_rules": [
        {"find": "/local/path", "replace": "/server/path"}
      ]
    },
    "m3u": {
      "path_style": "absolute",
      "base_path": "",
      "path_rules": []
    }
  },
  "cron": {
    "library": "My Collection",
    "mode": "plex",
    "profile": "",
    "m3u_output_dir": "~/Playlists",
    "verbosity": "-q"
  },
  "webhook": {
    "host": "0.0.0.0",
    "port": 5588,
    "library": "My Collection",
    "allowed_commands": ["plex", "scan", "scan+plex", "scan+m3u", "m3u"]
  }
}
```

| Field | Notes |
|-------|-------|
| `db_path` | Optional. Omit or leave empty for the default (`music_manager.db` in the project directory). Both GUI and CLI read this. |
| `targets.plex` | Omit entirely if you don't use Plex. At least one of `token` or `token_env` is required. |
| `targets.plex.music_section` | Optional if set per-library in the sidebar. |
| `targets.m3u` | Controls M3U export path style and rewriting. |
| `cron` | Optional. Settings for the cron companion script. See [Cron Automation](#cron-automation). |
| `cron.library` | Library name. Falls back to `active_library` if omitted. |
| `cron.mode` | One of: `plex`, `m3u`, `scan`, `scan+plex`, `scan+m3u`. Default: `plex`. |
| `cron.profile` | Single profile name. Empty = all profiles. |
| `cron.m3u_output_dir` | Output directory for M3U mode. Default: `~/Playlists`. |
| `cron.verbosity` | `-q` (quiet, default), `` (normal), or `-v` (verbose). |
| `webhook` | Optional. Settings for the webhook service. See [Webhook Service](#webhook-service). |
| `webhook.host` | Bind address. Default: `0.0.0.0` (all interfaces). |
| `webhook.port` | Listen port. Default: `5588`. |
| `webhook.library` | Library name. Falls back to `active_library` if omitted. |
| `webhook.allowed_commands` | List of allowed commands. Default: all five modes. |

### gui_prefs.json (auto-managed)

Stores window geometry and last-used export directory. Do not edit manually.

### Supported Audio Formats

MP3, FLAC, OGG, OPUS, M4A, MP4, WAV, WMA, AAC, ALAC, APE, WavPack (.wv)

---

## Cron Automation

The cron companion script (`classical-manager-cron.sh`) runs CLI commands on a
schedule. It reads its settings from the `cron` section of `config.json`.

### Setup

1. Add a `cron` section to `config.json` (or use the installer):

```json
"cron": {
  "library": "My Collection",
  "mode": "plex"
}
```

2. Add to crontab:

```bash
crontab -e
# Push all playlists to Plex every night at 2 AM:
0 2 * * * /home/user/.local/share/classical-manager/classical-manager-cron.sh
```

### Modes

| Mode | Action |
|------|--------|
| `plex` | Push all playlists to Plex (default) |
| `m3u` | Generate M3U playlist files |
| `scan` | Incremental scan only |
| `scan+plex` | Scan, then push to Plex |
| `scan+m3u` | Scan, then generate M3U files |

### Multiple Configurations

Use `--config` to point at different config files for different schedules:

```bash
0 2 * * * /path/to/classical-manager-cron.sh --config /path/to/nightly.json
0 * * * * /path/to/classical-manager-cron.sh --config /path/to/hourly.json
```

---

## Webhook Service

The webhook service is a lightweight HTTP server that accepts remote commands to
trigger playlist operations. It is designed for Home Assistant integration but
works with any HTTP client. No authentication is required (local network use).

> **Linux only.** The webhook service and its systemd integration require Linux.
> It is not supported on Windows or macOS.

### Starting the Service

```bash
# Start manually:
python main.py --cli webhook --library "My Collection" -v

# Or use the installed CLI:
classical-manager --cli webhook
```

CLI options override config.json values:

| Option | Default | Description |
|--------|---------|-------------|
| `--library NAME` | from config | Library to operate on |
| `--host ADDR` | `0.0.0.0` | Bind address |
| `--port PORT` | `5588` | Listen port |
| `-v` | off | Verbose logging |

### Running as a systemd Service

The installer can set this up automatically. To configure manually:

1. Copy the service template:

```bash
mkdir -p ~/.config/systemd/user
cp classical-manager-webhook.service ~/.config/systemd/user/
```

2. Edit the file and replace `%INSTALL_DIR%` with your install path
   (e.g., `/home/user/.local/share/classical-manager`).

3. Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now classical-manager-webhook
```

4. Check status:

```bash
systemctl --user status classical-manager-webhook
journalctl --user -u classical-manager-webhook -f
```

### API Reference

All responses are JSON. The service runs one job at a time.

#### GET /api/health

Returns service status and configuration.

```bash
curl http://localhost:5588/api/health
```

```json
{
  "status": "ok",
  "library": "My Collection",
  "allowed_commands": ["m3u", "plex", "scan", "scan+m3u", "scan+plex"]
}
```

#### POST /api/jobs

Submit a job. The request body must contain a `command` field.

```bash
curl -X POST http://localhost:5588/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"command": "plex"}'
```

To target a single profile instead of all profiles:

```bash
curl -X POST http://localhost:5588/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"command": "plex", "profile": "Morning Mix"}'
```

**Commands:** `plex`, `scan`, `scan+plex`, `scan+m3u`, `m3u` (same as cron modes).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | One of the commands listed above. |
| `profile` | string | no | Run for a single profile instead of all profiles. |
| `quiet` | boolean | no | Suppress progress output (default: `false`). |

**Responses:**

| Status | Meaning |
|--------|---------|
| 202 Accepted | Job started. Body contains job `id`, `command`, `quiet`, `status`, `started_at`. |
| 400 Bad Request | Missing or invalid `command`. |
| 409 Conflict | A job is already running. |

```json
{
  "id": "a1b2c3d4e5f6",
  "command": "plex",
  "quiet": false,
  "status": "running",
  "started_at": "2026-07-06T02:00:00"
}
```

#### GET /api/jobs/current

Returns the currently running job, or 404 if idle.

```bash
curl http://localhost:5588/api/jobs/current
```

#### GET /api/jobs/last

Returns the last completed job, including exit code and output.

```bash
curl http://localhost:5588/api/jobs/last
```

```json
{
  "id": "a1b2c3d4e5f6",
  "command": "plex",
  "quiet": false,
  "status": "completed",
  "started_at": "2026-07-06T02:00:00",
  "finished_at": "2026-07-06T02:01:23",
  "exit_code": 0,
  "output": "Pushed playlist 'Morning Mix' to Plex\n..."
}
```

### Home Assistant Integration

Add a `rest_command` to your Home Assistant `configuration.yaml`:

```yaml
rest_command:
  classical_manager_plex:
    url: "http://CM_HOST:5588/api/jobs"
    method: POST
    content_type: "application/json"
    payload: '{"command": "plex"}'

  classical_manager_scan_plex:
    url: "http://CM_HOST:5588/api/jobs"
    method: POST
    content_type: "application/json"
    payload: '{"command": "scan+plex"}'
```

Replace `CM_HOST` with the IP or hostname of the machine running Classical Manager.

Use in automations:

```yaml
automation:
  - alias: "Rebuild playlists nightly"
    trigger:
      - platform: time
        at: "02:00:00"
    action:
      - service: rest_command.classical_manager_plex

  - alias: "Scan and push on button press"
    trigger:
      - platform: state
        entity_id: input_button.rebuild_playlists
    action:
      - service: rest_command.classical_manager_scan_plex
```

To check job status from HA, use a `rest` sensor:

```yaml
sensor:
  - platform: rest
    name: Classical Manager Last Job
    resource: "http://CM_HOST:5588/api/jobs/last"
    value_template: "{{ value_json.status }}"
    json_attributes:
      - command
      - exit_code
      - finished_at
      - output
    scan_interval: 60
```

---

## Troubleshooting

### "No module named customtkinter"

Run `pip install -r requirements.txt` inside your virtual environment. On Windows,
run `setup.bat` to install all dependencies automatically.

### setup.bat says "Python is not installed"

Install Python 3.12+ from [python.org](https://www.python.org/downloads/). Make sure
to check **"Add python.exe to PATH"** during installation. If you installed Python
after opening the terminal, close and reopen it so the PATH takes effect.

### File dialogs look different on Linux

The app uses zenity (GNOME) or kdialog (KDE) for native file dialogs. If neither is
installed, it falls back to Tkinter's built-in dialogs:
```bash
sudo apt install zenity
```

### Plex push fails with "section not found"

The Plex Section name must match exactly (case-sensitive) with your Plex library name.
Check the per-library section in the sidebar and the default in Settings.

### Plex push fails with unmatched tracks

Path rules may not correctly translate local paths to Plex server paths. Click
**View Logs** to see which tracks failed. Adjust path rules in Settings.

### M3U shows wrong paths / Plex says "no tracks matched" on a different OS

Plex path rules and M3U path rules serve **different purposes** and must be
configured independently:

- **Plex path rules** translate database paths to what the **Plex server** sees.
  If the Plex server uses the same paths that were scanned (e.g., both are
  `/mnt/MediaLib/...`), no Plex rules are needed.
- **M3U path rules** translate database paths to what the **local machine** sees.
  If you're exporting M3U on Windows but the library was scanned on Linux, you
  need an M3U rule like `/mnt/MediaLib -> M:`.

A common mistake when running on a different OS than where the scan was done:
putting the local path translation in the Plex rules instead of the M3U rules.
This breaks Plex (which needs server paths, not local paths) and leaves M3U
untranslated.

**Example — library scanned on Linux at `/mnt/MediaLib`, Plex server at the
same path, Windows maps the share as `M:`:**

```json
"plex": {
  "path_rules": []
},
"m3u": {
  "path_rules": [
    {"find": "/mnt/MediaLib", "replace": "M:"}
  ]
}
```

### Works grouped incorrectly

Go to the **Cleanup / Overlay** tab. Use the Source dropdown to filter by detection
method and the search field to find specific works. Right-click > **Details** to
inspect metadata, or **Show Album** for the full album context.

Use **Set Group Key** to merge tracks, or **Make Standalone** to split them. Click
**Re-detect Works** to apply changes without a full rescan.

### Scan takes too long

Large collections may take several minutes for a full scan. Use **Scan Changes** for
routine updates — it only processes new, changed, or deleted files. Either scan type
can be cancelled mid-operation.

### "Cannot open database" or "disk I/O error"

The database file is likely locked by another instance or the network share is not
mounted. Close the app on all other machines and verify the share is accessible. The
GUI offers to fall back to the local default database.

### Database path change not taking effect

Database path changes require an application restart. Close and reopen the app.

### Console window appears briefly on Windows

When launching via the desktop shortcut, a console window may appear minimized
briefly while the batch script activates the virtual environment. This is normal
and closes automatically once the GUI loads.
