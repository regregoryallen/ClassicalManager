"""Command-line interface (§11).

Provides subcommands: scan, preview, generate, overrides, integrity.
Uses typer for argument parsing and help generation.

GUI imports are lazy so the CLI runs without a display server.
"""

import logging
import sys
from pathlib import Path

import typer

app = typer.Typer(help="Classical-aware music playlist manager.")
overrides_app = typer.Typer(help="Export/import metadata overrides.")
app.add_typer(overrides_app, name="overrides")


@app.callback()
def main_callback(
    config: str = typer.Option(None, "--config", help="Path to config.json"),
):
    """Classical-aware music playlist manager."""
    if config:
        from music_manager.core.config import set_config_path
        set_config_path(Path(config))


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging with the appropriate level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _init_database():
    """Initialize the database, with a clear error if it fails."""
    from music_manager.core.database import initialize_database
    from music_manager.core.config import get_db_path, ConfigError
    try:
        db_path = get_db_path()
    except ConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    try:
        initialize_database(db_path)
    except Exception as exc:
        typer.echo(f"Error: cannot open database: {db_path}", err=True)
        typer.echo(f"  {exc}", err=True)
        typer.echo("", err=True)
        typer.echo("Possible causes:", err=True)
        typer.echo("  - The app is open on another machine (database locked)", err=True)
        typer.echo("  - The network share or drive is not mounted", err=True)
        typer.echo("  - The db_path in config.json is incorrect", err=True)
        raise typer.Exit(1)


def _get_library(name: str):
    """Look up a library by name, or exit with an error."""
    from music_manager.core.database import Library
    _init_database()
    try:
        return Library.get(Library.name == name)
    except Library.DoesNotExist:
        libs = [lib.name for lib in Library.select()]
        typer.echo(f"Error: library '{name}' not found.", err=True)
        if libs:
            typer.echo(f"Available libraries: {', '.join(libs)}", err=True)
        else:
            typer.echo("No libraries exist yet. Create one first.", err=True)
        raise typer.Exit(1)


