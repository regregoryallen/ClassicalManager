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

from playhouse.shortcuts import ReconnectMixin

from music_manager.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DATABASE_PATH = PROJECT_ROOT / "music_manager.db"

# Text that takes part in an index must have a declared width on MySQL.
# 512 is the largest that keeps a composite index inside InnoDB's 3072-byte
# key limit: (INT, VARCHAR(512)) at utf8mb4 is 2052 bytes, while VARCHAR(768)
# overflows it. Going wider would not fail loudly on MariaDB — it silently
# rewrites over-long UNIQUE keys as USING HASH, which MySQL rejects outright
# and which cannot serve ordered or prefix scans. SQLite ignores the width
# entirely (type affinity), so this only ever binds on a server backend.
MAX_PATH_LENGTH = 512
MAX_KEY_LENGTH = 255

# A proxy, so the concrete backend (SQLite file or MySQL/MariaDB server) can
# be chosen at startup while the models below stay bound to one object.
database = pw.DatabaseProxy()


class ReconnectMySQLDatabase(ReconnectMixin, pw.MySQLDatabase):
    """MySQL that survives the server closing an idle connection.

    A server drops idle connections — MariaDB's wait_timeout defaults to
    8 hours — and peewee holds exactly one. Leaving the GUI open overnight
    was enough: the connection went away and the next click had nowhere to
    go. SQLite never had this failure mode because there is no connection
    to lose, so it arrived with the server backend.

    ReconnectMixin retries once on a connection-lost error. It deliberately
    refuses inside an explicit transaction, where a silent retry could
    replay half a unit of work.
    """


def _make_database(settings) -> pw.Database:
    """Build the concrete peewee database for the resolved settings."""
    if settings.backend == "mysql":
        return ReconnectMySQLDatabase(
            settings.name,
            host=settings.host, port=settings.port,
            user=settings.user, password=settings.password,
            # The server hands out latin1 connections by default; without
            # this, accented composer names are corrupted on write.
            charset=settings.charset,
        )
    # SQLite only: WAL for concurrent readers, and FKs are off by default.
    return pw.SqliteDatabase(str(settings.path), pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
    })


class DuplicateTracksError(Exception):
    """Raised at startup when duplicate (folder, relative_path) track rows
    exist — decision D3: report them and refuse to proceed until fixed."""


def find_duplicate_track_paths() -> list[tuple[int, str, int]]:
    """Return (folder_id, relative_path, count) for paths stored more
    than once. Under the album-is-a-folder design this should be
    impossible; rows here indicate a scan bug or manual DB edits."""
    cursor = database.execute_sql(
        "SELECT folder_id, relative_path, COUNT(*) AS c FROM tracks "
        "GROUP BY folder_id, relative_path HAVING c > 1 ORDER BY c DESC"
    )
    return list(cursor.fetchall())


def _ensure_track_indexes() -> None:
    """Create the track path indexes (V3, F9).

    - (library_id, relative_path): plain index — this is the lookup key
      for track-level selections and override matching.
    - (folder_id, relative_path): UNIQUE — guarded by a duplicate check.
      Duplicates are a hard stop (D3): raise with the offending rows so
      the user can fix the underlying files/DB and restart.
    """
    # get_indexes() works on every backend; PRAGMA index_list does not, and
    # CREATE INDEX IF NOT EXISTS is not portable either (MySQL rejects it).
    index_names = {ix.name for ix in database.get_indexes("tracks")}

    if "idx_tracks_library_relpath" not in index_names:
        database.execute_sql(
            "CREATE INDEX idx_tracks_library_relpath "
            "ON tracks (library_id, relative_path)"
        )

    if "uq_tracks_folder_relpath" in index_names:
        return  # uniqueness already enforced; no duplicates possible

    dups = find_duplicate_track_paths()
    if dups:
        listing = "\n".join(
            f"  folder {folder_id}: {rel_path} (x{count})"
            for folder_id, rel_path, count in dups[:20]
        )
        more = f"\n  ... and {len(dups) - 20} more" if len(dups) > 20 else ""
        raise DuplicateTracksError(
            f"Found {len(dups)} duplicate track path(s) in the database. "
            f"The same file is stored more than once, which corrupts "
            f"selection resolution.\n\n{listing}{more}\n\n"
            f"Fix the underlying cause (duplicate files, overlapping "
            f"source folders, or manual DB edits), run a full rescan of "
            f"the affected library, and restart. The app will not "
            f"proceed while duplicates exist."
        )

    database.execute_sql(
        "CREATE UNIQUE INDEX uq_tracks_folder_relpath "
        "ON tracks (folder_id, relative_path)"
    )
    logger.info("Created unique index on tracks (folder_id, relative_path)")


