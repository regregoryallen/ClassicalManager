# Classical Music Playlist Manager

A desktop application for managing and generating playlists from classical music collections. Unlike general-purpose playlist tools, it understands the structure of classical music: multi-movement works, composers, and the relationship between tracks within a composition. This enables playlist shuffling while keeping multi-movement works together.

## The Problem

Standard music players and playlist generators treat every track independently. For classical music, this means a symphony's four movements get scattered across a shuffled playlist, or a concerto's slow movement plays right after an unrelated opera aria. Classical listeners need tools that understand works as coherent units.

This tool works with music files you own — ripped CDs, purchased downloads, or any audio files stored on disk. It does not connect to or manage streaming services (Spotify, Apple Music, etc.), though downloaded files from those services work like any other audio files.

## Features

- **Automatic work detection** from MusicBrainz IDs, WORK tags, or title-prefix heuristics — with intelligent merging when per-movement MB IDs share a common WORK tag
- **Work-aware shuffling** that keeps movements together in correct order while randomizing the sequence of complete works
- **Avoid adjacent** option to prevent consecutive works by the same composer, from the same album, or of the same musical form
- **Additive selection** at album, work, or track level with specificity-based exceptions for precise playlist curation
- **Pin to position** — pin specific works to fixed positions (1–5) at the start of a generated playlist, ensuring a curated opening sequence
- **Show in profiles** — right-click any album, work, or track to see which saved profiles include it
- **Double-click toggle** — double-click items in the Playlist Builder's library pane to toggle their include/exclude state
- **Find Unused** to discover tracks not covered by any profile — useful for triaging new additions
- **Find Similar** — Pandora-style audio-similarity search that ranks the library against your current selections, with a self-calibrating match score, seed-agreement count, and volatility filter
- **Non-destructive metadata overrides** to correct grouping errors without modifying audio files
- **Incremental scanning** that detects only new, changed, or deleted files for fast library updates
- **Multiple export targets**: M3U files, JSON, or direct push to Plex servers — Plex playlists are updated in place, preserving playlist IDs across regenerations
- **Multiple libraries** to organize distinct collections (e.g., classical, holiday music)
- **Track preview** — right-click any track to play it in your system's default audio player
- **Column sorting** with numeric-aware ordering across all tree views
- **Profile summary** with per-profile album, work, track, composer, and duration statistics
- **GUI and CLI** interfaces — the GUI for interactive work, the CLI for scripting and cron jobs

## Quick Start

### Quick install

One small file that fetches the current source, runs the installer, and cleans
up after itself. No Git needed.

