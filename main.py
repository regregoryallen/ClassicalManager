"""Entry point for the Classical Music Playlist Manager.

Routes to the CLI when invoked with the explicit --cli flag (or any subcommand);
launches the GUI when run with no arguments.  Help flags (-h, --help, -?) print
a usage summary without launching the GUI.
"""

import sys

_HELP = """\
Classical Music Playlist Manager

Usage:
  python main.py                    Launch the GUI
  python main.py --cli <command>    Run a CLI command

CLI commands:

  scan --library NAME [-v] [-q]
      Full rescan of a library's source folders.

  scan-changes --library NAME [-v] [-q]
      Incremental scan: only process new, changed, or deleted files.
      Much faster than a full rescan for routine updates.

  redetect --library NAME [-v] [-q]
      Re-run all work detection steps using tag data already in the
      database, without rescanning files from disk.

  preview --profile NAME [-v]
      Dry-run a profile and output the resolved playlist as JSON.

  generate --profile NAME [--format m3u|json] [--output FILE] [--target plex] [-v]
      Generate and export a single playlist.
      --output is required for M3U format.

  generate-all --library NAME [--format m3u|json] [--output-dir DIR] [--target plex] [-v] [-q]
      Generate all profiles for a library.
      --output-dir sets where files are written (default: current directory).
      Each profile becomes <profile_name>.m3u (or .json).

  integrity --library NAME [-v]
      Check for orphaned tracks, unscanned files, duplicates, and
      cross-folder works.

  overrides export --library NAME --output FILE [-v]
  overrides import --library NAME --input FILE [--no-apply] [-v]
      Export or import metadata overrides as JSON.

Common flags:
  -v, --verbose   Debug-level logging
  -q, --quiet     Suppress progress output (errors only)

Examples:
  python main.py --cli scan --library "My Collection"
  python main.py --cli generate --profile "Sunday" --format m3u --output playlist.m3u
  python main.py --cli generate-all --library "My Collection" --output-dir ./playlists
  python main.py --cli generate-all --library "My Collection" --target plex -q

Run 'python main.py --cli <command> --help' for full option details.
"""


def main():
    """Route to CLI, help, or GUI based on arguments."""
    if {"-h", "--help", "-?"} & set(sys.argv[1:]):
        print(_HELP)
        return
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from music_manager.interfaces.cli import app
        app()
    else:
        from music_manager.interfaces.gui import launch_gui
        launch_gui()


if __name__ == "__main__":
    main()
