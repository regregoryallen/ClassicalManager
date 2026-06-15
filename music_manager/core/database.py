"""Peewee ORM models and database connection management.

Defines all tables from §4.2 of the specification:
  Libraries, SourceFolders, Composers, Albums, Works, Tracks,
  PlaylistProfiles, ProfileRules, Overrides.

Design rules (§4.1):
  - All stored paths use forward slashes (POSIX) regardless of host OS.
  - Album identity is keyed on the containing folder's relative path.
  - Ordering is always (disc_number, track_number).
  - Duration is stored as integer milliseconds.
  - SQLite foreign keys are enabled on every connection.
"""

import logging
from pathlib import Path

import peewee as pw

from music_manager.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DATABASE_PATH = PROJECT_ROOT / "music_manager.db"

database = pw.SqliteDatabase(None)


def initialize_database(db_path: Path | None = None) -> pw.SqliteDatabase:
    """Initialize the database connection and create tables.

    Args:
        db_path: Optional override for the database file location.
                 Defaults to <project_root>/music_manager.db.

    Returns:
        The initialized SqliteDatabase instance.
    """
    path = db_path or DATABASE_PATH
    database.init(str(path), pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    })
    database.connect()
    logger.info("Database connected: %s", path)

    database.create_tables([
        Library,
        SourceFolder,
        Composer,
        Album,
        Work,
        Track,
        PlaylistProfile,
        ProfileRule,
        Override,
    ])
    logger.info("Database tables created/verified")
    return database


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------

class BaseModel(pw.Model):
    """Base model binding all tables to the shared database instance."""

    class Meta:
        database = database


# ---------------------------------------------------------------------------
# Libraries & source folders
# ---------------------------------------------------------------------------

class Library(BaseModel):
    """A named music library (e.g. 'Main Collection', 'Christmas Music')."""

    name = pw.TextField()

    class Meta:
        table_name = "libraries"


class SourceFolder(BaseModel):
    """A root folder belonging to a library, scanned for audio files."""

    library = pw.ForeignKeyField(Library, backref="source_folders", on_delete="CASCADE")
    root_path = pw.TextField()  # canonical POSIX path

    class Meta:
        table_name = "source_folders"


# ---------------------------------------------------------------------------
# Composers
# ---------------------------------------------------------------------------

class Composer(BaseModel):
    """A composer, deduplicated by normalized key within a library."""

    library = pw.ForeignKeyField(Library, backref="composers", on_delete="CASCADE")
    name = pw.TextField()          # display form as tagged
    sort_name = pw.TextField(null=True)  # e.g. "Beethoven, Ludwig van"
    norm_key = pw.TextField()      # normalized key for dedup/matching

    class Meta:
        table_name = "composers"
        indexes = (
            (("library", "norm_key"), True),  # unique per library
        )


# ---------------------------------------------------------------------------
# Albums
# ---------------------------------------------------------------------------

class Album(BaseModel):
    """An album, identified by its containing folder's relative path.

    Uniqueness: (library, album_key).  Because each distinct recording lives
    in its own folder, the 'twelve different Beethoven 5ths' problem
    disappears.
    """

    library = pw.ForeignKeyField(Library, backref="albums", on_delete="CASCADE")
    folder = pw.ForeignKeyField(SourceFolder, backref="albums", on_delete="CASCADE")
    album_key = pw.TextField()             # folder's relative path = album identity
    title = pw.TextField()                 # from tags; folder name as fallback
    album_artist = pw.TextField(null=True)
    year = pw.IntegerField(null=True)
    musicbrainz_album_id = pw.TextField(null=True)

    class Meta:
        table_name = "albums"
        indexes = (
            (("library", "album_key"), True),
        )


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

class Work(BaseModel):
    """A musical work (symphony, concerto, sonata, or standalone track).

    A work belongs to exactly one album.  work_source records how the
    grouping was determined (§5.4): override, mb_workid, work_tag,
    heuristic, or standalone.
    """

    album = pw.ForeignKeyField(Album, backref="works", on_delete="CASCADE")
    composer = pw.ForeignKeyField(Composer, backref="works", null=True, on_delete="SET NULL")
    work_name = pw.TextField()
    work_sequence = pw.IntegerField(null=True)  # position within the album
    work_source = pw.TextField()  # override / mb_workid / work_tag / heuristic / standalone
    musicbrainz_work_id = pw.TextField(null=True)

    class Meta:
        table_name = "works"


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

class Track(BaseModel):
    """An individual audio track in the library."""

    library = pw.ForeignKeyField(Library, backref="tracks", on_delete="CASCADE")
    folder = pw.ForeignKeyField(SourceFolder, backref="tracks", on_delete="CASCADE")
    album = pw.ForeignKeyField(Album, backref="tracks", on_delete="CASCADE")
    work = pw.ForeignKeyField(Work, backref="tracks", null=True, on_delete="SET NULL")
    composer = pw.ForeignKeyField(Composer, backref="tracks", null=True, on_delete="SET NULL")
    title = pw.TextField()
    relative_path = pw.TextField()  # POSIX, relative to SourceFolder.root_path
    disc_number = pw.IntegerField(default=1)
    disc_total = pw.IntegerField(null=True)
    track_number = pw.IntegerField()
    movement_number = pw.IntegerField(null=True)
    duration_ms = pw.IntegerField()
    musicbrainz_recording_id = pw.TextField(null=True)

    class Meta:
        table_name = "tracks"


# ---------------------------------------------------------------------------
# Playlist profiles & rules
# ---------------------------------------------------------------------------

class PlaylistProfile(BaseModel):
    """A saved playlist definition (e.g. 'Sunday Classical').

    Captures shuffle mode, work-integrity policy, stop conditions, and
    optional seed for reproducible shuffles.
    """

    library = pw.ForeignKeyField(Library, backref="profiles", on_delete="CASCADE")
    name = pw.TextField()
    shuffle_mode = pw.TextField()      # track / work / album
    work_integrity = pw.TextField()    # enforce / respect_selection
    length_mode = pw.TextField()       # count / duration / all
    length_value = pw.IntegerField(null=True)
    seed = pw.IntegerField(null=True)
    no_repeat_tracks = pw.BooleanField(default=True)

    class Meta:
        table_name = "playlist_profiles"


class ProfileRule(BaseModel):
    """An include/exclude rule attached to a playlist profile."""

    profile = pw.ForeignKeyField(PlaylistProfile, backref="rules", on_delete="CASCADE")
    rule_type = pw.TextField()      # include / exclude
    target_level = pw.TextField()   # composer / album / work / track
    target_id = pw.IntegerField()   # id of the referenced entity

    class Meta:
        table_name = "profile_rules"


# ---------------------------------------------------------------------------
# Overrides (overlay corrections — §6)
# ---------------------------------------------------------------------------

class Override(BaseModel):
    """An overlay correction applied on top of scanned tag data.

    Audio files are never modified in V1.  At least one of match_mb_id
    or match_relative_path must be present.
    """

    library = pw.ForeignKeyField(Library, backref="overrides", on_delete="CASCADE")
    scope = pw.TextField()                    # track / album
    match_mb_id = pw.TextField(null=True)     # MB recording/album id
    match_relative_path = pw.TextField(null=True)  # track or album folder relpath
    field = pw.TextField()                    # overridden field name
    value = pw.TextField()                    # corrected value
    updated_at = pw.DateTimeField()

    class Meta:
        table_name = "overrides"
