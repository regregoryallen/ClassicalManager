# Classical Music Playlist Manager - User Guide

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

Classical Music Playlist Manager is a desktop application designed for managing and
generating playlists from classical music collections. Unlike general-purpose playlist
tools, it understands the structure of classical music: multi-movement works, composers,
and the relationship between tracks within a work.

Key capabilities:

- **Automatic work detection** from MusicBrainz tags, WORK/MOVEMENT metadata, or
  title-prefix heuristics
- **Work-aware shuffling** that keeps movements together in the correct order
- **Include/exclude rules** at the composer, album, work, or track level
- **Export to M3U, JSON, or Plex** with configurable path rewriting
- **Non-destructive metadata overrides** to correct grouping without modifying files
- **Multiple libraries** to organize distinct collections (e.g., classical, holiday)

---

## Installation

### Prerequisites

- Python 3.12 or later
- Tkinter (included with most Python installations; on Ubuntu/Debian: `sudo apt install python3-tk`)
- For Linux: `zenity` (GNOME) or `kdialog` (KDE) for native file dialogs (optional but recommended)

### Steps

1. Clone or download the project:
   ```bash
   git clone <repository-url>
   cd ClassicalManager
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate    # Linux/macOS
   venv\Scripts\activate       # Windows
   pip install -r requirements.txt
   ```

3. Create your configuration file from the template:
   ```bash
   cp config.example.json config.json
   ```

