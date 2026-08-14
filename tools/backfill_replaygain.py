#!/usr/bin/env python3
"""Backfill Track.rg_track_gain / rg_album_gain for an existing library.

v3.8 reads ReplayGain during the ordinary scan, so new and changed files
pick it up by themselves. Tracks already in the database were scanned
before that code existed, and an incremental scan will not revisit them
because nothing about the files has changed. This fills the gap once.

**Why not just run a full scan.** It would work — the analyses are
protected by track_analysis_snapshot, and the stored mtimes currently
match disk — but a full scan deletes and recreates every track row,
re-runs work detection, and puts every analysis through the snapshot and
restore round trip. That is a great deal of machinery to move two
columns, and every bit of it is a way for something else to go wrong.
This reads the same tag headers and writes only the two columns.

Not expected to be needed twice. After a future `rgtag.py` run the files'
mtimes move, so `scan-changes` sees them and the ordinary path takes
over.

Dry run is the default; `--write` is required to change anything. That is
`rgtag.py`'s convention, for the same reason: a scan can be run again.

    ./venv/bin/python tools/backfill_replaygain.py --progress
    ./venv/bin/python tools/backfill_replaygain.py --progress --write
"""

import argparse
import concurrent.futures
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _check_schema():
    """The v3.8 columns have to exist before anything can be written.

    They are added by `ensure_table()` at startup, so a database that has
    not seen the new build yet will not have them. Says so plainly rather
    than failing later with "Unknown column".
    """
    from music_manager.core.database import database
    columns = {c.name for c in database.get_columns("tracks")}
    missing = {"rg_track_gain", "rg_album_gain"} - columns
    if missing:
        sys.exit(
            f"The tracks table has no {', '.join(sorted(missing))} column.\n"
            "  Start the application once so the migration runs, then run "
            "this again.\n"
            "  (Adding it from here would be a second process running DDL "
            "against the live server, which is what v3.6 removed.)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", metavar="PATH",
                        help="Path to config.json, to point this at a "
                             "database other than the configured one.")
    parser.add_argument("--library", help="Library name (default: all)")
    parser.add_argument("--write", action="store_true",
                        help="Actually write. Off by default.")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel tag reads. These are small header "
                             "reads off a network share, so the limit is "
                             "round-trip latency, not bandwidth.")
    parser.add_argument("--limit", type=int,
                        help="Stop after this many tracks, for a trial run.")
    parser.add_argument("--all", action="store_true",
                        help="Re-read every track, not only those whose "
                             "gain columns are still empty.")
    args = parser.parse_args(argv)

    # Said before the work starts, not after it. The first version
    # printed "Dry run — nothing written" only in the summary, so a run
    # that took over an hour gave no indication for that whole hour that
    # it was not writing anything.
    if args.write:
        print("WRITING — changes will be applied to the database.\n")
    else:
        print("DRY RUN — nothing will be written. Pass --write to apply.\n")

    if args.config:
        from music_manager.core.config import set_config_path
        set_config_path(Path(args.config))

    from music_manager.loudness.db import connect_readonly
    if args.progress:
        print("  connecting...", file=sys.stderr, flush=True)
    connect_readonly()          # opens the database; runs no DDL
    _check_schema()

    from music_manager.core.database import Library, SourceFolder, Track, database
    from music_manager.core.scanner import extract_tags

    query = (Track.select(Track.id, Track.relative_path,
                          Track.rg_track_gain, Track.rg_album_gain,
                          SourceFolder.root_path)
             .join(SourceFolder, on=(Track.folder == SourceFolder.id)))
    if args.library:
        library = Library.get_or_none(Library.name == args.library)
        if library is None:
            sys.exit(f"No library named {args.library!r}")
        query = query.where(Track.library == library)
    if not args.all:
        # Default to the tracks that need it. Re-reading 7,000 files to
        # rewrite values that are already correct is only useful after a
        # retagging run that preserved mtimes.
        query = query.where(Track.rg_track_gain.is_null(True)
                            & Track.rg_album_gain.is_null(True))

    tracks = list(query.objects())
    if args.limit:
        tracks = tracks[:args.limit]
    if args.progress:
        print(f"  {len(tracks)} tracks to read", file=sys.stderr, flush=True)
    if not tracks:
        print("Nothing to do — every track already has its gain columns.")
        return 0

    def read_one(track):
        """Classify one track. Pure file reading — no database, no shared
        state — which is what makes it safe to run on a pool."""
        path = Path(track.root_path) / track.relative_path
        if not path.exists():
            return "missing", None
        # Deliberately the scanner's own entry point, not a private
        # helper: the backfill and a future scan must not be able to
        # disagree about what a file's gain is.
        raw = extract_tags(path)
        if raw is None:
            return "unreadable", None
        if raw.rg_track_gain is None and raw.rg_album_gain is None:
            return "untagged", None
        if (raw.rg_track_gain == track.rg_track_gain
                and raw.rg_album_gain == track.rg_album_gain):
            return "unchanged", None
        return "tagged", (track.id, raw.rg_track_gain, raw.rg_album_gain)

    # Read on a pool. Each file is a few KB of header off a network
    # share, so the wall clock is round-trip latency rather than
    # bandwidth or CPU, and latency is the one thing concurrency
    # actually fixes. Measured on this library: sequential managed
    # ~1.6 files/s and a 76-minute estimate for 7,241 tracks.
    #
    # mutagen releases the GIL while waiting on I/O, so threads are
    # enough; there is no CPU work here worth a process pool.
    counts = {"tagged": 0, "untagged": 0, "missing": 0,
              "unreadable": 0, "unchanged": 0}
    updates = []
    done = 0
    started = last_tick = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers) as pool:
        for kind, update in pool.map(read_one, tracks):
            counts[kind] += 1
            if update is not None:
                updates.append(update)
            done += 1
            if args.progress and time.monotonic() - last_tick >= 2.0:
                last_tick = time.monotonic()
                rate = done / max(last_tick - started, 1e-6)
                print(f"  ... {done}/{len(tracks)}  ({rate:.0f}/s, "
                      f"~{(len(tracks) - done) / max(rate, 1e-6) / 60:.1f} "
                      f"min left)", file=sys.stderr, flush=True)

    tagged = counts["tagged"]
    untagged = counts["untagged"]
    missing = counts["missing"]
    unreadable = counts["unreadable"]
    unchanged = counts["unchanged"]

    print(f"\nRead {len(tracks)} tracks in "
          f"{(time.monotonic() - started) / 60:.1f} min")
    print(f"  with ReplayGain to write : {tagged}")
    print(f"  already correct          : {unchanged}")
    print(f"  untagged (no gain tags)  : {untagged}")
    print(f"  file missing             : {missing}")
    print(f"  unreadable               : {unreadable}")

    if not args.write:
        print("\nDry run — nothing written. Re-run with --write.")
        for track_id, t_gain, a_gain in updates[:5]:
            offset = (a_gain - t_gain
                      if t_gain is not None and a_gain is not None else None)
            shown = f"{offset:+.2f}" if offset is not None else "n/a"
            print(f"  would set track {track_id}: track={t_gain} "
                  f"album={a_gain}  offset={shown}")
        if len(updates) > 5:
            print(f"  ... and {len(updates) - 5} more")
        return 0

    if not updates:
        # Reached on every run after the first: the default filter selects
        # tracks whose gain columns are null, and the untagged ones (m4a
        # and ape, which no tagger here can write) are null forever. They
        # are re-read each time and there is nothing to be done about
        # them, so say that rather than reporting "wrote 0".
        print("\nNothing to write — every track read is already correct "
              "or has no gain tags.")
        return 0

    # Batched, and one transaction per batch rather than one for the lot:
    # a single 7,000-row transaction against the server over the network
    # is a long lock for no benefit, and a partial backfill is harmless —
    # re-running finishes it.
    written = 0
    for start in range(0, len(updates), 500):
        batch = updates[start:start + 500]
        with database.atomic():
            for track_id, t_gain, a_gain in batch:
                (Track.update(rg_track_gain=t_gain, rg_album_gain=a_gain)
                 .where(Track.id == track_id).execute())
        written += len(batch)
        if args.progress:
            print(f"  written {written}/{len(updates)}",
                  file=sys.stderr, flush=True)

    print(f"\nWrote {written} tracks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