def initialize_database(db_path: Path | None = None,
                        settings=None) -> pw.Database:
    """Initialize the database connection and create tables.

    Args:
        db_path: A SQLite file to use, bypassing config entirely. Tests and
                 the GUI's fall-back-to-local path rely on this.
        settings: A resolved config.DbSettings. Takes precedence over
                 db_path; when both are omitted, config decides.

    Returns:
        The connected peewee database.
    """
    from music_manager.core.config import DbSettings, resolve_db_settings

    if settings is None:
        settings = (DbSettings(backend="sqlite", path=Path(db_path))
                    if db_path is not None else resolve_db_settings())

    database.initialize(_make_database(settings))
    database.connect(reuse_if_open=True)
    logger.info("Database connected: %s", settings.describe())

    if _schema_is_current():
        logger.debug("Schema already current; skipping DDL")
        return database

    _create_and_migrate(settings)
    return database


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------

class BaseModel(pw.Model):
    """Base model binding all tables to the shared database instance."""

    class Meta:
        database = database


# ---------------------------------------------------------------------------
# Schema marker
# ---------------------------------------------------------------------------

class SchemaState(BaseModel):
    """Which schema version this database has been built to.

    Exists so startup can answer "is the schema current?" with one SELECT
    instead of inspecting every table. See _schema_is_current.
    """

    version = pw.IntegerField()

    class Meta:
        table_name = "schema_state"


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
    norm_key = pw.CharField(max_length=MAX_KEY_LENGTH)  # normalized key for dedup/matching

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
    album_key = pw.CharField(max_length=MAX_PATH_LENGTH)  # folder's relative path = album identity
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
    relative_path = pw.CharField(max_length=MAX_PATH_LENGTH)  # POSIX, relative to SourceFolder.root_path
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
    # DOUBLE, not FLOAT: a Unix timestamp needs ~17 significant digits and
    # MySQL's single-precision FLOAT keeps ~7, which shifted real mtimes by
    # over half an hour — every file would look changed to an incremental
    # scan, and analysis preservation compares on this value.
    file_mtime = pw.DoubleField(null=True)      # file modification time (os.stat)
    file_size = pw.IntegerField(null=True)       # file size in bytes
    # When this track first entered the library. Set on INSERT only and
    # preserved across full rescans — file_mtime is the FILE's time and
    # cannot answer "what did the last scan add" (v3.3).
    first_seen = pw.DateTimeField(null=True)

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
    # True for machine-created profiles (e.g. per-import track sets).
    # These are excluded from "is this track used by any profile?"
    # questions — otherwise an import profile would instantly mark every
    # newly imported track as assigned and silence Find Unused, which is
    # the workflow the import profile exists to support (v3.3).
    auto_generated = pw.BooleanField(default=False, null=True)

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
    level = pw.CharField(max_length=16)  # 'album' / 'work' / 'track'
    key = pw.CharField(max_length=MAX_PATH_LENGTH)  # stable text key (album_key, composite work key, or relative_path)
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


# Bump when the DDL in _create_and_migrate changes. Recorded in the
# schema_state table so a startup that finds a matching version can skip
# the schema work entirely.
SCHEMA_VERSION = 1


def _schema_is_current() -> bool:
    """True when the schema is already built and at SCHEMA_VERSION.

    One query instead of roughly thirty metadata round trips. Every startup
    used to run create_tables across nine models, three get_columns calls
    and two index inspections — schema DDL on every GUI launch, every CLI
    command and every script. Free against a SQLite file. Against a server
    with a second client connected it is metadata-lock contention on every
    table, and it wedged the instance twice: a stuck
    "SHOW INDEX FROM playlist_profiles" blocking everything behind it.
    """
    try:
        row = database.execute_sql(
            "SELECT version FROM schema_state").fetchone()
    except Exception:
        return False        # table absent: fresh database or older layout
    return bool(row) and row[0] == SCHEMA_VERSION


def _record_schema_version() -> None:
    SchemaState.delete().execute()
    SchemaState.create(version=SCHEMA_VERSION)


def _create_and_migrate(settings) -> None:
    """Build or upgrade the schema. Runs only when the marker does not match."""
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
    from playhouse.migrate import (MySQLMigrator, SqliteMigrator,
                                   migrate as run_migrate)
    migrator = (MySQLMigrator(database) if settings.backend == "mysql"
                else SqliteMigrator(database))
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
            migrator.add_column("tracks", "file_mtime", pw.DoubleField(null=True)),
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

    if "auto_generated" not in profile_cols:
        run_migrate(
            migrator.add_column("playlist_profiles", "auto_generated",
                                pw.BooleanField(null=True, default=False)),
        )
        logger.info("Migrated: added auto_generated to playlist_profiles")

    if "first_seen" not in track_cols:
        run_migrate(
            migrator.add_column("tracks", "first_seen",
                                pw.DateTimeField(null=True)),
        )
        logger.info("Migrated: added first_seen to tracks")

    from music_manager.core.similarity import ensure_table
    ensure_table()

    _ensure_track_indexes()


    database.create_tables([SchemaState])
    _record_schema_version()
    logger.info("Database schema created/verified (version %d)", SCHEMA_VERSION)
