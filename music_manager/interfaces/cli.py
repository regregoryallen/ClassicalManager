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


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging with the appropriate level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _get_library(name: str):
    """Look up a library by name, or exit with an error."""
    from music_manager.core.database import Library, initialize_database
    initialize_database()
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
):
    """Rescan a library's source folders."""
    _setup_logging(verbose)

    from music_manager.core.scanner import scan_library
    lib = _get_library(library)

    def progress(current, total, message):
        typer.echo(f"\r[{current}/{total}] {message}", nl=False)

    typer.echo(f"Scanning library: {lib.name}")
    stats = scan_library(lib, progress_callback=progress)
    typer.echo("")  # newline after progress

    # Print health report
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
        typer.echo(f"\nFailed files:")
        for f in stats.files_failed[:20]:
            typer.echo(f"  {f}")
        if len(stats.files_failed) > 20:
            typer.echo(f"  ... and {len(stats.files_failed) - 20} more")


def _get_profile(name: str):
    """Look up a playlist profile by name, or exit with an error."""
    from music_manager.core.database import PlaylistProfile, initialize_database
    initialize_database()
    try:
        return PlaylistProfile.get(PlaylistProfile.name == name)
    except PlaylistProfile.DoesNotExist:
        profiles = [p.name for p in PlaylistProfile.select()]
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
):
    """Generate a playlist and export or push it."""
    _setup_logging(verbose)

    from music_manager.core.engine import generate_playlist
    prof = _get_profile(profile)
    result = generate_playlist(prof)

    if format == "json":
        from music_manager.core.serializers.json_dump import serialize_engine_result
        json_out = serialize_engine_result(
            result, output_path=Path(output) if output else None
        )
        if not output:
            typer.echo(json_out)
        else:
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
        typer.echo(f"Wrote M3U to {output}")
    elif target == "plex":
        from music_manager.core.serializers.plex import PlexSerializer, PlexConnectionError, PlexPushError
        from music_manager.core.config import load_config
        config = load_config()
        plex_config = config.get("targets", {}).get("plex", {})
        plex_config["playlist_name"] = prof.name
        serializer = PlexSerializer()
        try:
            serializer.serialize(result.playlist, plex_config)
            typer.echo(f"Pushed playlist '{prof.name}' to Plex")
        except PlexConnectionError as exc:
            typer.echo(f"Plex connection error: {exc}", err=True)
            raise typer.Exit(1)
        except PlexPushError as exc:
            typer.echo(f"Plex push error: {exc}", err=True)
            raise typer.Exit(1)
    else:
        typer.echo(f"Error: unknown format '{format}'", err=True)
        raise typer.Exit(1)

    typer.echo(f"Generated: {result.track_count} tracks, "
               f"{result.total_duration_ms // 1000}s total", err=True)


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
