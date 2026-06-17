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
  scan            Rescan a library's source folders
  scan-changes    Incremental scan (new/changed/deleted files only)
  redetect        Re-run work detection from stored tag data
  preview         Preview a playlist profile (dry-run, JSON output)
  generate        Generate and export a playlist (M3U, JSON, or Plex)
  generate-all    Generate all profiles for a library
  integrity       Run integrity checks on a library
  overrides       Export/import metadata overrides (subcommands: export, import)

Common flags:
  -v, --verbose   Debug-level logging
  -q, --quiet     Suppress progress output (errors only)

Examples:
  python main.py --cli scan --library "My Collection"
  python main.py --cli generate --profile "Sunday" --format m3u --output out.m3u
  python main.py --cli generate-all --library "My Collection" --target plex

Run 'python main.py --cli <command> --help' for command-specific options.
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