@app.command()
def scan(
    library: str = typer.Option(..., help="Library name to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress; only show errors"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Rescan a library's source folders."""
    _setup_logging(verbose)

    from music_manager.core.scanner import scan_library, check_source_folders
    lib = _get_library(library)

    check = check_source_folders(lib)
    if check["total"] == 0:
        typer.echo("Error: library has no source folders.", err=True)
        raise typer.Exit(1)
    if check["missing"]:
        for p in check["missing"]:
            typer.echo(f"Warning: source folder not found: {p}", err=True)
        if check["wrong_os"]:
            typer.echo("These paths appear to be from a different operating system.",
                       err=True)
        if len(check["missing"]) == check["total"]:
            typer.echo("Error: all source folders are missing.", err=True)
            raise typer.Exit(1)

    if not quiet and not yes:
        typer.echo(f"Full scan of '{lib.name}' ({check['total']} source folder(s)).")
        typer.echo("This may take a while for large libraries.")
        if not typer.confirm("Proceed?", default=True):
            raise typer.Exit(0)

    def progress(current, total, message):
        typer.echo(f"\r[{current}/{total}] {message}", nl=False)

    if not quiet:
        typer.echo(f"Scanning library: {lib.name}")
    stats = scan_library(lib, progress_callback=None if quiet else progress)
    if not quiet:
        typer.echo("")  # newline after progress

        typer.echo(f"\n--- Scan Report ---")
        typer.echo(f"Files found:      {stats.files_found}")
        typer.echo(f"Files scanned:    {stats.files_scanned}")
        typer.echo(f"Files failed:     {len(stats.files_failed)}")
        typer.echo(f"Albums created:   {stats.albums_created}")
        typer.echo(f"Works created:    {stats.works_created}")
        typer.echo(f"Tracks created:   {stats.tracks_created}")

        if stats.tracks_no_composer:
            typer.echo(f"⚠ Tracks without composer: {stats.tracks_no_composer}")
        if stats.tracks_no_duration:
            typer.echo(f"⚠ Tracks with zero duration: {stats.tracks_no_duration}")
        if stats.heuristic_works:
            typer.echo(f"⚠ Works detected by heuristic (review recommended): "
                       f"{stats.heuristic_works}")

    if stats.files_failed:
        typer.echo(f"\nFailed files:", err=quiet)
        for f in stats.files_failed[:20]:
            typer.echo(f"  {f}", err=quiet)
        if len(stats.files_failed) > 20:
            typer.echo(f"  ... and {len(stats.files_failed) - 20} more", err=quiet)


@app.command("scan-changes")
def scan_changes(
    library: str = typer.Option(..., help="Library name to scan"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress; only show errors"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Incremental scan: only process new, changed, or deleted files."""
    _setup_logging(verbose)

    from music_manager.core.scanner import scan_incremental, check_source_folders
    lib = _get_library(library)

    check = check_source_folders(lib)
    if check["total"] == 0:
        typer.echo("Error: library has no source folders.", err=True)
        raise typer.Exit(1)
    if check["missing"]:
        for p in check["missing"]:
            typer.echo(f"Warning: source folder not found: {p}", err=True)
        if check["wrong_os"]:
            typer.echo("These paths appear to be from a different operating system.",
                       err=True)
        if len(check["missing"]) == check["total"]:
            typer.echo("Error: all source folders are missing.", err=True)
            raise typer.Exit(1)

    if not quiet and not yes:
        typer.echo(f"Incremental scan of '{lib.name}' ({check['total']} source folder(s)).")
        if not typer.confirm("Proceed?", default=True):
            raise typer.Exit(0)

    def progress(current, total, message):
        typer.echo(f"\r[{current}/{total}] {message}", nl=False)

    if not quiet:
        typer.echo(f"Incremental scan: {lib.name}")
    stats = scan_incremental(lib, progress_callback=None if quiet else progress)
    if not quiet:
        typer.echo("")

        typer.echo(f"\n--- Incremental Scan Report ---")
        typer.echo(f"Files found:      {stats.files_found}")
        typer.echo(f"Unchanged:        {stats.files_unchanged}")
        typer.echo(f"Added:            {stats.files_added}")
        typer.echo(f"Updated:          {stats.files_updated}")
        typer.echo(f"Removed:          {stats.files_removed}")
        typer.echo(f"Albums affected:  {stats.albums_affected}")

    if stats.files_failed:
        typer.echo(f"\nFailed files:", err=quiet)
        for f in stats.files_failed[:20]:
            typer.echo(f"  {f}", err=quiet)
        if len(stats.files_failed) > 20:
            typer.echo(f"  ... and {len(stats.files_failed) - 20} more", err=quiet)


@app.command()
def redetect(
    library: str = typer.Option(..., help="Library name"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress; only show errors"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Re-run all work detection steps using tag data in the database."""
    _setup_logging(verbose)

    from music_manager.core.scanner import redetect_works
    lib = _get_library(library)

    if not quiet and not yes:
        typer.echo(f"Re-detect works for '{lib.name}'.")
        if not typer.confirm("Proceed?", default=True):
            raise typer.Exit(0)

    def progress(current, total, message):
        typer.echo(f"\r[{current}/{total}] {message}", nl=False)

    if not quiet:
        typer.echo(f"Re-detecting works for: {lib.name}")
    result = redetect_works(lib, progress_callback=None if quiet else progress)
    if not quiet:
        typer.echo("")  # newline after progress

        typer.echo(f"\n--- Redetect Report ---")
        typer.echo(f"Albums processed:    {result['albums_processed']}")
        typer.echo(f"Override:            {result['override']}")
        typer.echo(f"MB Work ID:          {result['mb_workid']}")
        typer.echo(f"Work Tag:            {result['work_tag']}")
        typer.echo(f"Heuristic:           {result['heuristic']}")
        typer.echo(f"Standalone:          {result['standalone']}")


def _get_profile(name: str):
    """Look up a playlist profile by name (must be unique across libraries)."""
    from music_manager.core.database import PlaylistProfile
    _init_database()
    matches = list(PlaylistProfile.select().where(
        (PlaylistProfile.name == name) &
        (~PlaylistProfile.name.startswith("__"))))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        libs = [m.library.name for m in matches]
        typer.echo(f"Error: profile '{name}' exists in multiple libraries: "
                   f"{', '.join(libs)}. Profile names must be unique.", err=True)
        raise typer.Exit(1)
    profiles = [p.name for p in PlaylistProfile.select().where(
        ~PlaylistProfile.name.startswith("__"))]
    typer.echo(f"Error: profile '{name}' not found.", err=True)
    if profiles:
        typer.echo(f"Available profiles: {', '.join(profiles)}", err=True)
    else:
        typer.echo("No profiles exist yet. Create one first.", err=True)
    raise typer.Exit(1)


@app.command()
def preview(
    profile: str = typer.Option(..., help="Profile name to preview"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Preview a playlist profile without writing anything (dry-run → JSON)."""
    _setup_logging(verbose)

    from music_manager.core.engine import generate_playlist
    from music_manager.core.serializers.json_dump import serialize_engine_result

    prof = _get_profile(profile)
    result = generate_playlist(prof)

    typer.echo(serialize_engine_result(result))
    typer.echo(f"\n--- {result.track_count} tracks, "
               f"{result.total_duration_ms // 1000}s total ---", err=True)


@app.command()
def generate(
    profile: str = typer.Option(..., help="Profile name to generate"),
    format: str = typer.Option("m3u", help="Output format: m3u, json"),
    output: str = typer.Option(None, help="Output file path"),
    target: str = typer.Option(None, help="Target: plex"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress; only show errors"),
):
    """Generate a playlist and export or push it."""
    _setup_logging(verbose)

    from music_manager.core.engine import generate_playlist
    prof = _get_profile(profile)
    result = generate_playlist(prof)

    _output_result(prof, result, format=format, output=output, target=target,
                   quiet=quiet)


def _output_result(prof, result, *, format="m3u", output=None, target=None, quiet=False):
    """Output a generated playlist to the specified format/target."""
    if target == "plex":
        from music_manager.core.serializers.plex import PlexSerializer, PlexConnectionError, PlexPushError
        from music_manager.core.config import load_config
        config = load_config()
        plex_config = config.get("targets", {}).get("plex", {})
        plex_config["playlist_name"] = prof.name
        # Use per-library plex section if set
        if prof.library.plex_section:
            plex_config["music_section"] = prof.library.plex_section
        serializer = PlexSerializer()
        try:
            serializer.serialize(result.playlist, plex_config)
            if not quiet:
                typer.echo(f"Pushed playlist '{prof.name}' to Plex")
        except PlexConnectionError as exc:
            typer.echo(f"Plex connection error: {exc}", err=True)
            raise typer.Exit(1)
        except PlexPushError as exc:
            typer.echo(f"Plex push error: {exc}", err=True)
            raise typer.Exit(1)
    elif format == "json":
        from music_manager.core.serializers.json_dump import serialize_engine_result
        json_out = serialize_engine_result(
            result, output_path=Path(output) if output else None
        )
        if not output:
            typer.echo(json_out)
        elif not quiet:
            typer.echo(f"Wrote JSON to {output}")
    elif format == "m3u":
        if not output:
            typer.echo("Error: --output is required for M3U format.", err=True)
            raise typer.Exit(1)
        from music_manager.core.serializers.m3u import M3USerializer
        from music_manager.core.config import load_config
        config = load_config()
        m3u_config = config.get("targets", {}).get("m3u", {})
        m3u_config["output_path"] = output
        serializer = M3USerializer()
        serializer.serialize(result.playlist, m3u_config)
        if not quiet:
            typer.echo(f"Wrote M3U to {output}")
    else:
        typer.echo(f"Error: unknown format '{format}'", err=True)
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"Generated: {result.track_count} tracks, "
                   f"{result.total_duration_ms // 1000}s total", err=True)


@app.command("generate-all")
def generate_all(
    library: str = typer.Option(..., help="Library name"),
    format: str = typer.Option("m3u", help="Output format: m3u, json"),
    output_dir: str = typer.Option(".", help="Output directory for files"),
    target: str = typer.Option(None, help="Target: plex"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress; only show errors"),
):
    """Generate all profiles for a library."""
    _setup_logging(verbose)

    from music_manager.core.database import PlaylistProfile
    from music_manager.core.engine import generate_playlist

    lib = _get_library(library)
    profiles = list(PlaylistProfile.select().where(
        (PlaylistProfile.library == lib) &
        (~PlaylistProfile.name.startswith("__"))))

    if not profiles:
        typer.echo("No profiles found for this library.", err=True)
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"Generating {len(profiles)} profiles from '{lib.name}'...")
    out_path = Path(output_dir)

    for prof in profiles:
        if not quiet:
            typer.echo(f"\n--- {prof.name} ---")
        result = generate_playlist(prof)
        if target:
            _output_result(prof, result, target=target, quiet=quiet)
        else:
            ext = ".json" if format == "json" else ".m3u"
            safe_name = prof.name.replace(" ", "_").replace("/", "_")
            output = str(out_path / f"{safe_name}{ext}")
            _output_result(prof, result, format=format, output=output, quiet=quiet)

    if not quiet:
        typer.echo(f"\nDone: {len(profiles)} profiles generated.")


@app.command()
def integrity(
    library: str = typer.Option(..., help="Library name to check"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Run integrity checks on a library."""
    _setup_logging(verbose)

    from music_manager.core.integrity import run_integrity_checks
    lib = _get_library(library)

    typer.echo(f"Running integrity checks on: {lib.name}")
    report = run_integrity_checks(lib)

    typer.echo(f"\n--- Integrity Report ---")
    typer.echo(f"Orphaned tracks (file missing):  {len(report.orphans)}")
    typer.echo(f"Unscanned files on disk:         {len(report.unscanned)}")
    typer.echo(f"Duplicate tracks:                {len(report.duplicates)}")
    typer.echo(f"Cross-folder works:              {len(report.cross_folder_works)}")

    if report.orphans:
        typer.echo(f"\nOrphaned tracks:")
        for t in report.orphans[:20]:
            typer.echo(f"  {t}")
        if len(report.orphans) > 20:
            typer.echo(f"  ... and {len(report.orphans) - 20} more")

    if report.unscanned:
        typer.echo(f"\nUnscanned files:")
        for f in report.unscanned[:20]:
            typer.echo(f"  {f}")
        if len(report.unscanned) > 20:
            typer.echo(f"  ... and {len(report.unscanned) - 20} more")

    if report.duplicates:
        typer.echo(f"\nDuplicate tracks:")
        for d in report.duplicates[:20]:
            typer.echo(f"  {d}")

    if report.cross_folder_works:
        typer.echo(f"\nCross-folder works (possible tagging error):")
        for w in report.cross_folder_works:
            typer.echo(f"  {w}")


# ---------------------------------------------------------------------------
# Overrides subcommands
# ---------------------------------------------------------------------------

@overrides_app.command("export")
def overrides_export(
    library: str = typer.Option(..., help="Library name"),
    output: str = typer.Option(..., help="Output JSON file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Export overrides for a library to a JSON file."""
    _setup_logging(verbose)
    from music_manager.core.overrides import export_overrides

    lib = _get_library(library)
    count = export_overrides(lib, Path(output))
    typer.echo(f"Exported {count} overrides to {output}")


@overrides_app.command("import")
def overrides_import(
    library: str = typer.Option(..., help="Library name"),
    input: str = typer.Option(..., "--input", help="Input JSON file path"),
    apply: bool = typer.Option(True, help="Apply overrides after import"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Import overrides from a JSON file into a library."""
    _setup_logging(verbose)
    from music_manager.core.overrides import import_overrides, apply_overrides

    lib = _get_library(library)
    counts = import_overrides(lib, Path(input))
    typer.echo(f"Import: {counts['imported']} new, {counts['updated']} updated, "
               f"{counts['errors']} errors")

    if apply:
        result = apply_overrides(lib)
        typer.echo(f"Applied: {result['tracks_updated']} tracks, "
                   f"{result['albums_updated']} albums, "
                   f"{result['skipped']} skipped")


@app.command()
def webhook(
    library: str = typer.Option(None, help="Library name (default: from config)"),
    host: str = typer.Option(None, help="Bind address (default: 0.0.0.0)"),
    port: int = typer.Option(None, help="Port (default: 5588)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Start the webhook service for remote job submission."""
    _setup_logging(verbose)
    from music_manager.core.config import load_config, _config_path_override
    config = load_config()

    wh = config.get("webhook", {})
    lib_name = (library
                or wh.get("library")
                or config.get("cron", {}).get("library"))
    _init_database()
    if not lib_name:
        from music_manager.core.database import Library
        try:
            lib_name = Library.get_by_id(config["active_library"]).name
        except Library.DoesNotExist:
            typer.echo(
                f"Error: no library with id {config['active_library']}. "
                "Set webhook.library in config.json or use --library.",
                err=True)
            raise typer.Exit(1)
    else:
        _get_library(lib_name)  # validate exists

    resolved_host = host or wh.get("host", "0.0.0.0")
    resolved_port = port or wh.get("port", 5588)
    allowed = wh.get("allowed_commands",
                     ["plex", "scan", "scan+plex", "scan+m3u", "m3u"])
    m3u_dir = config.get("cron", {}).get("m3u_output_dir", "~/Playlists")

    config_arg = []
    if _config_path_override:
        config_arg = ["--config", str(_config_path_override)]

    # Log file lives next to the config file
    from music_manager.core.config import DEFAULT_CONFIG_PATH
    config_dir = (_config_path_override or DEFAULT_CONFIG_PATH).parent
    log_file = config_dir / "webhook.log"

    from music_manager.interfaces.webhook import start_server
    start_server(resolved_host, resolved_port, lib_name, allowed,
                 config_arg, m3u_dir, log_file=str(log_file))


@app.command("analyze-similarity")
def analyze_similarity(
    library: str = typer.Option(..., help="Library name"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress"),
):
    """Analyze all tracks for similarity features (librosa)."""
    _setup_logging(verbose)

    from music_manager.core.similarity import analyze_library
    lib = _get_library(library)

    def progress(current, total, message):
        typer.echo(f"\r[{current}/{total}] {message}", nl=False)

    if not quiet:
        typer.echo(f"Analyzing similarity features for: {lib.name}")
    stats = analyze_library(lib, progress_callback=None if quiet else progress)
    if not quiet:
        typer.echo("")
        typer.echo(f"\n--- Similarity Analysis Report ---")
        typer.echo(f"Total tracks:   {stats['total']}")
        typer.echo(f"Already done:   {stats['skipped']}")
        typer.echo(f"Analyzed now:   {stats['analyzed']}")
        typer.echo(f"Failed:         {stats['failed']}")


@app.command("export-library")
def export_library(
    library: str = typer.Option(..., help="Library name"),
    output: str = typer.Option(..., help="Output JSON file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Export a library (tracks, profiles, overrides) to a JSON file."""
    _setup_logging(verbose)
    _init_database()
    lib = _get_library(library)

    from music_manager.core.library_io import export_library as do_export
    from music_manager.core.database import PlaylistProfile

    data = do_export(lib, Path(output))
    n_profiles = len(data["profiles"])
    n_albums = len(data["albums"])
    n_overrides = len(data["overrides"])
    typer.echo(f"Exported '{lib.name}': {n_albums} albums, "
               f"{n_profiles} profiles, {n_overrides} overrides → {output}")


@app.command("import-library")
def import_library_cmd(
    input: str = typer.Option(..., "--input", help="Input JSON file path"),
    name: str = typer.Option(None, "--name", help="Library name (default: from file)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Import a library from a JSON backup file."""
    _setup_logging(verbose)
    _init_database()

    import json as json_mod
    from music_manager.core.database import Library
    from music_manager.core.library_io import import_library

    try:
        data = json_mod.loads(Path(input).read_text())
    except Exception as exc:
        typer.echo(f"Error reading file: {exc}", err=True)
        raise typer.Exit(1)

    lib_name = name or data.get("library_name", "Imported")
    existing = {l.name for l in Library.select()}
    final_name = lib_name
    n = 2
    while final_name in existing:
        final_name = f"{lib_name} ({n})"
        n += 1

    lib = Library.create(name=final_name,
                         plex_section=data.get("plex_section", ""))
    result = import_library(lib, data)

    typer.echo(f"Imported '{final_name}': {result['albums']} albums, "
               f"{result['profiles']} profiles, {result['overrides']} overrides")
    typer.echo(f"Selections imported: {result['selections_imported']}")
    if result.get('old_format_skipped'):
        typer.echo(f"Old-format rules skipped: {result['old_format_skipped']} "
                   f"(re-create selections manually)")
