# Classical Music Playlist Manager

A desktop application for managing and generating playlists from classical music collections. Unlike general-purpose playlist tools, it understands the structure of classical music: multi-movement works, composers, and the relationship between tracks within a composition. This enables playlist shuffling while keeping multi-movement works together.

## The Problem

Standard music players and playlist generators treat every track independently. For classical music, this means a symphony's four movements get scattered across a shuffled playlist, or a concerto's slow movement plays right after an unrelated opera aria. Classical listeners need tools that understand works as coherent units.

This tool works with music files you own — ripped CDs, purchased downloads, or any audio files stored on disk. It does not connect to or manage streaming services (Spotify, Apple Music, etc.), though downloaded files from those services work like any other audio files.

## Features

- **Automatic work detection** from MusicBrainz IDs, WORK tags, or title-prefix heuristics — with intelligent merging when per-movement MB IDs share a common WORK tag
- **Work-aware shuffling** that keeps movements together in correct order while randomizing the sequence of complete works
- **Include/exclude rules** at the composer, album, work, or track level for precise playlist curation
- **Non-destructive metadata overrides** to correct grouping errors without modifying audio files
- **Incremental scanning** that detects only new, changed, or deleted files for fast library updates
- **Multiple export targets**: M3U files, JSON, or direct push to Plex servers
- **Multiple libraries** to organize distinct collections (e.g., classical, holiday music)
- **Track preview** — right-click any track to play it in your system's default audio player
- **Column sorting** with numeric-aware ordering across all tree views
- **Profile summary** with per-profile album, work, track, composer, and duration statistics
- **GUI and CLI** interfaces — the GUI for interactive work, the CLI for scripting and cron jobs

## Quick Start

Download and extract the [latest zip](https://github.com/regregoryallen/ClassicalManager/archive/refs/heads/master.zip) (extracts as `ClassicalManager-master`), or clone with Git:

```bash
git clone https://github.com/regregoryallen/ClassicalManager.git
```

Then from the extracted folder (Linux/macOS):

```bash
cd ClassicalManager-master   # or ClassicalManager if cloned
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python main.py
```

## Windows

**Prerequisite:** Install Python 3.12+ from [python.org](https://www.python.org/downloads/).
Check **"Add python.exe to PATH"** during installation and leave **"tcl/tk and IDLE"** checked.

From the extracted folder:

- **Automated:** Double-click `setup.bat`, then `run.bat` (setup offers to create a desktop shortcut)
- **CLI usage:** Open a terminal in the repo folder and run `run.bat --cli scan --library "My Collection"`

<details>
<summary>Manual setup (without batch scripts)</summary>

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python main.py
```
</details>

## How It Works

1. **Scan** your music folders — the scanner reads embedded metadata (MusicBrainz, WORK/MOVEMENT tags, ID3, Vorbis, MP4) and groups tracks into multi-movement works
2. **Review** detected works on the Cleanup tab — fix any incorrect groupings with overrides
3. **Build** playlists by including/excluding albums, works, or individual tracks
4. **Export** to M3U, JSON, or push directly to your Plex server

## Work Detection

Works are detected using a five-step precedence chain:

1. **Manual overrides** (`work_group_key`) — highest priority
2. **MusicBrainz Work ID** — tracks sharing the same MB work ID (or same WORK tag across different MB IDs)
3. **WORK tag** — tracks with matching WORK metadata
4. **Title-prefix heuristic** — contiguous tracks whose titles share a common prefix with movement markers
5. **Standalone** — remaining tracks become single-track works

## Requirements

- Python 3.12+
- Tkinter (`sudo apt install python3-tk` on Ubuntu/Debian)
- Optional: `zenity` or `kdialog` for native file dialogs on Linux

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
