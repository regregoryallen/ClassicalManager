"""v3.5 Phase 2: the schema must be creatable on MySQL/MariaDB.

SQLite cannot verify any of this. It ignores column widths entirely (type
affinity), so a CharField(max_length=512) there accepts a 5,000-character
value and every index succeeds — the constraints Phase 2 exists to satisfy
are invisible until a server is involved.

Skipped when no server is configured, so the default suite stays offline.
Point it at one with CM_TEST_MYSQL_URL, e.g.
    mysql://user:pass@host:3306/dbname
"""

import os
from urllib.parse import urlparse

import peewee as pw
import pytest

from music_manager.core.database import (
    MAX_KEY_LENGTH, MAX_PATH_LENGTH, Album, Composer, Library, Override,
    PlaylistProfile, ProfileSelection, SourceFolder, Track, Work,
    _ensure_track_indexes, database,
)

MODELS = [Library, SourceFolder, Composer, Album, Work, Track,
          PlaylistProfile, ProfileSelection, Override]

_URL = os.environ.get("CM_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="set CM_TEST_MYSQL_URL to run MySQL schema tests")


@pytest.fixture()
def mysql_db():
    """A connection with the schema built from scratch, dropped afterwards."""
    u = urlparse(_URL)
    db = pw.MySQLDatabase(
        u.path.lstrip("/"), host=u.hostname, port=u.port or 3306,
        user=u.username, password=u.password, charset="utf8mb4")
    database.initialize(db)
    db.connect()
    _drop_all(db)
    db.create_tables(MODELS)
    from music_manager.core.similarity import ensure_table
    ensure_table()
    _ensure_track_indexes()
    yield db
    _drop_all(db)
    db.close()


def _drop_all(db):
    db.execute_sql("SET FOREIGN_KEY_CHECKS=0")
    for (name,) in db.execute_sql("SHOW TABLES").fetchall():
        db.execute_sql(f"DROP TABLE IF EXISTS `{name}`")
    db.execute_sql("SET FOREIGN_KEY_CHECKS=1")


def _ddl(db, table):
    return db.execute_sql(f"SHOW CREATE TABLE `{table}`").fetchone()[1]


def test_every_table_and_index_is_created(mysql_db):
    """Before Phase 2 this failed: _ensure_track_indexes' non-unique index
    over a `text` column raised error 1071."""
    tables = {row[0] for row in mysql_db.execute_sql("SHOW TABLES").fetchall()}
    assert {m._meta.table_name for m in MODELS} <= tables
    names = {ix.name for ix in mysql_db.get_indexes("tracks")}
    assert "idx_tracks_library_relpath" in names
    assert "uq_tracks_folder_relpath" in names


def test_no_index_was_silently_rewritten_as_a_hash(mysql_db):
    """MariaDB 10.4+ rescues an over-long UNIQUE key by making it USING HASH,
    with no error and no warning. That is MariaDB-only (MySQL 8 rejects it)
    and a hash index cannot serve ordered or prefix scans, so its presence
    means a column is too wide — exactly what this phase capped."""
    offenders = [t for t in ("composers", "albums", "tracks",
                             "profile_selections", "track_analysis_snapshot")
                 if "USING HASH" in _ddl(mysql_db, t)]
    assert offenders == []


def test_indexed_columns_are_bounded_varchars(mysql_db):
    """TEXT cannot be indexed on MySQL without a prefix length."""
    for table, column, width in (
            ("tracks", "relative_path", MAX_PATH_LENGTH),
            ("albums", "album_key", MAX_PATH_LENGTH),
            ("composers", "norm_key", MAX_KEY_LENGTH),
            ("profile_selections", "key", MAX_PATH_LENGTH),
    ):
        col = next(c for c in mysql_db.get_columns(table) if c.name == column)
        assert col.data_type == "varchar", f"{table}.{column} is {col.data_type}"
        assert f"`{column}` varchar({width})" in _ddl(mysql_db, table)


def test_unindexed_long_text_is_still_text(mysql_db):
    """track_paths holds a JSON list and runs to 6,040 chars in the real
    library. It is not indexed, so it must NOT be capped."""
    col = next(c for c in mysql_db.get_columns("profile_selections")
               if c.name == "track_paths")
    assert col.data_type in ("text", "longtext")


def test_accented_names_survive_and_stay_distinct(mysql_db):
    """The server hands out latin1 connections by default, and its default
    collation treats Dvořák and Dvorak as equal — either would corrupt or
    merge composers."""
    lib = Library.create(name="L")
    a = Composer.create(library=lib, name="Dvořák", norm_key="dvořák")
    b = Composer.create(library=lib, name="Dvorak", norm_key="dvorak")
    assert Composer.get_by_id(a.id).name == "Dvořák"
    assert Composer.select().where(Composer.library == lib).count() == 2
    # Case must stay significant too, matching SQLite.
    Composer.create(library=lib, name="BACH", norm_key="BACH")
    Composer.create(library=lib, name="bach", norm_key="bach")
    assert Composer.select().where(Composer.library == lib).count() == 4
    assert b.norm_key == "dvorak"


def test_the_unique_track_path_index_is_enforced(mysql_db):
    lib = Library.create(name="L")
    sf = SourceFolder.create(library=lib, root_path="/music")
    album = Album.create(library=lib, folder=sf, album_key="A", title="A")
    fields = dict(library=lib, folder=sf, album=album, title="t",
                  disc_number=1, track_number=1, duration_ms=1)
    Track.create(relative_path="A/01.flac", **fields)
    with pytest.raises(pw.IntegrityError):
        Track.create(relative_path="A/01.flac", **fields)
    # Differing only by case is a DIFFERENT file under utf8mb4_bin.
    Track.create(relative_path="a/01.flac", **fields)


def test_a_path_at_the_cap_is_storable(mysql_db):
    """The cap must be usable to its stated limit, not one short."""
    lib = Library.create(name="L")
    sf = SourceFolder.create(library=lib, root_path="/music")
    album = Album.create(library=lib, folder=sf, album_key="A", title="A")
    path = "A/" + "x" * (MAX_PATH_LENGTH - 2)
    assert len(path) == MAX_PATH_LENGTH
    t = Track.create(library=lib, folder=sf, album=album, title="t",
                     relative_path=path, disc_number=1, track_number=1,
                     duration_ms=1)
    assert Track.get_by_id(t.id).relative_path == path
