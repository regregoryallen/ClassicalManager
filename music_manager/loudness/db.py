"""Reading CM's work groupings. This tool never writes to the database.

No new tables, no columns, no migration: all state lives in the audio
files, which keeps the tool decoupled from CM's schema and makes the
record travel with what it describes.

Connecting deliberately avoids `initialize_database`, which runs schema
DDL when the version marker does not match. v3.6 stopped that happening
on every startup for a reason — a second process creating tables against
the live server is metadata-lock contention, and it wedged the instance
twice. If the schema is behind, this tool says so and stops rather than
fixing it behind the application's back.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from music_manager.loudness.tags import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

# Groupings that came from an explicit tag, a MusicBrainz work id, or the
# user. `standalone` is a single track and so is trivially correct.
TRUSTED_SOURCES = frozenset({"override", "mb_workid", "work_tag", "standalone"})

SKIP_PROVENANCE = "provenance"
SKIP_FORMAT = "format"
SKIP_MIXED = "mixed-format"
SKIP_MISSING = "missing-file"
SKIP_CURRENT = "already-current"


class SchemaError(Exception):
    """The database is not at the schema version this tool expects."""


@dataclass(frozen=True)
class WorkJob:
    """One work and its member files, in playing order."""

    work_id: int
    work_name: str
    source: str
    album_title: str
    paths: list           # absolute, ordered
    relative_paths: list  # ordered, and what the staleness key hashes

    @property
    def size(self):
        return len(self.paths)


@dataclass(frozen=True)
class SkippedWork:
    """A work that will not be tagged, and why."""

    work_id: int
    work_name: str
    source: str
    reason: str
    detail: str = ""


@dataclass
class Selection:
    """What a run will and will not touch."""

    jobs: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def skipped_by(self, reason):
        return [s for s in self.skipped if s.reason == reason]


def connect_readonly(settings=None):
    """Open CM's database for reading, without running any DDL."""
    from music_manager.core.config import resolve_db_settings
    from music_manager.core.database import (
        database, _make_database, _schema_is_current,
    )

    if settings is None:
        settings = resolve_db_settings()
    database.initialize(_make_database(settings))
    database.connect(reuse_if_open=True)
    logger.info("Database connected read-only: %s", settings.describe())

    if not _schema_is_current():
        raise SchemaError(
            f"The database schema at {settings.describe()} is not current.\n"
            "  This tool will not migrate it: running schema DDL from a "
            "second process against a live server is the metadata-lock "
            "contention v3.6 removed.\n"
            "  Start the application once to bring the schema up to date, "
            "then run this again."
        )
    return database


def _member_order(track):
    """Playing order within a work. Nulls sort first, ties break on id."""
    return (track.disc_number or 0, track.track_number or 0, track.id)


def collect_works(library_name=None, work_ids=None, include_guessed=False,
                  limit=None, album_like=None, work_like=None):
    """Group CM's tracks into taggable works, with a reason for each refusal.

    Filters run in a deliberate order. An explicit `--work-id` overrides
    the provenance gate — naming a work is a statement that you mean it —
    but never the format gate, which is about what this tool can write.
    `limit` applies last, so it counts works that will actually be
    tagged rather than works considered.

    `album_like` and `work_like` are case-insensitive substring matches.
    They exist because CM's GUI does not show work ids anywhere, so
    `--work-id` alone left no practical way to name a work you had just
    been looking at.
    """
    from music_manager.core.database import Album, Library, SourceFolder, Track

    query = (Track
             .select(Track, Album, SourceFolder)
             .join(Album, on=(Track.album == Album.id))
             .switch(Track)
             .join(SourceFolder, on=(Track.folder == SourceFolder.id))
             .where(Track.work.is_null(False)))

    if library_name is not None:
        try:
            library = Library.get(Library.name == library_name)
        except Library.DoesNotExist:
            names = ", ".join(lib.name for lib in Library.select()) or "none"
            raise LookupError(
                f"library '{library_name}' not found. Available: {names}")
        query = query.where(Track.library == library)

    if work_ids:
        query = query.where(Track.work.in_(list(work_ids)))

    grouped = {}
    for track in query:
        grouped.setdefault(track.work_id, []).append(track)

    selection = Selection()
    explicit = set(work_ids or ())
    album_needle = (album_like or "").casefold()
    work_needle = (work_like or "").casefold()

    for work_id in sorted(grouped):
        members = sorted(grouped[work_id], key=_member_order)
        work = members[0].work                 # one query per work, cached
        name, source = work.work_name, work.work_source
        album_title = members[0].album.title or ""

        # Name filters select rather than refuse: a work the user did not
        # ask about is not "skipped", it was never in scope, and listing
        # 5,000 of them as skips would bury the ones that matter.
        if album_needle and album_needle not in album_title.casefold():
            continue
        if work_needle and work_needle not in name.casefold():
            continue

        def skip(reason, detail=""):
            selection.skipped.append(
                SkippedWork(work_id, name, source, reason, detail))

        if source not in TRUSTED_SOURCES and not include_guessed \
                and work_id not in explicit:
            skip(SKIP_PROVENANCE,
                 f"grouping was determined by '{source}'")
            continue

        suffixes = {Path(t.relative_path).suffix.lower() for t in members}
        unsupported = suffixes - SUPPORTED_EXTENSIONS
        if unsupported:
            skip(SKIP_FORMAT, ", ".join(sorted(unsupported)))
            continue
        if len(suffixes) > 1:
            # None exist in this library today, but a work whose members
            # span two formats has no single tag convention to write.
            skip(SKIP_MIXED, ", ".join(sorted(suffixes)))
            continue

        paths = [os.path.join(t.folder.root_path, t.relative_path)
                 for t in members]
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            skip(SKIP_MISSING, missing[0])
            continue

        selection.jobs.append(WorkJob(
            work_id=work_id, work_name=name, source=source,
            album_title=album_title, paths=paths,
            relative_paths=[t.relative_path for t in members],
        ))

    if limit is not None:
        selection.jobs = selection.jobs[:limit]
    return selection
