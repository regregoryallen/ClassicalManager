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

### Re-detect Works

Re-runs the title-prefix heuristic work detection using data already in the database,
without rescanning files from disk. This is much faster than a full rescan and is
useful when tuning detection parameters or after correcting overrides.

Only heuristic and standalone works are cleared and rebuilt. Works detected via
MusicBrainz IDs, WORK tags, or manual overrides are preserved.

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
- Use the search bar at the top to filter by album title or artist

### Works & Tracks (right pane)

- Click an album to see its works and individual tracks
- Hierarchical view: Works contain tracks
- Columns: Name, Source (how the work was detected), Composer, Track count

### Context Menus

Right-click on any item to include or exclude it:

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

### Settings (second row)

| Setting | Values | Description |
|---------|--------|-------------|
| **Shuffle** | `track`, `work`, `album` | Unit of shuffling (see below) |
| **Integrity** | `enforce`, `respect_selection` | How partial works are handled |
| **Length** | `all`, `count`, `duration` | Playlist length limit |
| **Length value** | number | Track count or duration in seconds |
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

- **Color coding**: Blue = included, Amber = partially included, Gray = excluded
- **Filter**: Type in the filter box to narrow the view (case-insensitive, matches
  at any level). Parents and children of matching items stay visible.
- **Add items**: Select one or more items and click **Add >>**, or double-click

### Playlist Pane (right)

Shows only the items that will be in your playlist.

- **Filter**: Same text filter as the library pane
- **Remove items**: Select and click **<< Remove**, or double-click

### Action Buttons (bottom)

| Button | Description |
|--------|-------------|
| **Preview** | Dry-run showing the resolved playlist with track details and total duration |
| **Export M3U** | Save as an M3U playlist file |
| **Export JSON** | Save as a JSON file with full metadata |
| **Push to Plex** | Create or update a playlist on your Plex server |

---

## Cleanup / Overlay Tab

This tab is for reviewing and correcting metadata, particularly for works detected
by the title-prefix heuristic.

### Heuristic Works Review

The top section lists all works whose grouping was determined by the title-prefix
heuristic (as opposed to MusicBrainz or explicit WORK tags). These are the most
likely to need correction.

Select a work to see its details and use the edit fields:

- **Set Work Name**: Change the display name of the work (creates an override)
- **Set Group Key**: Assign a work group key to manually control which tracks
  belong to this work. This is the highest-precedence grouping method. Requires
  a rescan to take effect.
- **Set Composer**: Assign or correct the composer for all tracks in the work

### Current Overrides

The bottom section lists all metadata overrides for the active library.

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
Rescan a library's source folders.
```bash
python main.py --cli scan --library "My Collection" [-v]
```

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

#### redetect
Re-run heuristic work detection without rescanning files from disk.
```bash
python main.py --cli redetect --library "My Collection" [-v]
```
Much faster than a full rescan. Only rebuilds heuristic and standalone works;
preserves works from overrides, MusicBrainz IDs, and WORK tags.

#### generate-all
Generate playlists for all profiles in a library.
```bash
# Export all as M3U files to a directory
python main.py --cli generate-all --library "My Collection" --output-dir ./playlists

# Push all to Plex
python main.py --cli generate-all --library "My Collection" --target plex
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

All commands accept `-v` / `--verbose` for debug-level logging.

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
2. Set Length to **duration** and enter a value in seconds (e.g., 3600 for one hour)
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
2. Find the work in the Heuristic Works list
3. Use **Set Group Key** to assign matching group keys to tracks that belong together
4. Rescan the library to apply the new grouping

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
Go to the **Cleanup / Overlay** tab to review heuristic works. Use **Set Group Key**
to manually control grouping. Works detected via MusicBrainz IDs or WORK tags are
generally reliable; heuristic groupings are the most likely to need correction.

After making corrections, click **Re-detect Works** in the sidebar to rebuild
heuristic groupings without a full rescan. This is much faster and preserves
override, MusicBrainz, and WORK tag groupings.

### Scan takes too long
Large collections (thousands of albums) may take several minutes. You can cancel
and resume later. The scan clears and rebuilds all data, so partial scans leave
the library incomplete.

### Database path change not taking effect
Database path changes require an application restart. Close and reopen the app.

### View Logs shows no output
The log viewer captures output from the current session only. If you just started
the app, perform an action (scan, export, etc.) to generate log entries.
