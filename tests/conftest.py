"""Shared fixtures: a fresh temp-file SQLite DB per test, plus row factories.

Tests build library data by inserting rows directly — no file scanning,
no mutagen, no audio files.
"""

import pytest

from music_manager.core.database import (
    database, initialize_database,
    Library, SourceFolder, Composer, Album, Work, Track,
    PlaylistProfile, ProfileSelection,
)


@pytest.fixture()
def db(tmp_path):
    """Initialize the shared Peewee database against a per-test temp file."""
    initialize_database(tmp_path / "test.db")
    yield database
    if not database.is_closed():
        database.close()


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
