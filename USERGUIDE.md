# Classical Music Playlist Manager — User Guide

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Initial Setup](#initial-setup)
4. [Getting Started](#getting-started)
5. [The Full Workflow](#the-full-workflow)
6. [The Sidebar](#the-sidebar)
7. [Playlist Builder Tab](#playlist-builder-tab)
8. [Rules](#rules)
9. [Cleanup / Overlay Tab](#cleanup--overlay-tab)
10. [Settings](#settings)
11. [Command-Line Interface](#command-line-interface)
12. [Usage Patterns](#usage-patterns)
13. [Configuration Reference](#configuration-reference)
14. [Troubleshooting](#troubleshooting)

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
- **Export to M3U, JSON, or Plex** with configurable path rewriting — or into a
  folder another music system imports, such as Music Assistant
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

### Running it afterwards

The install steps above create a virtual environment in `venv/` and
install everything into it. That environment is not active in a new
terminal, so **every later run has to activate it first**:

```bash
source venv/bin/activate
python main.py
```

On Windows the activate line is `venv\Scripts\activate` instead.

This applies to every `python main.py` in this guide — the GUI, each CLI
command, the webhook server — and to `rgtag.py`. Running `python main.py`
without activating uses the system Python, which does not have the
dependencies and fails with `ModuleNotFoundError`.

Two shortcuts avoid the activation step. On Windows, `run.bat` activates
the environment and starts the GUI in one go. On Linux and macOS,
`venv/bin/python main.py` works from anywhere without activating —
naming the interpreter inside the environment is equivalent to
activating it. `./rgtag.py` re-runs itself inside `venv/` for the same
reason.

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
- **Path Rules**: Find/replace rules for path translation, same format as Plex.
  Only applied in `absolute` mode — relative paths need no rewriting.

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

Click **Scan Library...** and choose **Full rebuild** (the only option for a
brand-new library). The scanner will:

- Discover all supported audio files (MP3, FLAC, OGG, OPUS, M4A, WAV, WMA, AAC,
  Monkey's Audio `.ape`, WavPack `.wv`, etc.)
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

The **Playlist Builder**'s Library pane (left) shows the full
album → work → track hierarchy with composer, genre, and year columns.
To audit how each work was detected (`mb_workid`, `work_tag`,
`heuristic`, or `standalone`), use the **Works Browser** on the
Cleanup / Overlay tab — its Source column shows the detection method.

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

## The Full Workflow

"Getting Started" above is the shortest path to a playlist. This chapter
is the whole pipeline, in the order the stages depend on one another,
with links to the chapter that covers each one in detail.

You do not need all of it. Stages 1–3 and 7–8 produce playlists on their
own; stages 4–6 exist to make those playlists *flow* — to stop a quiet
Adagio being followed by something that makes you reach for the volume.
Add them when that starts to matter.

**The dependencies that actually constrain the order:**

- Work grouping (3) must be right before tagging (4), because ReplayGain
  album gain is computed *per work*. Regrouping afterwards means
  retagging.
- Tagging (4) must precede any use of the **vs Work** filter (7), which
  is computed from the two ReplayGain tags and is blank without them.
- Audio analysis (5) and quietness measurement (6) are independent
  passes with separate costs and separate versions. Neither invalidates
  the other, and either can be skipped.

### 1. Acquire and organise the files

The scanner takes one album per folder, so the layout on disk decides
what an album is. Tags matter more than filenames: `COMPOSER`,
`ALBUMARTIST`, and above all `WORK` (or MusicBrainz work ids) are what
let the app group movements into works. See
[How Works Are Detected](#how-works-are-detected) for exactly which
fields are consulted and in what order.

Getting tags right at this stage is much cheaper than correcting the
results later — an overlay correction (3) fixes one work, a good tag
fixes every album you ever import from that source.

### 2. Scan

**Scan Library...** in the sidebar. First time, that is a **Full
rebuild**; afterwards prefer **Scan changes**, which updates rows in
place and keeps analyses. See [Scan Library...](#scan-library) and
[Scan Report](#scan-report).

Read the scan report rather than closing it. It tells you how many works
came from tags versus heuristics, which is the number that tells you
whether stage 3 is a five-minute job or an afternoon.

### 3. Clean up work grouping

The [Cleanup / Overlay Tab](#cleanup--overlay-tab) is where detection
mistakes get corrected. Corrections are stored as an *overlay* — the
files are never modified — so they survive rescans and can be exported
and reimported.

Sort the Works Browser by **Source** and start with `heuristic`: those
are the works the app guessed from title prefixes, and they are where
the errors are. `mb_workid` and `work_tag` came from your tags and are
usually right.

**Finish this before stage 4.** Album gain is calculated across a work's
members, so changing what belongs to a work invalidates the tags written
for it.

### 4. Write ReplayGain tags (optional)

`rgtag.py` writes work-scoped ReplayGain tags, so every movement of a
work plays at a level consistent with the rest of that work rather than
being individually normalised to the same loudness — which is what
flattens a symphony's dynamics.

```bash
source venv/bin/activate
python rgtag.py --library "My Collection"          # dry run: writes nothing
python rgtag.py --library "My Collection" --write
```

It needs `rsgain` on your PATH. Dry-run is the default; nothing is
written without `--write`. Run `python rgtag.py --help` for the full
option list — it documents provenance filtering, clipping prediction and
the mtime behaviour in more detail than belongs here.

**Follow a real run with a rescan**, or the app will not know the tags
exist:

```bash
python main.py --cli scan-changes --library "My Collection"
```

Use `scan-changes`, not a full rebuild: a full rescan only restores
analyses when mtime and size both match, and tagging changes the mtime,
so it would discard the work done in stages 5 and 6.

### 5. Analyse audio (optional)

**Analyze Audio** in the sidebar. One librosa pass per track produces the
feature vector behind [Find Similar](#find-similar-tracks) and the
Dynamic Range figure.

This is the expensive stage — hours for a large library, and it is
CPU- and memory-bound. See `analysis_workers` in the
[Configuration Reference](#configjson) before running it on a machine
with limited RAM; more workers is not linearly faster and past a point
will swap.

Results are cached per track and survive `scan-changes`. You can also
let Find Similar prompt you instead: it analyses what it needs and warns
with a time estimate before starting anything long.

### 6. Measure quietness (optional)

**Measure quietness** inside the Find Similar window. A separate, much
cheaper ffmpeg pass that produces the Startle figure — how sharply a
track rises above what came before it.

Deliberately *not* a library-wide operation. It measures the candidates
you are looking at and the tracks already in your profile, so the
library fills in as you curate rather than in one long batch up front.

Needs `ffmpeg` on your PATH; without it, Measure and Audition grey
themselves out.

### 7. Build a profile

The [Playlist Builder Tab](#playlist-builder-tab). Select albums, works
or tracks; each selection becomes a [rule](#rules), and the rules are
what get saved — not a frozen track list, so a profile picks up new
music on the next scan.

Typical loop:

1. Seed the profile with a few works you know you want.
2. **Find Similar** to widen it, filtering on Dyn Range, Startle and
   **vs Work** to keep the flow even. (**vs Work** is blank unless you
   did stage 4.)
3. Accept what fits, re-search from the widened set, repeat.
4. Watch the [Health Strip](#health-strip) for redundant or orphaned
   rules and for the pool's track count and playing time.
5. Set shuffle mode, work integrity and any length limit.
6. **Save** under a name.

### 8. Generate and publish

**Preview** resolves the rules into an actual ordered playlist so you can
check it before publishing. Then **Export M3U**, **Export JSON**, or
**Push to Plex**.

Everything here is also available from the
[Command-Line Interface](#command-line-interface), which is what makes
the last stage automatable.

### 9. Keep it current

New music arrives; the pipeline does not need re-running from the top.

- `scan-changes` picks up added, changed and removed files and keeps
  analyses.
- Stages 3–6 apply only to what is new.
- Saved profiles regenerate against the updated library without being
  touched, because they store rules rather than tracks.

To automate the regeneration, see [Cron Automation](#cron-automation)
for a schedule, or the [Webhook Service](#webhook-service) to trigger it
from Home Assistant or anything else that can make an HTTP request.

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

### Scan Library...

Opens a dialog offering two scan modes. During scanning, the button changes to
**Cancel Scan**.

**Quick scan** (recommended, the default) processes only new, changed, and deleted
files by comparing each file's modification time and size against stored values.
Minutes at most; work detection re-runs only on albums that changed. This is the
right choice for day-to-day updates.

**Full rebuild** re-reads every audio file and rebuilds the catalog from scratch —
hours on a large library. Playlists, overrides, and audio analyses are all
preserved. Use it for the first scan of a library, or to recover from suspected
metadata drift.

Quick scan is unavailable until one full rebuild has run, since it needs stored
file timestamps; the dialog explains this rather than failing later.

### Scan Report

Every scan finishes with a report rather than just a status line:

- **What was imported** — files found and scanned, albums, works and tracks
  created (or added/updated/removed for a Quick scan), and how many audio
  analyses were preserved.
- **Needs attention** — shown only when there is something to say:
  - *files that could not be read* — listed individually; they are **not** in
    the library
  - *tracks imported with no track number* — a reliable sign the file's tags
    were not readable. This also prevents work detection from grouping them,
    since the heuristic needs contiguous track numbers
  - tracks with no composer, and works detected by heuristic (review these on
    the Cleanup tab)
- **Not audio — skipped** — a per-extension count of everything the scanner
  ignored, so an unsupported format or a pile of stray files is visible.

**Copy report** puts the whole thing on the clipboard, including the list of
unreadable files.

### Regroup Works

Re-runs work detection from stored tag data and overrides, without reading
files. Use it when a correction changes **which tracks belong together** — for
example setting the same work name across tracks that currently sit in two
different works. Renaming alone cannot merge them; regrouping can.

It rebuilds every work, so playlist rules that point at works are remapped
automatically where possible, and the summary reports how many were remapped or
orphaned.

> **Regroup Works vs Apply Corrections.** Regroup changes *structure* (which
> tracks form a work). **Apply Corrections**, on the Cleanup tab, re-applies
> stored overrides that change *details* (composer, titles, numbering).
> Individual edits already apply themselves, so you rarely need either button —
> Apply Corrections is mainly for after importing an overrides JSON.

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
- **Analyze Audio**: Runs the one-time audio analysis that
  [Find Similar Tracks](#find-similar-tracks) depends on. Reports how many tracks
  still need analysis, shows progress, and can be cancelled and resumed later —
  already-analyzed tracks are skipped
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

## Playlist Builder Tab

The main workspace for creating playlists.

### Unsaved Changes

The status strip at the bottom right shows **• unsaved** whenever the current
playlist differs from its saved version. Any action that would replace the
builder's contents — **New**, **Load**, switching libraries,
or quitting — prompts first:

- **Yes** saves the profile (asking for a name if it doesn't have one yet)
- **No** discards the changes
- **Cancel** stays where you are, changes intact

Autosave continues to run in the background as crash protection. If the app
exits unexpectedly, your in-progress work is restored on next launch and
correctly shows as unsaved.

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
  Applies to **works only, never albums** — selecting one work never pulls in the
  album's other works. Explicitly excluded tracks and works are honored and never
  re-added by enforce.
- **respect_selection**: Play exactly what was selected, even if it means partial works.

The Playlist pane shows integrity expansion live: movements pulled in by
`enforce` appear in dimmed blue, and switching the Integrity setting updates
the pane immediately.

#### Avoid Adjacent

Three optional constraints that prevent consecutive items from sharing the same attribute after shuffling:

- **Same Composer**: No two adjacent works by the same composer.
- **Same Album**: No two adjacent works from the same album.
- **Same Form**: No two adjacent works of the same musical form (e.g., two symphonies or two string quartets back-to-back).

These are best-effort: if the playlist is dominated by one composer, album, or form, some adjacencies are unavoidable. Works without a detected form (standalone tracks, non-classical music) never conflict on the form dimension, so they act as natural separators.

### Library Pane (left)

Browse the full library in a hierarchical tree: Albums > Works > Tracks.

- **Columns**: Name, Composer, Genre, Year (albums), Info (track count or duration). Works appear in track order within each album.
- **Toolbar**: ⟳ reloads the tree, +/− expand/collapse. Filter fields have a ✕ clear button, and Ctrl+A selects all in any text field.
- **Show**: narrows the pane to a scope — *Entire library* (default),
  *Unassigned (no profile)* to find music no playlist uses, or any profile
  to work within it. **Show**, **Filter**, and **Hide 1-track** combine: each
  narrows what the others left. Ctrl+A in the tree selects everything shown,
  so you can add a whole scope in one gesture.

  Two workflows this enables: pick an *Imports* profile to assign newly added
  music, or pick playlist A while building playlist B to copy items across.
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

The controls sit on two rows. The first narrows the candidates; the
second decides how they are scored and which of them you are looking at.

- **Max results**: How many matches to return.
- **Max dyn range**: Optional filter, in dB. Dynamic range is how much a
  track varies internally (soft-to-loud, sparse-to-dense). Tick the
  checkbox next to the slider to *enable* the filter — moving the slider
  alone does nothing until it is enabled. Lower values keep more even,
  consistent tracks.
- **Max startle**: Optional filter, in LU. How sharply the track rises
  above what came before it. Requires **Measure quietness** (below);
  unmeasured tracks are excluded while this filter is on, not admitted.
- **Max level vs work**: Optional filter, in dB. Where the track plays
  relative to its own work once ReplayGain normalisation is applied.
  Blank for untagged files — see stage 4 of
  [The Full Workflow](#the-full-workflow).
- **Blend**: Slides between *nearest* (rank by the single closest seed) and *consensus*
  (favor tracks that many seeds agree are close).
- **Filter**: Free text, matched against title, composer and album. It
  narrows what is displayed without re-running the search and without
  changing what Match is measured against.
- **Feature weights**: Expands sliders for the six feature groups —
  timbre, register, dynamics, tempo, attack, harmony. 0 removes a group
  from the comparison, 2 doubles its say.

Each result row shows:

- **Match**: A percentage that is high when a track is as close to your seeds as your
  seeds already are to one another, decaying as it gets looser. It is self-calibrating
  per search, so it stays meaningful regardless of how broad your seed set is.
  Color-coded green (strong), amber (loose), red (weak).
- **Rank**: The track's position among the candidates scored, e.g. `7 of 500`.
- **Dyn Range**: The track's internal-variation score, in dB.
- **Startle** and **vs Work**: The two quietness figures above. An em
  dash means *not measured*, which is different from a measured zero.

The status line under the results reports how many candidates passed the
filters, how many were rejected as too loud, how many are unmeasured,
and how many the text filter is hiding — each counted separately,
because each asks for a different action.

Column widths and the window's size are remembered between sessions.

Actions:

- **Accept Selected / Accept All**: Add result tracks to the profile as track-level
  selections.
- **Re-search (include accepted)**: Re-run using the widened seed set.
- **Measure quietness**: Runs the ffmpeg pass that fills in the Startle
  and vs Work columns, for the candidates on screen and the tracks
  already in the profile. Results are saved as they finish, so it can be
  stopped and resumed.
- **Sort results**: double-click any column header to rank by it (numeric-aware).
- **Right-click** a result for **Play**, **Audition loudest moment**
  (eight seconds from where the Startle figure came from), **Details**,
  **Show Album**, or **Show in Folder**.

Find Similar analyzes any tracks that still need it before searching. For a small
number it just runs; for a large backlog it warns with a time estimate first, so a
search click never silently starts a multi-hour job. To do that work deliberately,
use **Analyze Audio** in the sidebar. A search seeded from more than
2000 tracks asks for confirmation as well — scoring that many seeds
against the library takes minutes, with the window unresponsive.

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

## Rules

Every add and exclusion you make in the Builder is stored as a *rule*: **ADD** or
**EXCEPT** at album, work, or track level. The most specific rule matching a track
always wins (track beats work beats album). The Builder trees show the *effect* of
your rules; the Rules window shows the rules themselves.

### Health Strip

The status line at the bottom right of the Builder summarizes your rules and the
resulting pool, e.g.
`Rules: 12 (9 active, 2 redundant, 1 orphaned ⚠) — pool: 45 trk (41 + 4 via integrity) / 3h 12m`.
Click it to open the Rules window. An empty profile reads "playlist is empty" —
no rules means no tracks.

It says **pool** because that is what it measures: the material the
profile is allowed to draw from. For a profile with a time or count
limit, that is deliberately *not* what the generated playlist will
contain — a 3h 12m pool with a one-hour limit is working correctly. Use
**Preview** to see what will actually play.

### Rules Window

A non-modal window grading each rule against the current library:

- **active** — removing it would change the playlist (or it carries a pin)
- **redundant** — an ADD already fully covered by a broader ADD
- **no-op** — an EXCEPT with no broader ADD to except from
- **orphaned** — the key no longer matches anything (deleted files or works
  regrouped by a rescan); shown in red. This window is the only place orphaned
  rules are visible at all.

Actions:

- **Remove** — delete exactly the selected rules, nothing else (no cascades)
- **Reveal in Library** — jump to the rule's item in the Builder tree
  (double-click does the same)
- **Clean Up** — remove all redundant, no-op, and orphaned rules in one
  confirmed step

The Tracks column shows how many tracks each rule currently decides.
"no breadcrumbs" marks a work rule missing its rescan-reconciliation data; it is
healed automatically when the profile is saved or loaded.

---

### Imported Music

After a Quick scan that adds files, those tracks are saved as their own
profile named like `Imports 2026-07-28 14:30`, and the app tells you so.
Pick it under **Show** to browse and assign the new music.

Import profiles are ordinary, editable profiles with one exception: they never
count as evidence that a track is *already assigned*, so **Show → Unassigned**
still finds their tracks. That is deliberate — an import profile exists to help
you assign music, not to claim it.

To keep one as a real playlist, save it under a new name; you are then offered
the chance to remove the original. Delete the ones you have finished with — the
Delete Profile dialog accepts multiple selections.


## Cleanup / Overlay Tab

Review, correct, and manage work groupings and metadata overrides.

### How Works Are Detected

Tracks are grouped into works by the first rule that matches: a manual override,
a MusicBrainz work ID, a WORK tag, then the title-prefix heuristic, and finally
standalone (one track = one work).

**Why didn't my album group?** The title-prefix heuristic is deliberately
conservative — a wrong grouping is harder to notice than a missing one. It groups
tracks only when the shared title prefix is **at least 5 characters and at least
3 words**, the tracks are **adjacent by track number**, and either the prefix ends
in a delimiter (`:`, `-`) or both remainders begin with a movement marker
(`I.`, `Allegro`, `No. 2`…).

So an album titled `Magnificat: Quia respexit`, `Magnificat: Et misericordia`… does
*not* group: the shared prefix `Magnificat:` is a single word. Correct these here —
select the tracks and **Set Work Name** — rather than expecting the scanner to
catch them. Loosening the rule would risk merging unrelated tracks on albums where
every title begins with the composer's name.

### Works Browser

- **Show**: narrows the browser to a scope — the whole library, unassigned
  tracks, or a single profile. Picking an *Imports* profile is the quickest way
  to review just-added music for grouping problems. A work appears when *any* of
  its tracks is in scope and then lists all of them: you are judging whether the
  grouping is right, so the work's full contents matter (the Builder filters
  individual tracks instead, because there you are picking them).

The top section lists works with filtering and search controls:

- **Source dropdown**: Filter by detection method — All Works, Heuristic, Standalone,
  Override, MB Work ID, or Work Tag
- **Search field**: Live filtering by work name, album title, or composer
- **Hide 1-track**: Hides standalone works to focus on multi-track groupings
  (off by default)
- **+/−**: Expand or collapse all tree nodes
- **Multi-select**: Ctrl+click or Shift+click to select multiple works

Works are shown hierarchically with their tracks as children. Columns: Name, Source,
Album, Tracks, Composer.

### Right-Click Context Menu

- **Play** (tracks only): Opens the audio file in your system's default player
- **Details**: Read-only popup showing all work and track metadata (names, paths,
  MB IDs, durations, and per-track dynamic range once analyzed) with copy buttons.
  The work's internal id is shown dimmed at the bottom — that is the
  value `rgtag.py --work-id` expects, and clicking it copies it.
  **Show advanced metrics** expands each track with everything else on
  record: tags, file size and timestamps, ReplayGain values, the feature
  vector by group, and the quietness metrics. Three of those are
  labelled *diagnostics* and are not comparable between tracks — they
  are stored because re-measuring is expensive, not because they mean
  anything on their own
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

- **Backend**: `SQLite (file)` or `MySQL / MariaDB (server)`. The rest of the section
  changes to match. Both the GUI and CLI read this from `config.json`, and a change
  takes effect on restart.
- **SQLite** — **Database File**: path to the `.db` file. To move a database, copy the
  `.db` file (and any `-wal`/`-shm` files) to the new location, then update this
  setting. Leave it at the default and nothing is written to `config.json`, so the
  app keeps using the database beside it wherever the app is installed.
- **MySQL / MariaDB** — **Host**, **Port**, **Database**, **User**, **Charset**, and
  either **Password** or **Password Env Var**. The environment variable wins whenever
  it is set, so a config you share or back up need not carry the credential. Only a
  password stored in `config.json` is shown in the dialog — one that comes from the
  environment stays there.
- **Test Connection** tries the values on screen without saving them, so a typo shows
  up here rather than on the next start.

Switching backend opens a different database; it does not copy anything across. To
move an existing library, use `migrate-db` (see
[Sharing a Database Across Systems](#sharing-a-database-across-systems)).

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
- **Path Rules**: Same find/replace format as Plex, applied to M3U output paths.
  Use forward slashes on all platforms. They are ignored in
  `relative_to_playlist` mode, which needs no rewriting; the app warns if both
  are set.

`base_path` was removed in v3.6.1. It prepended a prefix to absolute paths, did
nothing at all in relative mode, and was easily mistaken for an output folder.
Use a **Path Rule** with `absolute` path style instead. A config file still
carrying the key keeps working and logs a warning saying it is no longer
applied.

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
| `--version` | Print the version and exit (also shown in the window title) |

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
6. Click **Regroup Works** in the sidebar to apply

### Suppressing Erroneous Work Tags

Some files have incorrect WORK tags (e.g., "PMEDIA" from bulk tagging tools):

1. Switch the Source dropdown to **Work Tag** or **MB Work ID**
2. Multi-select the incorrect works (Ctrl+click or Shift+click)
3. Click **Make Standalone**
4. Click **Regroup Works** to apply

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

There are two ways, and they behave quite differently.

**A shared SQLite file.** Point **Database File** in Settings at a path on a shared
drive. Simple, but only one machine may run the app at a time — SQLite does not
support concurrent access over a network filesystem.

**A MySQL or MariaDB server.** Choose that backend in Settings (or write the
`database` section by hand, see below) and several machines can use one library at
once. This is also more robust: no `-wal` files to keep together when copying, and
no lock errors when a share drops out.

Create the database and user on the server first:

```sql
CREATE DATABASE classical_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'cmanager'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON classical_manager.* TO 'cmanager'@'%';
```

The `utf8mb4_bin` collation is not optional. The usual defaults
(`utf8mb4_general_ci`, `utf8mb4_unicode_ci`) are case- *and* accent-insensitive,
so they treat `Dvorak` and `Dvořák` as the same composer, and two file paths
differing only in capitalisation as the same file.

**Moving an existing library to a server** copies everything, including
similarity analyses and the file timestamps incremental scanning relies on:

```bash
python main.py --cli migrate-db --target mysql://cmanager@dbhost:3306/classical_manager
```

Supply the password in `$CM_TARGET_DB_PASSWORD` rather than in the URL, where it
would be visible in the process list. Add `--dry-run` first to see the row counts.
Every table is verified by content hash after copying, and the source database is
only ever read. Then point Settings → Database at the server and restart.

The window title shows which database is open — a file name for SQLite, or
`schema @ host` for a server — so there is no doubt which one you are looking at.

If the app cannot open the database (locked by another instance, network share
unmounted, server unreachable, wrong credentials), it shows a diagnostic message
naming the likely causes for that backend. The GUI offers the option to fall back
to the local default database; the CLI exits with an error.

If source folders are at different paths on each machine (e.g., `/mnt/Music` on
Linux vs. `M:/Music` on Windows), scan from only one machine. The other machine
can generate playlists using path rules to translate paths for its target.

### Feeding Playlists to Another Music System

Plex is not the only destination. Any system that can import M3U files can take
CM's playlists — Music Assistant, Navidrome, Jellyfin, a hardware streamer, or a
player that simply opens a folder of `.m3u` files. The pattern is the same in
every case: **write the whole set of playlists into a folder that system looks
at, then let it import them.**

Nothing special is needed for this. It is `generate-all` writing to a directory,
which CM has always done:

```bash
python main.py --cli generate-all --library "My Collection" \
    --format m3u --output-dir /path/to/that/systems/playlist/folder
```

Every profile becomes `<Profile Name>.m3u`. The name is used as-is apart from
`/`, which becomes an underscore — spaces are preserved, because importers such
as Music Assistant name the playlist after the file. Rerunning overwrites the
same files in place, so regenerating
updates the playlists rather than accumulating copies. Profiles whose names begin
with `__` are internal and are skipped.

**Getting the paths right is the part that needs thought.** The other system has
to be able to resolve every path in the file, and it often sees the same music at
a different location than CM does — a container mount, a network share mapped
elsewhere, a different drive letter. Two ways to handle that:

- **Relative paths.** Set **Path Style** to `relative_to_playlist` and put the
  playlist folder *inside* the music tree, alongside the album folders. Paths
  come out as `../Composer/Album/track.flac`, which resolve identically no
  matter where either system mounts the share. This is the simplest answer when
  you can choose the folder, and it needs no maintenance.
- **Absolute paths with a path rule.** Keep **Path Style** as `absolute` and add
  a **Path Rule** rewriting your path to theirs — for example find
  `/mnt/MediaLib` and replace with `/media/MediaLib`. Use this when the playlist
  folder has to live outside the music tree. Path rules are ignored in relative
  mode, so the two approaches are alternatives, not a combination.

**Triggering the import** is the other system's job, and how depends on it. Most
pick playlists up on their next library scan, so scheduling CM's export ahead of
that scan is usually enough — see the cron script's `m3u` and `scan+m3u` modes,
which read `cron.m3u_output_dir`. If the system exposes an API to start a scan,
call it after the export. CM does not talk to these systems itself and holds no
credentials for them; it writes files and stops there.

Two things worth knowing before you rely on it:

- **CM never deletes anything in that folder.** Renaming or deleting a profile
  leaves its old `.m3u` behind, and the other system will keep showing that
  playlist until you remove the file yourself. Tidy the folder by hand
  occasionally, and take care if it also holds playlists you made elsewhere.
- **Check the folder's name.** Some scanners skip directories beginning with an
  underscore — Music Assistant does — so `Playlists` works where `_Playlists`
  silently imports nothing.

#### Music Assistant specifics

If Music Assistant is the destination, configure its **File System** provider
against the music share with *Import playlists (m3u files)* enabled, and give the
playlists their own folder: an M3U placed inside an album folder is not imported.
Home Assistant fixes MA's view of the share and does not expose it as
configurable, so relative paths in a folder such as `Albums/Playlists` are the
path style to reach for. Track order is preserved as written, and regenerating a
playlist updates it in place without creating a duplicate.

---

## Configuration Reference

### config.json

`config.example.json` in the install directory is the authoritative
copy — it carries explanatory `_comment` keys that are stripped here for
readability. Any key beginning with `_` is ignored, which is how that
file annotates itself; JSON has no comment syntax.

```json
{
  "active_library": 1,
  "autosave_interval": 60,
  "analysis_workers": 12,
  "similarity_weights": {
    "timbre": 1.0,
    "register": 0.6,
    "dynamics": 1.0,
    "tempo": 1.0,
    "attack": 1.0,
    "harmony": 0.4
  },
  "database": {
    "backend": "mysql",
    "path": "",
    "host": "dbhost",
    "port": 3306,
    "name": "classical_manager",
    "user": "cmanager",
    "password_env": "CM_DB_PASSWORD",
    "charset": "utf8mb4"
  },
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
    "libraries": {
      "My Collection": {"m3u_output_dir": "~/Playlists"}
    },
    "allowed_commands": ["plex", "scan", "scan+plex", "scan+m3u", "m3u",
                         "exclude-track"],
    "token_env": "CM_WEBHOOK_TOKEN"
  }
}
```

| Field | Notes |
|-------|-------|
| `active_library` | Library id used when nothing else names one. The app writes this when you switch libraries in the sidebar. |
| `autosave_interval` | Seconds between builder autosaves. Default: 60; `0` disables autosaving entirely. The autosave is what a crash recovers from, so raising it widens the window of work you can lose. |
| `db_path` | Legacy, still read. Superseded by `database.path`, which wins when both are present. Saving from the Settings dialog rewrites it as `database.path` and removes this key. |
| `similarity_weights` | Optional. Per-group influence in Find Similar: `timbre`, `register`, `dynamics`, `tempo`, `attack`, `harmony`. Groups are normalised by size before weighting, so a weight is a decision rather than a consequence of how many columns a group has. 0 removes a group, 2 doubles it. The Find Similar window has sliders for the same values. |
| `analysis_workers` | Optional. Processes used by audio analysis. Omit for three quarters of the cores. Analysis is CPU-bound and the measured speedup flattens past about 12 workers, so more is not linearly faster. The GUI's Analyze Audio dialog lets you choose per run; this sets the default for the GUI, CLI, webhook and cron alike. |
| `database` | Optional. Omit entirely for SQLite at `db_path`. Settings → Database writes this section. |
| `database.backend` | `sqlite` or `mysql`. `mysql` also covers MariaDB. |
| `database.path` | SQLite only. Omit for `music_manager.db` in the project directory. Settings leaves it out when you keep the default, so an install that moves still finds its database. |
| `database.host` / `port` / `name` / `user` | Server connection. Port defaults to 3306. |
| `database.password` | Stored in `config.json`, which the installer sets to mode 600. |
| `database.password_env` | Name of an environment variable holding the password. Wins over `password` when the variable is set, so a shared or backed-up config need not carry the credential. |
| `database.charset` | Defaults to `utf8mb4`. Do not lower it — the server hands out `latin1` connections by default, which corrupts accented names on write. |
| `targets.plex` | Omit entirely if you don't use Plex. At least one of `token` or `token_env` is required. |
| `targets.plex.music_section` | Optional if set per-library in the sidebar. |
| `targets.m3u` | Controls M3U export path style and rewriting. |
| `cron` | Optional. Settings for the cron companion script. See [Cron Automation](#cron-automation). |
| `cron.library` | Library name. Falls back to `active_library` if omitted. |
| `cron.mode` | One of: `plex`, `m3u`, `scan`, `scan+plex`, `scan+m3u`. Default: `plex`. |
| `cron.profile` | Single profile name. Empty = all profiles. |
| `cron.m3u_output_dir` | Output directory for M3U mode. Default: `~/Playlists`. A leading `~` is expanded to your home directory. |
| `cron.verbosity` | `-q` (quiet, default), `` (normal), or `-v` (verbose). |
| `webhook` | Optional. Settings for the webhook service. See [Webhook Service](#webhook-service). |
| `webhook.host` | Bind address. Default: `0.0.0.0` (all interfaces). |
| `webhook.port` | Listen port. Default: `5588`. |
| `webhook.library` | Default library, used when a request does not name one. Falls back to `active_library` if omitted. |
| `webhook.libraries` | Optional. Maps a library name to its own `m3u_output_dir`, letting one service serve several libraries. A leading `~` is expanded to your home directory. A request may name only libraries listed here. See [Serving several libraries](#serving-several-libraries). |
| `webhook.allowed_commands` | List of allowed commands. Valid values: `plex`, `m3u`, `scan`, `scan+plex`, `scan+m3u`, `exclude-track`. Defaults to the five mode commands — `exclude-track` must be enabled explicitly, since it changes a profile rather than only publishing one. |
| `webhook.token_env` | Name of an environment variable holding the shared secret, used instead of putting `webhook.token` in the file. See [Webhook Service](#webhook-service). |

### gui_prefs.json (auto-managed)

Stores the main window's geometry, each popup's remembered size and
position, tree column widths, the last-used export directory and the
last library. Written as you use the app; do not edit manually. Deleting
it is safe — everything in it returns to a default.

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
works with any HTTP client.

Authentication is optional and off by default (local network use). Set
`webhook.token` in config.json — or `webhook.token_env` naming an environment
variable that holds it — and every POST must then carry a matching
`X-Auth-Token` header. Enabling it is recommended once you allow
`exclude-track`, which modifies saved profiles.

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
  "libraries": ["My Collection"],
  "allowed_commands": ["m3u", "plex", "scan", "scan+m3u", "scan+plex"]
}
```

`library` is the default used when a request does not name one; `libraries`
lists every library this service will accept (see
[Serving several libraries](#serving-several-libraries)).

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

To target a library other than the default:

```bash
curl -X POST http://localhost:5588/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"command": "m3u", "library": "XmasMusic"}'
```

**Commands:** `plex`, `scan`, `scan+plex`, `scan+m3u`, `m3u` (same as cron modes),
plus `exclude-track` (see below). Each must be listed in
`webhook.allowed_commands` to be accepted.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | One of the commands listed above. |
| `library` | string | no | Library to run against. Must be listed in `webhook.libraries`. Defaults to `webhook.library`. Ignored by `exclude-track`, which acts on a profile. |
| `profile` | string | no | Run for a single profile instead of all profiles. Required for `exclude-track`. |
| `quiet` | boolean | no | Suppress progress output (default: `false`). |
| `track` | object | no | Track identifiers for `exclude-track` (see below). |

#### Serving several libraries

One service can serve several libraries, each writing m3u files to its own
directory. Map them in `webhook.libraries`:

```json
"webhook": {
  "library": "MainMusic",
  "libraries": {
    "MainMusic": { "m3u_output_dir": "/mnt/MediaLib/Albums/Playlists" },
    "XmasMusic": { "m3u_output_dir": "/mnt/MediaLib/Albums/XmasPlaylists" }
  }
}
```

A request may then name any library in that map, and no other — asking for one
that is not listed is refused with `400` rather than served from the default
library's directory. That is deliberate: a seasonal library whose playlists
quietly land among the everyday ones produces a job that reports success, and
nothing afterwards records which files came from which library.

The output directory is never taken from the request. It comes only from this
map, so a caller cannot choose where files are written.

Notes:

- `webhook.library` must itself appear in the map, since it is what a request
  without a `library` field falls back to. The service refuses to start
  otherwise.
- Every name in the map must be an existing library; the service checks at
  startup and lists the available names if one is wrong.
- The map is read once at startup — after editing it, restart the service.
- Omit `libraries` entirely to keep the previous behaviour: one library,
  writing to `cron.m3u_output_dir`. In that mode a request naming any other
  library is refused.
- Each job records its library and output directory in `webhook.log` and in
  the `/api/jobs/last` response.

#### Thumbs Down: `exclude-track`

Excludes the track you are listening to from a profile, so it stops appearing
after the next playlist regeneration. The exclusion is an ordinary rule — it
shows up in the Rules window and can be undone there.

```bash
curl -X POST http://localhost:5588/api/jobs \
  -H 'Content-Type: application/json' \
  -H 'X-Auth-Token: your-token' \
  -d '{"command": "exclude-track", "profile": "Morning Mix",
       "track": {"title": "Adagio", "album": "Spartacus"}}'
```

The `track` object accepts:

| Field | Description |
|-------|-------------|
| `title` | Track title as tagged. Required unless `path` is given. |
| `album` | Album title — use when the same title appears on several albums. |
| `artist` | Performer, conductor, or ensemble — another disambiguator. |
| `path` | Exact relative path; skips matching entirely. |
| `scope` | `track` (default) or `work` to drop the entire work. |

Matching is case-insensitive. If more than one track matches, the job fails
rather than guessing — add `album` or `artist` to narrow it.

`album` and `artist` are hints, not filters: they are consulted only while
more than one track still matches the title, and one that matches none of
them is ignored rather than failing the job. So a caller that supplies
best-effort metadata — Music Assistant reports a library-level artist name,
which need not equal your file tags — cannot turn a track that exists into a
"no such track". Only the title can do that.

**Home Assistant example.** Because playback goes through Music Assistant, the
button reads the MA media player's attributes:

```yaml
rest_command:
  thumbs_down:
    url: "http://your-host:5588/api/jobs"
    method: POST
    headers:
      X-Auth-Token: !secret cm_webhook_token
    content_type: "application/json"
    payload: >
      {"command": "exclude-track", "profile": "Morning Mix",
       "track": {"title": "{{ state_attr('media_player.music_assistant', 'media_title') }}",
                 "album": "{{ state_attr('media_player.music_assistant', 'media_album_name') }}"}}
```

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
**Regroup Works** to apply grouping changes without a full rescan.

### Scan takes too long

Large collections may take hours for a full rebuild. Use **Quick scan** for
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