4. Launch the application:
   ```bash
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
- **Path Rules**: If your music files are at different paths on the Plex server than
  on your local machine, add find/replace rules

### 2. Configure M3U Export (optional)

In the same config file or Settings dialog:

- **Path Style**: `absolute` (full paths) or `relative_to_playlist` (paths relative to
  the M3U file location)
- **Base Path**: Optional prefix prepended to absolute paths
- **Path Rules**: Same find/replace as Plex, for path translation

### 3. Database Location

By default, the database is stored as `music_manager.db` in the project directory.
To change this, open **Settings** and set a new database file path. Changes take
effect after restarting the app.

---

## Getting Started

This walkthrough covers the most common first-time workflow.

### Step 1: Create a Library

A library is a named collection of music with its own source folders, profiles, and
settings. You might have one for your main collection and another for holiday music.

1. Click **New** in the sidebar
2. Enter a name (e.g., "My Classical Collection")

### Step 2: Add Source Folders

Source folders are the root directories where your music files live. Every audio file
under these folders will be discovered during scanning.

1. Click **Add Folder**
2. Navigate to your music directory and select it
3. Repeat for additional folders if your collection spans multiple locations

### Step 3: Scan the Library

Click **Rescan Library**. The scanner will:

- Discover all audio files (MP3, FLAC, OGG, OPUS, M4A, WAV, WMA, AAC, and more)
- Extract metadata: title, artist, album, composer, track/disc numbers, duration
- Read MusicBrainz identifiers if present
- Group tracks into albums (one album per folder)
- Detect multi-movement works using metadata and heuristics

The progress bar and status text show scanning progress. For large collections,
this may take a few minutes. You can click **Cancel Scan** to abort.

When complete, the **Metrics** section shows counts of albums, works, tracks, and
composers found.

### Step 4: Browse Your Library

Switch to the **Explorer & Rules** tab to browse what was scanned:

- The left pane lists all albums
- Click an album to see its works and tracks in the right pane
- The "Source" column shows how each work was detected:
  `mb_workid`, `work_tag`, `heuristic`, or `standalone`

### Step 5: Build a Playlist

Switch to the **Playlist Builder** tab:

1. In the Library pane (left), select albums, works, or tracks you want
2. Click **Add >>** to include them (or double-click)
3. The Playlist pane (right) shows what's included
4. Adjust settings: shuffle mode, work integrity, length limits
5. Click **Preview** to see the resolved playlist
6. Click **Export M3U**, **Export JSON**, or **Push to Plex** to output it

### Step 6: Save Your Profile

Enter a name in the Profile field and click **Save**. Your rules and settings are
stored in the database and can be reloaded anytime with **Load**.

---

## The Sidebar

The sidebar (left panel) is always visible and manages library-level operations.

### Library Selector

The dropdown at the top lists all libraries. Selecting one loads its data into all
tabs. The **(none)** option appears when no libraries exist.

### Library Management

| Button | Action |
|--------|--------|
| **New** | Create a library (prompts for name) |
| **Rename** | Rename the active library |
| **Delete** | Delete the library and all its data (confirmation required) |
| **Export Lib** | Save the entire library to a JSON file (structure, profiles, overrides) |
| **Import Lib** | Load a library from a JSON file (auto-handles name collisions) |

### Metrics

Displays live counts for the active library: Albums, Works, Tracks, Composers.
Updated automatically after scans and data changes.

### Rescan Library

Rescans all source folders, rebuilding albums, works, and tracks from file metadata.
Overrides are preserved across rescans. During scanning, the button changes to
**Cancel Scan**.

### Scan Changes

Runs an incremental scan that only processes new, changed, or deleted files. Compares
each file's modification time and size against stored values to skip unchanged files.
Much faster than a full rescan for day-to-day library maintenance.

Requires one prior full scan to populate file metadata. Work detection is re-run only
on albums that had changes.

### Re-detect Works

Re-runs all five work detection steps (override, MusicBrainz, WORK tag, heuristic,
standalone) using tag data already stored in the database, without rescanning files
from disk. This is much faster than a full rescan and is useful after correcting
overrides or when detection logic has been updated.

### Source Folders

Lists the root directories for the active library.

- **Add Folder**: Opens a directory picker to add a new source folder
- **Remove Folder**: Removes the selected folder (tracks from removed folders
  become orphans until the next rescan)

### Plex Section

An entry field to map this library to a specific Plex music library section. This
overrides the default section from config.json, allowing different libraries to push
to different Plex sections.

Leave blank if you don't use Plex or want to use the default from Settings.

### Import Old Playlists

Imports plain-text playlist files (one album directory name per line). Each file
becomes a profile with include rules for matched albums. Useful for migrating from
a simpler playlist system.

### Bottom Buttons

- **Library Integrity Check**: Runs integrity checks (orphaned tracks, unscanned
  files, duplicates, cross-folder works) and displays a report
- **Profile Summary**: Shows a sortable table of all profiles with counts and durations
- **Settings**: Opens the configuration dialog (see [Settings](#settings))
- **View Logs**: Opens a window showing application log output, useful for
  troubleshooting scan or Plex errors

---

## Explorer & Rules Tab

This tab provides a browsable view of your library and lets you build include/exclude
rules.

### Album List (left pane)

- Shows all albums sorted by title
- Columns: Album name, Year, Track count
- Use the filter field at the top to narrow by album title or artist (live filtering
  as you type)

### Works & Tracks (right pane)

- Click an album to see its works and individual tracks
- Hierarchical view: Works contain tracks
- Columns: Name, Source (how the work was detected), Composer, Track count

### Context Menus

Right-click on any item to include or exclude it:

- **Play** (tracks only): Opens the audio file in your system's default music player
- **Include Album/Work/Track**: Add an include rule
- **Exclude Album/Work/Track**: Add an exclude rule

### Rules Display

The bottom section shows all active rules. Select a rule and click **Remove** to
delete it. Rules created here are shared with the Playlist Builder tab.

---

## Playlist Builder Tab

This is the main workspace for creating playlists.

### Profile Management (top row)

- **Profile name**: Enter a name for your playlist profile
- **Load**: Pick from saved profiles to restore settings and rules
- **Save**: Save current settings and rules under the profile name
- **Delete**: Remove one or more saved profiles
- **Profile Summary**: Opens a popup showing a sortable table of all profiles with
  album, work, track, composer counts, and total duration

### Settings (second row)

| Setting | Values | Description |
|---------|--------|-------------|
| **Shuffle** | `track`, `work`, `album` | Unit of shuffling (see below) |
| **Integrity** | `enforce`, `respect_selection` | How partial works are handled |
| **Length** | `all`, `count`, `duration` | Playlist length limit |
| **Length value** | number or H:MM | Track count or duration (seconds, H:MM, or H:MM:SS) |
| **Seed** | number | Fixed seed for reproducible shuffles |
| **No repeats** | checkbox | Remove duplicate tracks |

#### Shuffle Modes

- **track**: Fully random track order. Movements may be separated.
- **work**: Shuffle works as units. Movements within a work stay in order.
  Best for classical listening.
- **album**: Shuffle albums as units. Works and tracks within each album stay in
  their original order.

#### Work Integrity

- **enforce**: If any track from a work is selected, include the entire work in
  correct movement order. This ensures you never hear just one movement of a symphony.
- **respect_selection**: Play exactly what was selected, even if it means partial works.

### Library Pane (left)

Browse the full library with a hierarchical tree: Albums > Works > Tracks.

- **Columns**: Name, Composer (album artist for albums, work/track composer), Info
  (track count or duration)
- **Color coding**: Blue = included, Amber = partially included, Gray = excluded
- **Filter**: Type in the filter box to narrow the view (live filtering, case-insensitive,
  matches at any level). Parents and children of matching items stay visible.
- **Hide 1-track**: Checkbox to hide single-track (standalone) works (default off).
  A gold warning appears when enabled to note that playlist items may be hidden.
- **+/−**: Expand or collapse all tree nodes (expands to work level only, not
  individual tracks)
- **Column sorting**: Double-click any column header to sort. Click again to reverse.
  An ▲ or ▼ indicator appears next to the sorted column name. Numeric values
  (track counts, durations, years) are sorted numerically.
- **Add items**: Select one or more items and click **Add >>**, or double-click
  (double-clicking the expand/collapse arrow does not trigger add)
- **Right-click**: Context menu with **Play** (tracks), **Details...** (work/track
  details popup), and **Show Album** (full album view with editing)

### Playlist Pane (right)

Shows only the items that will be in your playlist. Tree expansion, sort order,
and scroll position are preserved when items are added or removed.

- **Filter**: Same text filter as the library pane
- **Column sorting**: Same double-click-to-sort as the library pane
- **Remove items**: Select and click **<< Remove**, or double-click
- **Right-click**: Same Play/Details/Show Album context menu as the library pane

### Action Buttons (bottom)

| Button | Description |
|--------|-------------|
| **Preview** | Dry-run showing the resolved playlist with track details and total duration |
| **Export M3U** | Save as an M3U playlist file |
| **Export JSON** | Save as a JSON file with full metadata |
| **Push to Plex** | Create or update a playlist on your Plex server |

---

## Cleanup / Overlay Tab

This tab is for reviewing, correcting, and managing work groupings and metadata
overrides across your library.

### Works Browser

The top section lists works with filtering and search controls:

- **Source dropdown**: Filter by detection method — Heuristic, Standalone, All Works,
  Override, MB Work ID, or Work Tag
- **Search field**: Live filtering by work name, album title, or composer
- **Hide 1-track checkbox**: Hides standalone (single-track) works to focus on
  multi-track groupings (enabled by default)
- **+/−**: Expand or collapse all tree nodes
- **Multi-select**: Use Ctrl+click or Shift+click to select multiple works

Works are shown hierarchically with their tracks as children. Columns: Name, Source,
Album, Tracks, Composer.

### Right-Click Context Menu

Right-click any work or track in the browser for:

- **Play** (tracks only): Opens the audio file in your system's default music player
- **Details...**: Opens a read-only popup showing all work and track metadata
  (names, paths, MB IDs, durations) with copy buttons for work name and MB work ID
- **Show Album**: Opens the album popup (see below)
- **Set Work Name/Group Key/Composer**: Focuses the corresponding edit field
- **Make Standalone**: Sets `__standalone__` group key for all tracks in the selected
  work(s), suppressing erroneous groupings on the next re-detect

### Edit Section

Edit controls that operate on all selected works:

- **Set Work Name**: Change the display name (creates a `work_name` override)
- **Set Group Key**: Assign a `work_group_key` override to control grouping.
  Requires re-detect or rescan to take effect.
- **Make Standalone**: Marks tracks with a special `__standalone__` group key that
  forces each track into its own standalone work, bypassing all detection steps.
  Useful for suppressing erroneous WORK tags or MB work IDs.
- **Set Composer**: Override the composer for all tracks
- **Show Album**: Opens the Show Album popup for the selected work's album

### Show Album Popup

A detailed album view for inspecting and editing all works and tracks in an album:

- **Album header**: Edit album title, artist, and year (creates album-scope overrides)
- **Works/Tracks tree**: Shows all works with tracks as children, multi-select enabled.
  Right-click a track to **Play** it in your default music player.
- **Track actions**: Set Group Key, Work Name, or Composer for selected tracks.
  A **Make Standalone** button sets `__standalone__` for selected tracks.
- Selection count shows how many tracks are currently selected

### Current Overrides

The bottom section lists all metadata overrides for the active library with a live
search field for filtering.

Overrides are non-destructive: they modify database values without touching your
audio files. They survive rescans (applied automatically after each scan).

Supported override fields:

| Scope | Fields |
|-------|--------|
| Track | composer, work_group_key, work_name, disc_number, track_number, movement_number, title |
| Album | album_title, album_artist, year |

Use **Export Overrides JSON** and **Import Overrides JSON** to back up or share
your corrections.

---

## Settings

The Settings dialog (accessible from the sidebar) configures application-wide options.
All changes are saved to `config.json`.

### Database

- **Database File**: Path to the SQLite database file. Changing this requires a
  restart. Use the browse button to select a location.

### Plex

- **Server URL**: Plex server address (e.g., `http://192.168.1.100:32400`)
- **Token**: Plex authentication token (stored in config.json)
- **Token Env Var**: Alternative: name of an environment variable holding the token
  (e.g., `PLEX_TOKEN`). Preferred for security.
