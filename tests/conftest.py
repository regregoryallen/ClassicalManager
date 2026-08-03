"""Shared fixtures: a fresh database per test, plus row factories.

Tests build library data by inserting rows directly — no file scanning,
no mutagen, no audio files.

The whole suite can run against either backend:

    pytest                                        # SQLite (default, offline)
    CM_TEST_MYSQL_URL=mysql://u:p@host/db \\
        pytest --backend=mysql                    # the same tests on MySQL

SQLite cannot catch type-mapping faults — it has one numeric type and
ignores column widths — so it silently passed a FLOAT that truncated file
mtimes by half an hour, and TEXT columns that MySQL cannot index. Running
the real suite against a server is the only thing that finds those.
"""

import os
from urllib.parse import urlparse

import pytest

from music_manager.core.database import (
    database, initialize_database,
    Library, SourceFolder, Composer, Album, Work, Track,
    PlaylistProfile, ProfileSelection,
)

_ALL_TABLES = ("track_analysis", "track_analysis_snapshot", "profile_selections",
               "overrides", "playlist_profiles", "tracks", "works", "albums",
               "composers", "source_folders", "libraries")


def pytest_addoption(parser):
    parser.addoption(
        "--backend", action="store", default="sqlite",
        choices=("sqlite", "mysql"),
        help="Database backend for the suite. mysql needs CM_TEST_MYSQL_URL.")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "sqlite_only: test depends on SQLite specifics (schema introspection, "
        "file-level behaviour) and is skipped on a server backend.")


@pytest.fixture(scope="session")
def backend(request):
    return request.config.getoption("--backend")


@pytest.fixture(scope="session")
def mysql_settings(backend):
    """Resolved target for --backend=mysql, or None for SQLite."""
    if backend != "mysql":
        return None
    url = os.environ.get("CM_TEST_MYSQL_URL")
    if not url:
        raise pytest.UsageError(
            "--backend=mysql requires CM_TEST_MYSQL_URL, e.g. "
            "mysql://user:pass@host:3306/dbname")
    from music_manager.core.config import DbSettings
    u = urlparse(url)
    return DbSettings(backend="mysql", host=u.hostname, port=u.port or 3306,
                      name=u.path.lstrip("/"), user=u.username,
                      password=u.password or "")


def _ensure_schema():
    """Recreate the schema if it is missing.

    test_mysql_schema.py legitimately drops every table in the schema it is
    pointed at, so a later test cannot assume the tables are still there.
    Cheap when they are: one existence check.
    """
    from music_manager.core.database import (
        Override, _ensure_track_indexes,
    )
    if database.table_exists(Track._meta.table_name):
        return
    database.create_tables([Library, SourceFolder, Composer, Album, Work,
                            Track, PlaylistProfile, ProfileSelection, Override])
    from music_manager.core.similarity import ensure_table
    ensure_table()
    _ensure_track_indexes()


def _truncate_all():
    """Empty every table without touching the schema.

    Deliberately not drop-and-recreate: repeated DDL is both slow and, as a
    wedged dict_sys.latch on the real server showed, a good way to hang
    MySQL when a run is interrupted mid-statement.
    """
    database.execute_sql("SET FOREIGN_KEY_CHECKS=0")
    try:
        for table in _ALL_TABLES:
            try:
                database.execute_sql(f"TRUNCATE TABLE `{table}`")
            except Exception:
                pass  # table not created yet on the first pass
    finally:
        database.execute_sql("SET FOREIGN_KEY_CHECKS=1")


@pytest.fixture(scope="session")
def mysql_connection(mysql_settings):
    """Connect and build the schema ONCE for the whole session.

    Per-test initialize_database would rebind the proxy to a fresh database
    object each time, leaking the previous connection, and would repeat the
    DDL 200+ times for no benefit.
    """
    if mysql_settings is None:
        yield None                   # a bare return here yields nothing
        return
    initialize_database(settings=mysql_settings)
    concrete = database.obj          # the real database behind the proxy
    yield concrete
    if not concrete.is_closed():
        concrete.close()