| | Download | Then |
|---|---|---|
| **Linux / macOS** | [install-classical-manager.sh](https://raw.githubusercontent.com/regregoryallen/ClassicalManager/master/bootstrap/install-classical-manager.sh) | `bash install-classical-manager.sh` |
| **Windows** | [install-classical-manager.bat](https://raw.githubusercontent.com/regregoryallen/ClassicalManager/master/bootstrap/install-classical-manager.bat) and [install-classical-manager.ps1](https://raw.githubusercontent.com/regregoryallen/ClassicalManager/master/bootstrap/install-classical-manager.ps1), into the same folder | double-click the `.bat` |

Add `--ref v3.11` (Linux) or `-Ref v3.11` (Windows) to install a specific
release rather than the current master.

Neither bootstrap installs Python — that is a system-wide change they should
not make unasked. If Python 3.12+ is missing they say so, name the command for
your platform, and stop.

> These are ordinary scripts: read them before running them. That is also why
> there is no `curl | bash` one-liner here — piping a download straight into a
> shell is a habit worth not building.

### Manual install

Download and extract the [latest zip](https://github.com/regregoryallen/ClassicalManager/archive/refs/heads/master.zip) (extracts as `ClassicalManager-master`), or clone with Git:

```bash
git clone https://github.com/regregoryallen/ClassicalManager.git
```

Then follow the platform-specific instructions below.

## Linux

**Prerequisite:** Python 3.12+ and Tkinter (`sudo apt install python3-tk` on Debian/Ubuntu).

From the extracted folder, run the interactive installer:

```bash
cd ClassicalManager-master   # or ClassicalManager if cloned
bash install.sh
```

The installer will:
- Check prerequisites and offer to install missing packages
- Deploy to `~/.local/share/classical-manager` (local) or `/opt/classical-manager` (system-wide)
- Create a Python virtual environment and install dependencies
- Walk you through configuring Plex, M3U export, and database location
- Install a desktop launcher (under Sound & Video) and the `classical-manager`
  and `classical-manager-rgtag` commands
- Copy the cron companion script for scheduled automation

After installation:
- **GUI:** Launch from the app menu, or run `classical-manager`
- **CLI:** `classical-manager --cli scan --library "My Collection"`
- **Tagger:** `classical-manager-rgtag --help`
- **Uninstall:** `bash install.sh --uninstall`

Both commands run inside the installed virtual environment, so there is
nothing to activate first.

### Cron automation

The installer places a companion script at `~/.local/share/classical-manager/classical-manager-cron.sh`. Configure the mode by adding a `cron` section to `config.json`, then add the script to your crontab:

```json
"cron": {
  "library": "My Collection",
  "mode": "plex"
}
```

```bash
# Push all playlists to Plex every night at 2 AM:
0 2 * * * /home/user/.local/share/classical-manager/classical-manager-cron.sh
```

Modes: `plex` (default), `m3u`, `scan`, `scan+plex`, `scan+m3u`. See the comments inside the script for full details.

### Webhook / Home Assistant (Linux only)

A built-in webhook service lets Home Assistant (or any HTTP client) trigger playlist operations remotely:

```bash
# Start the webhook service:
classical-manager --cli webhook

# Or install as a systemd service (the installer offers this during setup)
```

Configure Home Assistant with a `rest_command`:

```yaml
rest_command:
  classical_manager_plex:
    url: "http://CM_HOST:5588/api/jobs"
    method: POST
    content_type: "application/json"
    payload: '{"command": "plex"}'
```

One service can serve several libraries — map each to its own m3u output
directory in `webhook.libraries`, then name one in the request:

```yaml
  classical_manager_xmas_m3u:
    url: "http://CM_HOST:5588/api/jobs"
    method: POST
    content_type: "application/json"
    payload: '{"command": "m3u", "library": "XmasMusic"}'
```

See the [User Guide](USERGUIDE.md#webhook-service) for full API documentation.

<details>
<summary>Manual setup (without install script)</summary>

```bash
cd ClassicalManager-master   # or ClassicalManager if cloned
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python main.py
```
</details>

## Windows

**Prerequisite:** Install Python 3.12+ from [python.org](https://www.python.org/downloads/).
Check **"Add python.exe to PATH"** during installation and leave **"tcl/tk and IDLE"** checked.

From the extracted folder, run the interactive installer:

```
install.bat
```

The installer will:
- Check prerequisites (Python 3.12+, Tkinter)
- Deploy to `%LOCALAPPDATA%\ClassicalManager` (default) or a custom path
- Create a Python virtual environment and install dependencies
- Walk you through configuring Plex, M3U export, and database location
- Create Desktop and Start Menu shortcuts and a `classical-manager` CLI command

After installation:
- **GUI:** Launch from the Desktop shortcut, Start Menu, or run `classical-manager`
- **CLI:** `classical-manager --cli scan --library "My Collection"`
- **Uninstall:** `install.bat --uninstall`

<details>
<summary>Manual setup (without install script)</summary>

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python main.py
```
</details>

## macOS

No installer script is provided yet. Follow the manual Linux steps above (the same commands work on macOS). Tkinter is included with the python.org Python 3.12+ installer for macOS.

## How It Works

1. **Scan** your music folders — the scanner reads embedded metadata (MusicBrainz, WORK/MOVEMENT tags, ID3, Vorbis, MP4) and groups tracks into multi-movement works
2. **Review** detected works on the Cleanup tab — fix any incorrect groupings with overrides
3. **Build** playlists by including/excluding albums, works, or individual tracks
4. **Export** to M3U, JSON, or push directly to your Plex server

## Work Detection

Works are detected using a five-step precedence chain:

1. **Manual overrides** (`work_name`) — highest priority
2. **MusicBrainz Work ID** — tracks sharing the same MB work ID (or same WORK tag across different MB IDs)
3. **WORK tag** — tracks with matching WORK metadata
4. **Title-prefix heuristic** — contiguous tracks whose titles share a common prefix with movement markers
5. **Standalone** — remaining tracks become single-track works

## Work-scoped ReplayGain (Linux, optional)

`rgtag.py` writes ReplayGain tags scoped to the **work** rather than the album
folder, so a symphony is normalized as one unit and its movements keep their
relative levels. It is a separate tool, not part of the application: it is the
only thing here that writes to your audio files.

It needs [rsgain](https://github.com/complexlogic/rsgain), which the application
itself does not:

```bash
sudo apt install rsgain
```

**Dry-run is the default — nothing is written without `--write`.**

The examples below use `./rgtag.py`, which re-runs itself inside the project's
virtual environment — the form to use from a source checkout. After running the
installer the command is `classical-manager-rgtag` instead, and on Windows from
a checkout it is `rgtag.bat`. The arguments are identical in all three.

```bash
# See what would happen across the whole library, including which
# groupings were excluded as untrustworthy and which works are
# predicted to clip on playback:
./rgtag.py --library "My Collection"

# Find a particular work (the GUI does not show work ids):
./rgtag.py --library "My Collection" --list --album "Mahler 5"

# Tag copies in a scratch directory first, leaving the library untouched:
./rgtag.py --library "My Collection" --limit 5 --sandbox /tmp/rgtest

# Then, for real:
./rgtag.py --library "My Collection" --limit 5 --write

# Afterwards, let the database catch up with the changed files:
python main.py --cli scan-changes --library "My Collection"
```

That last step matters. Tagging updates file mtimes — it has to, because
Music Assistant decides whether to re-read a file from its mtime, and
preserving it would make the tags invisible to the player they were written
for. `scan-changes` updates the affected tracks in place and keeps their
similarity analyses; a **full** rescan straight after a tagging run would
discard those analyses and make you re-run the audio analysis.

`REPLAYGAIN_TRACK_GAIN` keeps its ordinary per-track meaning, so Kodi and other
players are unaffected; the work gain rides in `REPLAYGAIN_ALBUM_GAIN`. Works
whose grouping was guessed by the title-prefix heuristic are excluded unless you
pass `--include-heuristic` — review them in the dry-run report first, because a
wrong grouping writes a wrong gain into files.

## Requirements

- Python 3.12+
- Tkinter (included on Windows/macOS; `sudo apt install python3-tk` on Debian/Ubuntu)
- Optional on Linux: `zenity` or `kdialog` for native file dialogs
- Optional on Linux: `rsgain`, needed only by `rgtag.py` (see above)

## Documentation

See the [User Guide](USERGUIDE.md) for detailed documentation covering installation, setup, all features, and troubleshooting.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

Copyright (c) 2026 Roger Gregory-Allen

### Dependency note

The MIT license above covers this project's own source code. This application
depends on [mutagen](https://github.com/quodlibet/mutagen), which is licensed
under the GNU GPL v2.0 or later. Installing the dependencies separately (via
`pip install -r requirements.txt`) and running from source does not affect the
licensing of this project's code. If you later distribute a *bundled* build that
packages mutagen together with the application (for example, a PyInstaller
executable), that combined distribution is subject to the terms of the GPL.

## Development

This application was built using [Claude Code](https://claude.ai/claude-code) (Anthropic's AI coding assistant). The author provided the specifications, directed development, and performed all testing; Claude wrote the code. The result is a fully functional application that reflects a human-directed, AI-implemented collaboration.