- **Default Section**: Default Plex music library name. Overridden by the per-library
  Plex Section field in the sidebar.

### Plex Path Rules

If your music files are at different paths on the Plex server than on your local
machine, add path rewrite rules. Format: one rule per line, `find -> replace`.

Example: if your local path is `/home/user/Music` but Plex sees `/mnt/MediaLib/Music`:
```
/home/user/Music -> /mnt/MediaLib/Music
```

### M3U Export

- **Path Style**: `absolute` for full paths, `relative_to_playlist` for paths
  relative to the M3U file's location
- **Base Path**: Optional prefix for absolute paths
- **Path Rules**: Same find/replace format as Plex, applied to M3U output paths

---

## Command-Line Interface

The CLI provides the same core functionality for scripting and automation.

```bash
# Activate your virtual environment first
source venv/bin/activate

# All CLI commands use the --cli flag
python main.py --cli <command> [options]
```

### Commands

#### scan
Full rescan of a library's source folders.
```bash
python main.py --cli scan --library "My Collection" [-v] [-q]
```

#### scan-changes
Incremental scan: only processes new, changed, or deleted files.
```bash
python main.py --cli scan-changes --library "My Collection" [-v] [-q]
```
Compares file modification time and size against stored values. Much faster than
a full rescan for routine updates. Requires one prior full scan.