@pytest.fixture()
def db(request, tmp_path, mysql_settings, mysql_connection):
    """The shared Peewee database, per test.

    SQLite gets a fresh temp file. MySQL keeps one schema for the session
    and is emptied between tests.
    """
    if mysql_settings is None:
        initialize_database(tmp_path / "test.db")
        yield database
        if not database.is_closed():
            database.close()
        return

    if request.node.get_closest_marker("sqlite_only"):
        pytest.skip("depends on SQLite specifics")
    # Other suites rebind the global proxy — the migration tests point it at
    # their own target, the io tests close it — so put it back rather than
    # assuming it still refers to the session connection.
    database.initialize(mysql_connection)
    if database.is_closed():
        database.connect()
    _ensure_schema()
    _truncate_all()
    yield database
    # The session connection stays open; closing per test would pay a full
    # handshake each time.


@pytest.fixture()
def lib(db):
    """A library with one source folder attached as `lib.test_folder`."""
    library = Library.create(name="TestLib")
    library.test_folder = SourceFolder.create(
        library=library, root_path="/music")
    return library


def make_album(lib, album_key, works, title=None, composer=None, year=None):
    """Create an album with works and tracks.

    Args:
        lib: Library fixture (must carry `test_folder`).
        album_key: Folder-style key, e.g. "Beethoven/Symphony 5".
        works: list of (work_name, n_tracks) or (work_name, n_tracks, source).
        composer: optional Composer applied to all works/tracks.

    Tracks are numbered sequentially across the album on disc 1, with
    relative_path f"{album_key}/{track_number:02d}.flac" and 60s duration.
    """
    folder = lib.test_folder
    album = Album.create(
        library=lib, folder=folder, album_key=album_key,
        title=title or album_key.rsplit("/", 1)[-1], year=year)
    track_no = 0
    for seq, spec in enumerate(works, start=1):
        work_name, n_tracks = spec[0], spec[1]
        source = spec[2] if len(spec) > 2 else "work_tag"
        work = Work.create(
            album=album, composer=composer, work_name=work_name,
            work_sequence=seq, work_source=source)
        for _ in range(n_tracks):
            track_no += 1
            Track.create(
                library=lib, folder=folder, album=album, work=work,
                composer=composer,
                title=f"{work_name} - part {track_no}",
                relative_path=f"{album_key}/{track_no:02d}.flac",
                disc_number=1, track_number=track_no,
                duration_ms=60_000)
    return album


def make_composer(lib, name):
    from music_manager.core.scanner import normalize_composer_name
    return Composer.create(
        library=lib, name=name, norm_key=normalize_composer_name(name))


def make_profile(lib, name="P1", **kwargs):
    defaults = dict(
        shuffle_mode="track",
        work_integrity="respect_selection",
        length_mode="all",
        length_value=None,
        seed=1234,
        no_repeat_tracks=True,
    )
    defaults.update(kwargs)
    return PlaylistProfile.create(library=lib, name=name, **defaults)


def add_sel(profile, level, key, excluded=False, pin_position=None,
            track_paths=None):
    return ProfileSelection.create(
        profile=profile, level=level, key=key, excluded=excluded,
        pin_position=pin_position, track_paths=track_paths)


def work_key(album_key, work_name, work_seq):
    """Build a composite work key without loading the Work row."""
    from music_manager.core.selection import COMPOSITE_SEP
    return COMPOSITE_SEP.join([album_key, work_name, str(work_seq)])


def track_ids(album, work_name=None):
    """All track IDs of an album, optionally restricted to one work."""
    q = Track.select(Track.id).where(Track.album == album)
    if work_name is not None:
        q = q.join(Work).where(Work.work_name == work_name)
    return {t.id for t in q}
