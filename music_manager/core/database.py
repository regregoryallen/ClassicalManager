"""Peewee ORM models and database connection management.

Defines all tables from §4.2 of the specification:
  Libraries, SourceFolders, Composers, Albums, Works, Tracks,
  PlaylistProfiles, ProfileSelections, Overrides.

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
        ProfileSelection,
        Override,
    ])

    # Migrations: add columns that may not exist in older databases.
    # IMPORTANT: always use null=True in migration field definitions — Peewee's
    # SqliteMigrator adds a NOT NULL constraint via _update_column, which drops
    # and recreates the table, triggering ON DELETE CASCADE on related tables.
    from playhouse.migrate import SqliteMigrator, migrate as run_migrate
    migrator = SqliteMigrator(database)
    columns = {col.name for col in database.get_columns("libraries")}
    if "plex_section" not in columns:
        run_migrate(migrator.add_column("libraries", "plex_section",
                                        pw.TextField(null=True, default="")))
        logger.info("Migrated: added plex_section to libraries")

    track_cols = {col.name for col in database.get_columns("tracks")}
    if "work_tag" not in track_cols:
        run_migrate(
            migrator.add_column("tracks", "work_tag", pw.TextField(null=True)),
            migrator.add_column("tracks", "mb_work_id", pw.TextField(null=True)),
        )
        logger.info("Migrated: added work_tag, mb_work_id to tracks")
    if "file_mtime" not in track_cols:
        run_migrate(
            migrator.add_column("tracks", "file_mtime", pw.FloatField(null=True)),
            migrator.add_column("tracks", "file_size", pw.IntegerField(null=True)),
        )
        logger.info("Migrated: added file_mtime, file_size to tracks")
    if "genre" not in track_cols:
        run_migrate(
            migrator.add_column("tracks", "genre", pw.TextField(null=True)),
            migrator.add_column("tracks", "performer", pw.TextField(null=True)),
            migrator.add_column("tracks", "conductor", pw.TextField(null=True)),
            migrator.add_column("tracks", "ensemble", pw.TextField(null=True)),
        )
        logger.info("Migrated: added genre, performer, conductor, ensemble to tracks")

    profile_cols = {col.name for col in database.get_columns("playlist_profiles")}
    if "separate_composers" not in profile_cols:
        run_migrate(
            migrator.add_column("playlist_profiles", "separate_composers",
                                pw.BooleanField(null=True, default=False)),
            migrator.add_column("playlist_profiles", "separate_albums",
                                pw.BooleanField(null=True, default=False)),
            migrator.add_column("playlist_profiles", "separate_forms",
                                pw.BooleanField(null=True, default=False)),
        )
        logger.info("Migrated: added separation columns to playlist_profiles")

    from music_manager.core.similarity import ensure_table
    ensure_table()

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
    plex_section = pw.TextField(default="")  # Plex library section name

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
    genre = pw.TextField(null=True)              # genre tag from file
    performer = pw.TextField(null=True)          # performing artist (TPE1/ARTIST)
    conductor = pw.TextField(null=True)          # conductor (TPE3/CONDUCTOR)
    ensemble = pw.TextField(null=True)           # orchestra/ensemble
    work_tag = pw.TextField(null=True)          # raw WORK tag from file
    mb_work_id = pw.TextField(null=True)        # per-track MusicBrainz work ID from file
    file_mtime = pw.FloatField(null=True)       # file modification time (os.stat)
    file_size = pw.IntegerField(null=True)       # file size in bytes

    class Meta:
        table_name = "tracks"


# ---------------------------------------------------------------------------
# Playlist profiles & selections
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
    separate_composers = pw.BooleanField(default=False)
    separate_albums = pw.BooleanField(default=False)
    separate_forms = pw.BooleanField(default=False)

    class Meta:
        table_name = "playlist_profiles"


class ProfileSelection(BaseModel):
    """A single selection entry in a playlist profile.

    Each row represents one item the user has explicitly added to or
    excluded from the profile.  Uses stable text keys so entries survive
    library rescans that reassign integer IDs.

    Semantics:
      - excluded=False: this item is ADDED to the playlist.
      - excluded=True:  this item is an EXCEPTION (removed from a broader add).

    Specificity is structural: track overrides work, work overrides album.
    The most specific selection matching a track always wins.
    """

    profile = pw.ForeignKeyField(PlaylistProfile, backref="selections",
                                 on_delete="CASCADE")
    level = pw.TextField()          # 'album' / 'work' / 'track'
    key = pw.TextField()            # stable text key (album_key, composite work key, or relative_path)
    excluded = pw.BooleanField(default=False)  # False=add, True=exception
    pin_position = pw.IntegerField(null=True)  # 1-5 or NULL; only for level='work'
    track_paths = pw.TextField(null=True)  # JSON list of relative_paths; work-level only.
                                           # Breadcrumbs for reconciliation after rescan.

    class Meta:
        table_name = "profile_selections"
        indexes = (
            (("profile", "level", "key"), True),  # one entry per item per profile
        )


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
