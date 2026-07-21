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
        "The Playlist Builder's Library pane (left) shows the full "
        "album → work → track hierarchy with composer, genre, and "
        "year. To audit how works were detected (mb_workid, work_tag, "
        "heuristic, standalone), use the Works Browser on the Cleanup tab "
        "— its Source column shows the detection method.\n"
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
    bullet("Track Similarity \u2014 standalone finder: pick seed tracks and browse "
           "audio-similar matches (see Playlist Builder \u2192 Find Similar)")
    bullet("Profile Summary \u2014 sortable table of all profiles with stats")
    bullet("Settings \u2014 application-wide configuration")
    bullet("View Logs \u2014 log output for the current session")

    # ── Playlist Builder ──
    heading("builder", "Playlist Builder")
    body("The main workspace for creating playlists.\n")

    subheading("Profile Management")
    bullet("Profile name \u2014 enter a name for your playlist profile")
    bullet("Unsaved changes \u2014 the status strip shows \"\u2022 unsaved\" "
           "whenever the playlist differs from its saved version. New, Load, "
           "switching libraries, Find Unused, and quitting all prompt you to "
           "Save, Discard, or Cancel first, so work is never lost by "
           "navigating away")
    bullet("Load \u2014 restore a saved profile's settings and selections")
    bullet("Save \u2014 save current settings and selections")
    bullet("Delete \u2014 remove saved profiles")
    bullet("Profile Summary \u2014 stats for all profiles")

    subheading("Playlist Settings")
    bold("Shuffle: ")
    body("track (fully random), work (keep movements in order), album (shuffle albums as units)\n")
    bold("Integrity: ")
    body("enforce (any work with at least one selected track plays whole, "
         "in movement order) or respect_selection (play exactly what was "
         "selected). Integrity applies to WORKS only, never albums — "
         "selecting one movement pulls in its siblings, but selecting one "
         "work never pulls in the album's other works. Explicitly excluded "
         "tracks and works are honored and never re-added by enforce.\n")
    bold("Length: ")
    body("all (no limit), count (max tracks), or duration (seconds, H:MM, or H:MM:SS)\n")
    bold("Seed: ")
    body("fixed number for reproducible shuffles\n")
    bold("Avoid adjacent: ")
    body("prevent consecutive items from sharing the same composer, album, or musical "
         "form (e.g. two symphonies back-to-back). Best-effort: if the pool is "
         "dominated by one value, some adjacencies may remain.\n")

    subheading("Library Pane (left)")
    bullet("Columns: Name, Composer, Genre, Year (albums), Info (track count or duration)")
    bullet("Color coding: Blue = included, Amber = partial, Gray = excluded. "
           "A container is blue when every track under it is included (including "
           "when all children were added individually), amber only when some but "
           "not all content is included")
    bullet("Filter matches name, composer, genre, performer, conductor, ensemble")
    bullet("Hide 1-track: hides standalone works")
    bullet("+/\u2212: expand/collapse all (to work level)")
    bullet("Double-click column headers to sort (numeric-aware)")
    bullet("Select items and click Add >> or double-click to include "
           "(double-click toggles: included items are removed, unselected items are included)")
    bullet("Right-click: Play, Details (metadata incl. per-track volatility), Show Album")
    bullet("Show in profiles\u2026 \u2014 right-click to see which saved profiles include this item")

    subheading("Playlist Pane (right)")
    body(
        "Shows what the playlist will actually play. Tree state (expansion, "
        "sort, scroll) is preserved when items are added or removed.\n"
    )
    bullet("Tracks pulled in by Integrity=enforce (unselected movements of a "
           "partially selected work) appear in dimmed blue; directly selected "
           "tracks in normal text. Switching the Integrity setting updates "
           "the pane immediately")
    bullet("Filter and column sorting work the same as the library pane")
    bullet("Select and click << Remove or double-click to remove items. "
           "Removing a container (album or work) removes everything beneath "
           "it, regardless of sub-selections")

    subheading("Action Buttons")
    bullet("Preview \u2014 dry-run showing resolved playlist with track details")
    bullet("Export M3U \u2014 save as an M3U playlist file")
    bullet("Export JSON \u2014 save as a JSON file with full metadata")
    bullet("Push to Plex \u2014 create or update a playlist on your Plex server "
           "(preserves playlist ID across regenerations)")
    bullet("Find Unused \u2014 populate the builder with all tracks not included "
           "in any saved profile, so you can browse and assign them")
    bullet("Find Similar \u2014 find tracks that sound similar to your selections "
           "(see below); needs a one-time audio analysis pass the first time")

    subheading("Find Similar Tracks")
    body(
        "A Pandora-style search: every track you have selected acts as a seed, "
        "and the library is ranked by audio similarity. Accept the matches you "
        "like back into the profile; accepting widens the seed set so the search "
        "broadens as you go. The first run analyzes the library (one-time audio "
        "pass per track, with progress); results are cached for later searches.\n"
    )
    bullet("Max results \u2014 how many matches to return")
    bullet("Volatility max \u2014 optional filter on internal variation (soft-to-loud, "
           "sparse-to-dense). Tick the checkbox next to the slider to enable it; "
           "moving the slider alone does nothing until enabled")
    bullet("Blend \u2014 slide between nearest (single closest seed) and consensus "
           "(favor tracks many seeds agree are close)")
    bullet("Match column \u2014 % that is high when a track is as close to your seeds "
           "as the seeds are to each other; self-calibrating per search. "
           "Green = strong, amber = loose, red = weak")
    bullet("Agreement column \u2014 how many seeds consider the track close (e.g. 12/31)")
    bullet("Accept Selected / Accept All \u2014 add matches as track-level selections")
    bullet("Re-search (include accepted) \u2014 re-run with the widened seed set")
    bullet("Right-click a result for Play or Details")

    subheading("Pin to Position")
    body(
        "Pin specific works to fixed positions (1\u20135) at the start of a "
        "generated playlist for a curated opening sequence.\n"
    )
    bullet("Right-click a work in the Playlist pane \u2192 Pin to position... \u2192 choose 1\u20135")
    bullet("Pinned works show [#N] prefix in orchid color")
    bullet("Pinned works are auto-added \u2014 no separate selection needed")
    bullet("Right-click \u2192 Remove pin to unpin")
    bullet("Pins are saved with the profile")

    # ── Rules ──
    heading("rules", "Rules")
    body(
        "Every add and exclusion you make in the Builder is stored as a "
        "rule: ADD or EXCEPT at album, work, or track level. The most "
        "specific rule matching a track always wins (track beats work "
        "beats album). The Builder trees show the EFFECT of your rules; "
        "the Rules window shows the rules themselves.\n"
    )

    subheading("Health Strip")
    body(
        "The status line at the bottom right of the Builder summarizes "
        "your rules and the resulting track count, e.g. "
        "\"Rules: 12 (9 active, 2 redundant, 1 orphaned \u26a0) \u2014 "
        "45 trk (41 + 4 via integrity)\". Click it to open the Rules "
        "window. An empty profile reads \"playlist is empty\" \u2014 no "
        "rules means no tracks.\n"
    )

    subheading("Rules Window")
    body("Each rule is graded against the current library:\n")
    bullet("active \u2014 removing it would change the playlist (or it carries a pin)")
    bullet("redundant \u2014 an ADD already fully covered by a broader ADD")
    bullet("no-op \u2014 an EXCEPT with no broader ADD to except from")
    bullet("orphaned \u2014 the key no longer matches anything (deleted or "
           "regrouped after a rescan); shown in red. This window is the "
           "only place orphaned rules are visible")
    body("\nActions:\n")
    bullet("Remove \u2014 delete exactly the selected rules, nothing else")
    bullet("Reveal in Library \u2014 jump to the rule's item in the Builder "
           "(also on double-click)")
    bullet("Clean Up \u2014 remove all redundant, no-op, and orphaned rules "
           "in one confirmed step")
    body(
        "\nThe Tracks column shows how many tracks each rule currently "
        "decides. \"no breadcrumbs\" marks a work rule missing its "
        "reconciliation data; it is healed automatically when the profile "
        "is saved or loaded.\n"
    )

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
    bullet("Details \u2014 read-only metadata popup (incl. per-track volatility) with copy buttons")
    bullet("Show Album \u2014 full album view with editing")
    bullet("Set Work Name / Group Key / Composer \u2014 jump to edit fields")
    bullet("Make Standalone \u2014 set __standalone__ group key")

    subheading("Edit Controls")
    bold("Set Work Name")
    body(" \u2014 set the work name for selected tracks. Tracks sharing the same "
         "work name are grouped into a single work on re-detect or rescan.\n")
    bold("Make Standalone")
    body(
        " \u2014 marks tracks as standalone, forcing each into its own work. "
        "Useful for suppressing incorrect WORK tags.\n"
    )
    bold("Set Composer")
    body(" \u2014 override the composer for all tracks in selected works\n")
    bold("Show Album")
    body(" \u2014 opens the album popup for the selected work's album\n")

    subheading("Show Album Popup")
    bullet("Edit album title, artist, and year (creates album-scope overrides)")
    bullet("Works/tracks tree with multi-select; right-click to Play")
    bullet("Set Work Name, Composer, or Make Standalone for selected tracks")

    subheading("Current Overrides")
    body(
        "Lists all metadata overrides with a live search field. Overrides are "
        "non-destructive: they modify database values without touching audio "
        "files and survive rescans.\n"
    )
    bold("Track fields: ")
    body("composer, work_name, disc_number, track_number, "
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
    bold("analyze-similarity")
    body(" \u2014 pre-compute audio similarity features (librosa) for a library\n")
    code("  python main.py --cli analyze-similarity --library \"My Collection\"\n")
    bold("integrity")
    body(" \u2014 run integrity checks\n")
    code("  python main.py --cli integrity --library \"My Collection\"\n")
    bold("overrides")
    body(" \u2014 export or import metadata overrides\n")
    code("  python main.py --cli overrides export --library \"My Collection\" --output overrides.json\n")
    code("  python main.py --cli overrides import --library \"My Collection\" --input overrides.json\n")
    bold("export-library")
    body(" \u2014 export a library (tracks, profiles, overrides) to a JSON backup\n")
    code("  python main.py --cli export-library --library \"My Collection\" --output backup.json\n")
    bold("import-library")
    body(" \u2014 import a library from a JSON backup file\n")
    code("  python main.py --cli import-library --input backup.json [--name \"New Name\"]\n")
    bold("webhook")
    body(" \u2014 start the webhook HTTP service for remote job submission (Linux only)\n")
    code("  python main.py --cli webhook [--library \"My Collection\"] [--port 5588] [-v]\n")

    subheading("Global Options")
    bullet("--config PATH \u2014 use a custom config.json file")
    code("  python main.py --config /path/to/config.json --cli generate-all --library \"My Collection\" --target plex\n")

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
