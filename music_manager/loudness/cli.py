"""Command line for the work-scoped ReplayGain tagger.

Dry-run is the default and `--write` is required to touch a file. That
inverts CM's usual convention deliberately: a scan can be run again, and
seven thousand irreplaceable audio files cannot.
"""

import logging
import sys
from pathlib import Path

import typer

from music_manager.loudness.gain import MA_TARGET_LUFS, REFERENCE_LUFS

app = typer.Typer(add_completion=False,
                  help="Write work-scoped ReplayGain tags into audio files.")


def _setup_logging(verbose=False, quiet=False):
    level = logging.DEBUG if verbose else (
        logging.ERROR if quiet else logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s",
                        stream=sys.stderr)


@app.command()
def tag(
    config: str = typer.Option(None, "--config",
                               help="Path to config.json"),
    library: str = typer.Option(None, "--library",
                                help="Library name (default: every library)"),
    write: bool = typer.Option(False, "--write",
                               help="Actually write tags. Off by default."),
    sandbox: str = typer.Option(None, "--sandbox", metavar="DIR",
                                help="Copy each work into DIR and tag the "
                                     "copies, leaving the library untouched."),
    reference: float = typer.Option(REFERENCE_LUFS, "--reference",
                                    help="Reference loudness in LUFS."),
    ma_target: float = typer.Option(MA_TARGET_LUFS, "--ma-target",
                                    help="MA's normalization target, for the "
                                         "clipping report only."),
    work_id: list[int] = typer.Option(None, "--work-id",
                                      help="Tag only these works. Repeatable. "
                                           "Overrides the provenance filter."),
    limit: int = typer.Option(None, "--limit",
                              help="Stop after this many selected works."),
    include_heuristic: bool = typer.Option(
        False, "--include-heuristic",
        help="Also tag works whose grouping was guessed rather than tagged."),
    force: bool = typer.Option(False, "--force",
                               help="Retag works that are already current."),
    workers: int = typer.Option(None, "-j", "--workers",
                                help="Parallel measurements."),
    yes: bool = typer.Option(False, "-y", "--yes",
                             help="Skip the confirmation prompt."),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Measure each work as one loudness unit and tag its member files."""
    _setup_logging(verbose, quiet)

    if config:
        from music_manager.core.config import set_config_path
        set_config_path(Path(config))

    from music_manager.loudness import db as work_db
    from music_manager.loudness import report as reporting
    from music_manager.loudness import runner
    from music_manager.loudness.measure import (
        MeasurementError, find_rsgain, rsgain_version,
    )

    # Once at startup: a missing binary is not a per-work condition, and
    # discovering it four thousand works in would be a poor way to learn.
    try:
        binary = find_rsgain()
    except MeasurementError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    if not quiet:
        typer.echo(f"Using {rsgain_version(binary)}")

    try:
        work_db.connect_readonly()
    except work_db.SchemaError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    except Exception as exc:                       # noqa: BLE001 - reported
        typer.echo(f"Error: cannot open database: {exc}", err=True)
        raise typer.Exit(1)

    try:
        selection = work_db.collect_works(
            library_name=library, work_ids=work_id or None,
            include_guessed=include_heuristic, limit=limit)
    except LookupError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    if not selection.jobs:
        typer.echo("No works selected.")
        for line in reporting.render(
                runner.RunResult(selection=selection, wrote=False),
                verbose=verbose):
            typer.echo(line)
        raise typer.Exit(0)

    if write and not sandbox and not yes:
        tracks = sum(job.size for job in selection.jobs)
        typer.echo(f"About to write tags into {tracks} file(s) across "
                   f"{len(selection.jobs)} work(s).")
        typer.echo("This modifies your audio files in place.")
        if not typer.confirm("Proceed?", default=False):
            raise typer.Exit(0)

    def progress(done, total, outcome):
        if quiet:
            return
        typer.echo(f"\r[{done}/{total}] work {outcome.job.work_id} "
                   f"{outcome.job.work_name[:44]:<44}", nl=False)

    result = runner.run(
        selection, reference=reference, ma_target=ma_target, write=write,
        force=force, workers=workers, binary=binary, sandbox=sandbox,
        progress=progress)

    if not quiet:
        typer.echo("")
    for line in reporting.render(result, verbose=verbose):
        typer.echo(line)

    raise typer.Exit(1 if result.failed else 0)


def main():
    app()
