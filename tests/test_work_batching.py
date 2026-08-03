"""v3.5: work detection writes an album's works in one INSERT.

Creating each Work individually cost four round trips per work — a composer
fetch, a MAX for work_sequence, the INSERT, and an UPDATE assigning tracks —
which on a 5,420-work library was 45 seconds against a server. Works are now
built in memory with locally reserved primary keys and inserted per album.

That reservation is the risky part: a duplicate id would silently attach
tracks to the wrong work, and a column left out of the hand-built insert row
would silently become NULL. Both are pinned here.
"""

import pytest

from music_manager.core.database import (
    Album, Composer, Library, SourceFolder, Track, Work,
)
from music_manager.core.scanner import (
    PendingTrack, RawTags, detect_works, redetect_works,
)

from tests.conftest import make_album, make_composer


def _pending(album, **tag_kwargs):
    """PendingTracks for an album, in disc/track order."""
    out = []
    for track in (Track.select().where(Track.album == album)
                  .order_by(Track.disc_number, Track.track_number)):
        tags = RawTags(title=track.title, **tag_kwargs)
        out.append(PendingTrack(db_track=track, tags=tags))
    return out


def _clear_works(album):
    Track.update(work=None).where(Track.album == album).execute()
    Work.delete().where(Work.album == album).execute()


# ---------------------------------------------------------------------------
# Primary key reservation
# ---------------------------------------------------------------------------

def test_work_ids_are_unique_across_albums(lib):
    for name in ("A/One", "A/Two", "A/Three"):
        make_album(lib, name, [("W1", 2), ("W2", 3)])
    redetect_works(lib)

    ids = [w.id for w in Work.select()]
    assert len(ids) == len(set(ids)), "reserved a primary key twice"
    assert Track.select().where(Track.work.is_null()).count() == 0


def test_reserved_ids_do_not_collide_with_surviving_works(lib):
    """A work in another library must not have its row overwritten."""
    other = Library.create(name="Other")
    other_folder = SourceFolder.create(library=other, root_path="/other")
    other.test_folder = other_folder
    other_album = make_album(other, "B/Keep", [("Untouched", 2)])
    keep = {w.id: w.work_name for w in Work.select().where(Work.album == other_album)}

    make_album(lib, "A/One", [("W1", 2)])
    redetect_works(lib)

    for work_id, name in keep.items():
        assert Work.get_by_id(work_id).work_name == name


def test_repeated_redetect_keeps_ids_unique(lib):
    """The id counter is reused across runs in one process."""
    make_album(lib, "A/One", [("W1", 2), ("W2", 2)])
    redetect_works(lib)
    first = {w.id for w in Work.select()}
    redetect_works(lib)
    second = {w.id for w in Work.select()}

    assert len(second) == len(first)
    assert Track.select().where(Track.work.is_null()).count() == 0
    # Orphaned references would mean tracks point at deleted rows.
    assert Track.select().where(
        Track.work.is_null(False) & ~Track.work.in_(Work.select(Work.id))
    ).count() == 0


# ---------------------------------------------------------------------------
# The hand-built insert row
# ---------------------------------------------------------------------------

def test_every_work_column_is_written(lib):
    """A column omitted from the insert dict would silently be NULL."""
    composer = make_composer(lib, "Dvořák")
    album = Album.create(library=lib, folder=lib.test_folder,
                         album_key="A/Alb", title="Alb")
    for i in (1, 2):
        Track.create(library=lib, folder=lib.test_folder, album=album,
                     composer=composer, title=f"Movement {i}",
                     relative_path=f"A/Alb/{i:02d}.flac", disc_number=1,
                     track_number=i, duration_ms=60_000)

    detect_works(album, _pending(album, mb_work_id="mb-work-123"))

    work = Work.get(Work.album == album)
    assert work.work_name
    assert work.work_source == "mb_workid"
    assert work.musicbrainz_work_id == "mb-work-123"
    assert work.work_sequence == 1
    assert work.composer_id == composer.id     # modal composer of its tracks
    assert work.album_id == album.id
    assert {t.work_id for t in Track.select().where(Track.album == album)} == {work.id}


def test_work_sequence_increments_within_an_album(lib):
    """work_sequence came from a MAX query per work; it is cached now."""
    album = Album.create(library=lib, folder=lib.test_folder,
                         album_key="A/Alb", title="Alb")
    for i in range(1, 4):
        Track.create(library=lib, folder=lib.test_folder, album=album,
                     title=f"Standalone {i}",
                     relative_path=f"A/Alb/{i:02d}.flac", disc_number=1,
                     track_number=i, duration_ms=60_000)

    detect_works(album, _pending(album))

    sequences = sorted(w.work_sequence for w in Work.select().where(Work.album == album))
    assert sequences == [1, 2, 3]


# ---------------------------------------------------------------------------
# Deferred-write hygiene
# ---------------------------------------------------------------------------

def test_a_failed_album_does_not_leak_into_the_next(lib, monkeypatch):
    """Pending works are cleared on entry, so a part-way failure cannot
    attach one album's works to the following album."""
    import music_manager.core.scanner as scanner

    good = make_album(lib, "A/Good", [("W", 2)])
    bad = make_album(lib, "A/Bad", [("W", 2)])
    _clear_works(good)
    _clear_works(bad)

    real_flush = scanner._flush_works
    monkeypatch.setattr(scanner, "_flush_works",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        detect_works(bad, _pending(bad))

    monkeypatch.setattr(scanner, "_flush_works", real_flush)
    detect_works(good, _pending(good))

    # Only the good album's works exist, and none point at the bad album.
    assert Work.select().where(Work.album == bad).count() == 0
    assert Work.select().where(Work.album == good).count() > 0
    for work in Work.select():
        assert work.album_id == good.id


def test_tracks_point_at_the_work_that_owns_them(lib):
    """The whole point of reserving ids before the insert."""
    album = make_album(lib, "A/Alb", [("First", 2), ("Second", 3)])
    _clear_works(album)
    detect_works(album, _pending(album, work="Grouped"))

    for track in Track.select().where(Track.album == album):
        assert track.work_id is not None
        assert Work.get_by_id(track.work_id).album_id == album.id