#### redetect
Re-run all work detection steps using tag data stored in the database.
```bash
python main.py --cli redetect --library "My Collection" [-v] [-q]
```
Much faster than a full rescan. Re-runs all five detection steps (override,
MusicBrainz, WORK tag, heuristic, standalone) without reading audio files.

#### preview
Dry-run a profile without writing files.
```bash
python main.py --cli preview --profile "Sunday Classical" [-v]
```

#### generate
Generate and export a playlist.
```bash
# Export to M3U
python main.py --cli generate --profile "Sunday Classical" --format m3u --output playlist.m3u

# Export to JSON
python main.py --cli generate --profile "Sunday Classical" --format json --output playlist.json

# Push to Plex
python main.py --cli generate --profile "Sunday Classical" --target plex
```

#### generate-all
Generate playlists for all profiles in a library.
```bash
# Export all as M3U files to a directory
python main.py --cli generate-all --library "My Collection" --output-dir ./playlists [-q]

# Push all to Plex
python main.py --cli generate-all --library "My Collection" --target plex [-q]
```

#### integrity
Run integrity checks on a library.
```bash
python main.py --cli integrity --library "My Collection" [-v]
```
Reports orphaned tracks, unscanned files, duplicates, and cross-folder works.

#### overrides
Export or import metadata overrides.
```bash
# Export
python main.py --cli overrides export --library "My Collection" --output overrides.json

# Import
python main.py --cli overrides import --library "My Collection" --input overrides.json
```

#### Common Flags

