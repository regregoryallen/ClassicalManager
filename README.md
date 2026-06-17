# Classical Music Playlist Manager

A desktop application for managing and generating playlists from classical music collections. Unlike general-purpose playlist tools, it understands the structure of classical music: multi-movement works, composers, and the relationship between tracks within a composition.

## The Problem

Standard music players and playlist generators treat every track independently. For classical music, this means a symphony's four movements get scattered across a shuffled playlist, or a concerto's slow movement plays right after an unrelated opera aria. Classical listeners need tools that understand works as coherent units.

## Features

- **Automatic work detection** from MusicBrainz IDs, WORK tags, or title-prefix heuristics — with intelligent merging when per-movement MB IDs share a common WORK tag
- **Work-aware shuffling** that keeps movements together in correct order while randomizing the sequence of complete works
- **Include/exclude rules** at the composer, album, work, or track level for precise playlist curation
- **Non-destructive metadata overrides** to correct grouping errors without modifying audio files
- **Incremental scanning** that detects only new, changed, or deleted files for fast library updates
- **Multiple export targets**: M3U files, JSON, or direct push to Plex servers
- **Multiple libraries** to organize distinct collections (e.g., classical, holiday music)
- **Column sorting** with numeric-aware ordering across all tree views
- **Profile summary** with per-profile album, work, track, composer, and duration statistics
- **GUI and CLI** interfaces — the GUI for interactive work, the CLI for scripting and cron jobs

## Quick Start

```bash
git clone https://github.com/regregoryallen/ClassicalManager.git
cd ClassicalManager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python main.py
```

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

This project is provided as-is for personal use.
