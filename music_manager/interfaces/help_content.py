"""In-app help content for the Classical Music Playlist Manager.

Provides build_help_content() which populates a tk.Text widget with
formatted, bookmarked help text.
"""

import tkinter as tk


def build_help_content(text: tk.Text) -> None:
    """Insert all help content into a tk.Text widget with tags and section marks.

    Tags must already be configured on the widget before calling this.
    Section marks are set so callers can jump to named sections.
    """
    def heading(mark, title):
        text.mark_set(mark, "end-1c")
        text.mark_gravity(mark, "left")
        text.insert("end", f"\n{title}\n", "h1")
        text.insert("end", "\u2500" * 60 + "\n", "sep")

    def subheading(title):
        text.insert("end", f"\n{title}\n", "h2")

    def body(content):
        text.insert("end", content, "body")

    def bold(content):
        text.insert("end", content, "bold")

    def bullet(content):
        text.insert("end", f"  \u2022 {content}\n", "body")

    def code(content):
        text.insert("end", content, "code")

    # ── Title ──
    text.mark_set("top", "1.0")
    text.mark_gravity("top", "left")
    text.insert("end", "Classical Music Playlist Manager\n", "title")
    text.insert("end", "Help & Reference\n", "h2")
    body(
        "This application manages and generates playlists from classical music "
        "collections. It understands multi-movement works, composers, and how "
        "tracks relate within a composition \u2014 so a symphony's movements stay "
        "together in a shuffled playlist.\n"
    )

    # ── Initial Setup ──
    heading("setup", "Initial Setup")

    subheading("Database Location")
    body(
        "The database is stored as music_manager.db in the project directory by "
        "default. To change this, open Settings and set a new path. The change "
        "takes effect after restarting the app. Both the GUI and CLI read this "
        "setting from config.json.\n"
    )

    subheading("Plex Configuration")
    body("To push playlists to a Plex server, configure these in Settings:\n")
    bullet("Server URL \u2014 your Plex server address (e.g. http://192.168.1.100:32400)")
    bullet("Token \u2014 your Plex authentication token")
    bullet("Token Env Var \u2014 alternative: environment variable holding the token")
    bullet("Default Section \u2014 Plex music library name (overridable per-library in the sidebar)")
    body(
        "If your music files are at different paths on the Plex server, add path "
        "rewrite rules in Settings. Format: one rule per line, find -> replace. "
        "All paths are stored with forward slashes, even on Windows.\n"
    )

    subheading("M3U Export Configuration")
    bullet("Path Style \u2014 \"absolute\" for full paths, \"relative_to_playlist\" for relative paths")
    bullet("Base Path \u2014 optional prefix for absolute paths")
    bullet("Path Rules \u2014 same find/replace format as Plex")

    # ── Getting Started ──
    heading("getting_started", "Getting Started")

    subheading("1. Create a Library")
    body(
        "A library is a named collection with its own source folders, profiles, "
        "and settings. Click New in the sidebar and enter a name.\n"
    )

    subheading("2. Add Source Folders")
    body(
        "Click Add Folder to select root directories containing your music. "
        "Every audio file under these folders will be discovered during scanning.\n"
    )

    subheading("3. Scan the Library")
    body("Click Rescan Library. The scanner will:\n")
    bullet("Discover all supported audio files (MP3, FLAC, OGG, OPUS, M4A, WAV, etc.)")
    bullet("Extract metadata: title, artist, album, composer, genre, conductor, ensemble")
    bullet("Read MusicBrainz identifiers if present")
    bullet("Group tracks into albums (one album per folder)")
    bullet("Detect multi-movement works using metadata and heuristics")
    body(
        "Large collections may take several minutes. Click Cancel Scan to abort. "
        "The Metrics section shows counts after completion.\n"
    )

    subheading("4. Browse Your Library")
    body(
        "Switch to Explorer & Rules. The left pane lists albums; click one to "
        "see its works and tracks. The Source column shows detection method: "
        "mb_workid, work_tag, heuristic, or standalone.\n"
    )

    subheading("5. Build a Playlist")
    body(
        "Switch to Playlist Builder. Select albums, works, or tracks in the "
        "Library pane and click Add >>. Adjust shuffle, integrity, and length "
        "settings, then Preview or Export.\n"
    )

    subheading("6. Save Your Profile")
    body(
        "Enter a name in the Profile field and click Save. Rules and settings "
        "are stored in the database and can be reloaded with Load.\n"
    )

    # ── The Sidebar ──
    heading("sidebar", "The Sidebar")
    body("The sidebar (left panel) is always visible and manages library-level operations.\n")

    subheading("Library Management")
    bullet("New \u2014 create a library")
    bullet("Rename \u2014 rename the active library")
    bullet("Delete \u2014 delete the library and all its data (confirmation required)")
    bullet("Export Lib \u2014 save the entire library to a JSON file")
    bullet("Import Lib \u2014 load a library from a JSON file")

    subheading("Scanning")
    bold("Rescan Library")
    body(" \u2014 full rescan of all source folders. Overrides are preserved.\n")
    bold("Scan Changes")
    body(
        " \u2014 incremental scan; only processes new, changed, or deleted "
        "files. Much faster. Requires one prior full scan.\n"
    )
    bold("Re-detect Works")
    body(
        " \u2014 re-runs all five detection steps from stored tag data, "
        "without rescanning files. Useful after editing overrides.\n"
    )

    subheading("Other Controls")
    bullet("Source Folders \u2014 add or remove root directories for the library")
    bullet("Plex Section \u2014 map this library to a specific Plex music section")
    bullet("Import Old Playlists \u2014 import text files as profiles")
    bullet("Library Integrity Check \u2014 find orphans, duplicates, cross-folder works")
    bullet("Profile Summary \u2014 sortable table of all profiles with stats")
    bullet("Settings \u2014 application-wide configuration")
    bullet("View Logs \u2014 log output for the current session")

    # ── Explorer & Rules ──
    heading("explorer", "Explorer & Rules")
    body("Browse your library and set include/exclude rules.\n")

    subheading("Album List (left pane)")
    bullet("Columns: Album, Genre, Year, Tracks")
    bullet("Filter narrows by album title, artist, or track metadata")

    subheading("Works & Tracks (right pane)")
    body("Click an album to see its works and tracks.\n")
    bullet("Columns: Name, Source (detection method), Composer, Tracks")
    bullet("Works contain their tracks as children in the tree")

    subheading("Context Menu (right-click)")
    bullet("Play \u2014 open the track in your system's default player")
    bullet("Include Album/Work/Track \u2014 add an include rule")
    bullet("Exclude Album/Work/Track \u2014 add an exclude rule")

    subheading("Rules Display")
    body(
        "The bottom section shows all active rules. Select a rule and click "
        "Remove to delete it. Rules are shared with the Playlist Builder.\n"
    )

    # ── Playlist Builder ──
    heading("builder", "Playlist Builder")
    body("The main workspace for creating playlists.\n")

    subheading("Profile Management")
    bullet("Profile name \u2014 enter a name for your playlist profile")
    bullet("Load \u2014 restore a saved profile's settings and rules")
    bullet("Save \u2014 save current settings and rules")
    bullet("Delete \u2014 remove saved profiles")
    bullet("Profile Summary \u2014 stats for all profiles")

    subheading("Playlist Settings")
    bold("Shuffle: ")
    body("track (fully random), work (keep movements in order), album (shuffle albums as units)\n")
    bold("Integrity: ")
    body("enforce (include entire works) or respect_selection (play exactly what was selected)\n")
    bold("Length: ")
    body("all (no limit), count (max tracks), or duration (seconds, H:MM, or H:MM:SS)\n")
    bold("Seed: ")
    body("fixed number for reproducible shuffles\n")
    bold("Avoid adjacent: ")
    body("prevent consecutive items from sharing the same composer, album, or musical "
         "form (e.g. two symphonies back-to-back). Best-effort: if the pool is "
         "dominated by one value, some adjacencies may remain.\n")

    subheading("Library Pane (left)")
    bullet("Columns: Name, Composer, Genre, Info (track count or duration)")
    bullet("Color coding: Blue = included, Amber = partial, Gray = excluded")
    bullet("Filter matches name, composer, genre, performer, conductor, ensemble")
    bullet("Hide 1-track: hides standalone works")
    bullet("+/\u2212: expand/collapse all (to work level)")
    bullet("Double-click column headers to sort (numeric-aware)")
    bullet("Select items and click Add >> or double-click to include")
    bullet("Right-click: Play, Details, Show Album")

    subheading("Playlist Pane (right)")
    body(
        "Shows included items. Tree state (expansion, sort, scroll) is "
        "preserved when items are added or removed.\n"
    )
    bullet("Filter and column sorting work the same as the library pane")
    bullet("Select and click << Remove or double-click to remove items")

    subheading("Action Buttons")
    bullet("Preview \u2014 dry-run showing resolved playlist with track details")
    bullet("Export M3U \u2014 save as an M3U playlist file")
    bullet("Export JSON \u2014 save as a JSON file with full metadata")
    bullet("Push to Plex \u2014 create or update a playlist on your Plex server")
    bullet("Find Unused \u2014 populate the builder with all tracks not included "
           "in any saved profile, so you can browse and assign them")

    # ── Cleanup / Overlay ──
    heading("cleanup", "Cleanup / Overlay")
    body("Review, correct, and manage work groupings and metadata overrides.\n")

    subheading("Works Browser")
    bullet("Source dropdown \u2014 filter by: All Works, Heuristic, Standalone, Override, MB Work ID, Work Tag")
    bullet("Search field \u2014 live filtering by work name, album, or composer")
    bullet("Hide 1-track \u2014 hides standalone works (enabled by default)")
    bullet("Multi-select with Ctrl+click or Shift+click")

    subheading("Context Menu (right-click)")
    bullet("Play \u2014 open track in default player")
    bullet("Details \u2014 read-only metadata popup with copy buttons")
    bullet("Show Album \u2014 full album view with editing")
    bullet("Set Work Name / Group Key / Composer \u2014 jump to edit fields")
    bullet("Make Standalone \u2014 set __standalone__ group key")

    subheading("Edit Controls")
    bold("Set Work Name")
    body(" \u2014 change the display name (creates a work_name override)\n")
    bold("Set Group Key")
    body(" \u2014 assign a work_group_key to control grouping. Requires re-detect or rescan.\n")
    bold("Make Standalone")
    body(
        " \u2014 marks tracks with __standalone__, forcing each into its own work. "
        "Useful for suppressing incorrect WORK tags.\n"
    )
    bold("Set Composer")
    body(" \u2014 override the composer for all tracks in selected works\n")
    bold("Show Album")
    body(" \u2014 opens the album popup for the selected work's album\n")

    subheading("Show Album Popup")
    bullet("Edit album title, artist, and year (creates album-scope overrides)")
    bullet("Works/tracks tree with multi-select; right-click to Play")
    bullet("Set Group Key, Work Name, Composer, or Make Standalone for selected tracks")

    subheading("Current Overrides")
    body(
        "Lists all metadata overrides with a live search field. Overrides are "
        "non-destructive: they modify database values without touching audio "
        "files and survive rescans.\n"
    )
    bold("Track fields: ")
    body("composer, work_group_key, work_name, disc_number, track_number, "
         "movement_number, title, genre, performer, conductor, ensemble\n")
    bold("Album fields: ")
    body("album_title, album_artist, year\n")
    body("Use Export/Import Overrides JSON to back up or share corrections.\n")

    # ── Settings ──
    heading("settings", "Settings")
    body("Application-wide options saved to config.json.\n")

    subheading("Database")
    body(
        "Path to the SQLite database file. Both GUI and CLI read this. Changing "
        "the path requires a restart. To move the database, copy the .db file "
        "(and any -wal/-shm files) to the new location, then update this setting.\n"
    )

    subheading("Plex")
    bullet("Server URL \u2014 Plex server address")
    bullet("Token \u2014 Plex auth token (stored in config.json)")
    bullet("Token Env Var \u2014 environment variable name (preferred for security)")
    bullet("Default Section \u2014 default Plex library name")

    subheading("Plex Path Rules")
    body("Format: one rule per line, ")
    code("find -> replace")
    body(
        "\nTranslates local paths to Plex server paths. Use forward slashes "
        "in the find portion, even on Windows.\n"
    )

    subheading("M3U Export")
    bullet("Path Style \u2014 absolute or relative_to_playlist")
    bullet("Base Path \u2014 optional prefix for absolute paths")
    bullet("Path Rules \u2014 same format as Plex path rules")

    # ── CLI ──
    heading("cli", "Command-Line Interface")
    body("All CLI commands use the --cli flag:\n")
    code("  python main.py --cli <command> [options]\n")
    body("On Windows, use run.bat:\n")
    code("  run.bat --cli <command> [options]\n")

    subheading("Commands")
    bold("scan")
    body(" \u2014 full rescan of a library's source folders\n")
    code("  python main.py --cli scan --library \"My Collection\"\n")
    bold("scan-changes")
    body(" \u2014 incremental scan (new/changed/deleted files only)\n")
    code("  python main.py --cli scan-changes --library \"My Collection\"\n")
    bold("redetect")
    body(" \u2014 re-run work detection from stored tag data\n")
    code("  python main.py --cli redetect --library \"My Collection\"\n")
    bold("preview")
    body(" \u2014 dry-run a profile\n")
    code("  python main.py --cli preview --profile \"Sunday\"\n")
    bold("generate")
    body(" \u2014 generate and export a playlist\n")
    code("  python main.py --cli generate --profile \"Sunday\" --format m3u --output out.m3u\n")
    code("  python main.py --cli generate --profile \"Sunday\" --target plex\n")
    bold("generate-all")
    body(" \u2014 generate all profiles in a library\n")
    code("  python main.py --cli generate-all --library \"My Collection\" --output-dir ./playlists\n")
    code("  python main.py --cli generate-all --library \"My Collection\" --target plex\n")
    bold("integrity")
    body(" \u2014 run integrity checks\n")
    code("  python main.py --cli integrity --library \"My Collection\"\n")
    bold("overrides")
    body(" \u2014 export or import metadata overrides\n")
    code("  python main.py --cli overrides export --library \"My Collection\" --output overrides.json\n")
    code("  python main.py --cli overrides import --library \"My Collection\" --input overrides.json\n")

    subheading("Common Flags")
    bullet("-v / --verbose \u2014 debug-level logging")
    bullet("-q / --quiet \u2014 suppress progress; errors only (ideal for cron)")
    bullet("-h / --help \u2014 print usage summary")

    # ── Usage Patterns ──
    heading("patterns", "Usage Patterns")

    subheading("All-Composer Playlist")
    body(
        "In Playlist Builder, type the composer's name in the Filter box, "
        "select all visible albums, click Add >>. Set Shuffle to work and "
        "Integrity to enforce.\n"
    )

    subheading("Time-Limited Playlist")
    body(
        "Add desired items, set Length to duration, enter a value (e.g. 1:00 "
        "for one hour, 2:30 for 2.5 hours). Set a Seed for reproducible "
        "selections.\n"
    )

    subheading("Filter by Genre or Performer")
    body(
        "The filter field in Playlist Builder searches genre, performer, "
        "conductor, and ensemble \u2014 not just the displayed name. Type "
        "\"chamber\" or a performer's name to find matching items.\n"
    )

    subheading("Correcting Work Grouping")
    body(
        "On the Cleanup tab, use the Source dropdown to filter by detection "
        "method. Right-click \u2192 Show Album for full context. To merge "
        "tracks: set the same Group Key. To split: click Make Standalone. "
        "Then Re-detect Works in the sidebar.\n"
    )

    subheading("Suppressing Erroneous Work Tags")
    body(
        "Filter by Work Tag or MB Work ID, multi-select the incorrect works, "
        "click Make Standalone, then Re-detect Works.\n"
    )

    subheading("Multiple Plex Sections")
    body(
        "Create separate libraries, set the Plex Section field in the sidebar "
        "for each. Playlists automatically target the correct section.\n"
    )

    subheading("Sharing a Database")
    body(
        "Place the database on a shared drive (set db_path in config.json). "
        "Only run the app on one machine at a time \u2014 SQLite does not "
        "support concurrent network access. If source folders differ between "
        "machines, scan from only one; use path rules on the other.\n"
    )

    # ── Troubleshooting ──
    heading("troubleshooting", "Troubleshooting")

    bold("\"No module named customtkinter\"")
    body(" \u2014 Run pip install -r requirements.txt in your venv. On Windows, run setup.bat.\n")
    bold("setup.bat says \"Python is not installed\"")
    body(" \u2014 Install Python 3.12+ from python.org. Check \"Add python.exe to PATH\". Reopen terminal.\n")
    bold("Plex push: \"section not found\"")
    body(" \u2014 Section name must match exactly (case-sensitive). Check per-library field and Settings.\n")
    bold("Plex push: unmatched tracks")
    body(" \u2014 Path rules may not translate correctly. Check View Logs for details. Adjust in Settings.\n")
    bold("M3U wrong paths / Plex \"no tracks\" on a different OS")
    body(
        " \u2014 Plex and M3U path rules are independent. Plex rules translate "
        "to what the Plex server sees; M3U rules translate to what the local "
        "machine sees. A common mistake: putting local path translation (e.g. "
        "/mnt/MediaLib -> M:) in Plex rules instead of M3U rules. This breaks "
        "Plex and leaves M3U untranslated.\n"
    )
    bold("Works grouped incorrectly")
    body(" \u2014 Use Cleanup tab. Set Group Key to merge, Make Standalone to split. Re-detect Works to apply.\n")
    bold("Scan takes too long")
    body(" \u2014 Use Scan Changes for routine updates. Either scan type can be cancelled.\n")
    bold("\"Cannot open database\"")
    body(" \u2014 Database likely locked by another instance or network share unmounted. GUI offers local fallback.\n")
    bold("Database path change not taking effect")
    body(" \u2014 Requires a restart. Close and reopen the app.\n")
    bold("File dialogs look different on Linux")
    body(" \u2014 Install zenity (GNOME) or kdialog (KDE) for native dialogs.\n")
