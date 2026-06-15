"""Entry point for the Classical Music Playlist Manager.

Routes to the CLI when invoked with the explicit --cli flag (or any subcommand);
launches the GUI when run with no arguments.  The presence of --cli is the
deciding signal — --help and future GUI flags behave predictably.
"""

import sys


def main():
    """Route to CLI or GUI based on the presence of --cli."""
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from music_manager.interfaces.cli import app
        app()
    else:
        from music_manager.interfaces.gui import launch_gui
        launch_gui()


if __name__ == "__main__":
    main()