| Flag | Description |
|------|-------------|
| `-v` / `--verbose` | Debug-level logging |
| `-q` / `--quiet` | Suppress progress output; only show errors (ideal for cron jobs) |

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
2. Set Length to **duration** and enter a duration: `1:00` for one hour, `2:30` for
   2.5 hours, or a plain number for seconds (e.g., `3600`)
3. Set a **Seed** value if you want the same selection each time
4. Export

### Managing Multiple Music Sections in Plex

1. Create separate libraries (e.g., "Classical", "Christmas")
2. For each library, set the **Plex Section** field in the sidebar to the
   corresponding Plex library name (e.g., "MainMusic", "XmasMusic")
3. When you push a playlist, it automatically targets the correct Plex section

### Correcting Work Grouping

If the scanner grouped tracks incorrectly:

1. Go to the **Cleanup / Overlay** tab
2. Use the **Source** dropdown to filter by detection method (e.g., MB Work ID, Work Tag)
3. Find the work and right-click → **Show Album** to see the full album context
4. To merge tracks into one work: select tracks, set the same **Group Key** for all
5. To break apart an incorrect grouping: select the work(s) and click **Make Standalone**
6. Click **Re-detect Works** in the sidebar to apply changes

### Suppressing Erroneous Work Tags

Some files have incorrect WORK tags (e.g., "PMEDIA" from bulk tagging). To clear these:

1. Switch the Source dropdown to **Work Tag** or **MB Work ID**
2. Multi-select the incorrect works (Ctrl+click or Shift+click)
3. Click **Make Standalone** to mark all tracks as standalone
4. Click **Re-detect Works** to apply

### Migrating from Simple Playlists

If you have text files listing album directories (one per line):

1. Click **Import Old Playlists** in the sidebar
2. Select your text files
3. Each file becomes a named profile with include rules for matched albums
4. Load the profile in the Playlist Builder to review and adjust

### Backing Up Your Library

Use **Export Lib** to save the entire library (structure, profiles, overrides) to
a JSON file. Use **Import Lib** to restore it on the same or different machine.
Source folders must exist at the same paths (or be updated after import) for
rescanning to work.

---

## Configuration Reference

### config.json

```json
{
  "active_library": 1,
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
  }
}
```

- **active_library**: Legacy field (GUI uses selected library)
- **targets.plex**: Omit entirely if you don't use Plex
  - At least one of `token` or `token_env` is required
  - `music_section` is optional if set per-library in the sidebar
- **targets.m3u**: Controls M3U export behavior

### gui_prefs.json (auto-managed)

Stores window geometry, database path override, and last-used export directory.
Do not edit manually.

### Supported Audio Formats

MP3, FLAC, OGG, OPUS, M4A, MP4, WAV, WMA, AAC, ALAC, APE, WavPack (.wv)

---

## Troubleshooting

### "No module named customtkinter"
Run `pip install -r requirements.txt` inside your virtual environment.

### File dialogs look different on Linux
The app uses zenity (GNOME) or kdialog (KDE) for native file dialogs on Linux.
If neither is installed, it falls back to Tkinter's built-in dialogs. Install
zenity with `sudo apt install zenity`.

### Plex push fails with "section not found"
Verify the Plex Section name matches exactly (case-sensitive) with your Plex
library name. Check the per-library section in the sidebar and the default in
Settings.

### Plex push fails with unmatched tracks
Your path rules may not correctly translate local paths to Plex server paths.
Click **View Logs** to see which tracks failed to match. Adjust path rules in
Settings.

### Works grouped incorrectly
Go to the **Cleanup / Overlay** tab. Use the Source dropdown to filter by detection
method and the search field to find specific works. Right-click → **Details** to
inspect metadata, or **Show Album** to see the full album context and edit
track-level overrides.

Use **Set Group Key** to merge tracks into a work, or **Make Standalone** to break
apart incorrect groupings. Click **Re-detect Works** to apply changes without a
full rescan.

### Scan takes too long
Large collections (thousands of albums) may take several minutes for a full scan.
Use **Scan Changes** for routine updates — it only processes new, changed, or
deleted files and is much faster. You can cancel either scan type mid-operation.

### Database path change not taking effect
Database path changes require an application restart. Close and reopen the app.

### View Logs shows no output
The log viewer captures output from the current session only. If you just started
the app, perform an action (scan, export, etc.) to generate log entries.
