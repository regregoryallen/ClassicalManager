"""Phase 2 tests: track path indexes (F9/D3) and similarity-analysis
preservation across full rescans (F8).

The scan itself needs real audio files, so the snapshot/restore helpers
are tested directly against fabricated rows — the same code path
scan_library runs before/after its delete-and-rebuild.
"""

import json
from datetime import datetime, timezone

import pytest

from music_manager.core.database import (
    DuplicateTracksError, Track, _ensure_track_indexes,
    find_duplicate_track_paths,
)
from music_manager.core.scanner import _restore_analyses, _snapshot_analyses
from music_manager.core.similarity import FEATURE_VERSION, TrackAnalysis

from tests.conftest import make_album


def _set_file_stats(album, mtime=1000.0, size=4096):
    for t in Track.select().where(Track.album == album):
        t.file_mtime = mtime
        t.file_size = size
        t.save()


def _analyze_fake(track, features=None):
    return TrackAnalysis.create(
        track=track,
        features=json.dumps(features or [0.5] * 31),
        volatility=0.25,
        analyzed_at=datetime.now(timezone.utc),
        feature_version=FEATURE_VERSION,
    )


# ---------------------------------------------------------------------------
# F8: analysis preservation
# ---------------------------------------------------------------------------

def test_snapshot_and_restore_preserves_unchanged_analyses(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    for t in Track.select().where(Track.album == album):
        _analyze_fake(t, features=[float(t.id)] * 31)

    snapshot = _snapshot_analyses(lib)
    assert len(snapshot) == 3

    # Simulate a full rescan: tracks deleted (CASCADE kills analyses),
    # then recreated at the same paths with new IDs.
    old_paths = [t.relative_path for t in
                 Track.select().where(Track.album == album)]
    Track.delete().where(Track.album == album).execute()
    assert TrackAnalysis.select().count() == 0

    for i, path in enumerate(old_paths, start=1):
        Track.create(
            library=lib, folder=lib.test_folder, album=album,
            title=f"rescanned {i}", relative_path=path,
            disc_number=1, track_number=i, duration_ms=60_000,
            file_mtime=1000.0, file_size=4096)

    preserved = _restore_analyses(lib, snapshot)
    assert preserved == 3
    assert TrackAnalysis.select().count() == 3

    # Analyses are attached to the NEW track rows with features intact.
    for ta in TrackAnalysis.select():
        assert ta.track.title.startswith("rescanned")
        assert len(json.loads(ta.features)) == 31
        assert ta.feature_version == FEATURE_VERSION


def test_restore_skips_changed_and_unknown_files(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    for t in Track.select().where(Track.album == album):
        _analyze_fake(t)

    snapshot = _snapshot_analyses(lib)
    old_paths = sorted(t.relative_path for t in
                       Track.select().where(Track.album == album))
    Track.delete().where(Track.album == album).execute()

    # Track 1: unchanged. Track 2: mtime changed. Track 3: size changed.
    specs = [
        (old_paths[0], 1000.0, 4096),
        (old_paths[1], 2000.0, 4096),
        (old_paths[2], 1000.0, 9999),
    ]
    for i, (path, mtime, size) in enumerate(specs, start=1):
        Track.create(
            library=lib, folder=lib.test_folder, album=album,
            title=f"t{i}", relative_path=path,
            disc_number=1, track_number=i, duration_ms=60_000,
            file_mtime=mtime, file_size=size)

    assert _restore_analyses(lib, snapshot) == 1
    (ta,) = list(TrackAnalysis.select())
    assert ta.track.relative_path == old_paths[0]


def test_restore_skips_tracks_without_mtime(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    _set_file_stats(album, mtime=1000.0)
    (track,) = list(Track.select().where(Track.album == album))
    _analyze_fake(track)

    snapshot = _snapshot_analyses(lib)
    Track.delete().where(Track.album == album).execute()
    Track.create(
        library=lib, folder=lib.test_folder, album=album,
        title="no stats", relative_path=track.relative_path,
        disc_number=1, track_number=1, duration_ms=60_000,
        file_mtime=None, file_size=None)

    assert _restore_analyses(lib, snapshot) == 0


def test_empty_snapshot_is_noop(lib):
    assert _restore_analyses(lib, {}) == 0


# ---------------------------------------------------------------------------
# F9/D3: path indexes and the duplicate hard stop
# ---------------------------------------------------------------------------

def test_fresh_database_gets_both_indexes(db):
    names = {row[1] for row in
             db.execute_sql("PRAGMA index_list('tracks')").fetchall()}
    assert "idx_tracks_library_relpath" in names
    assert "uq_tracks_folder_relpath" in names


def test_unique_index_blocks_duplicate_inserts(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    with pytest.raises(Exception):  # peewee IntegrityError
        Track.create(
            library=lib, folder=lib.test_folder, album=album,
            title="dup", relative_path="A/Alb1/01.flac",
            disc_number=1, track_number=99, duration_ms=1)


def test_duplicates_are_a_hard_stop_D3(lib, db):
    """Simulate a pre-V3 database containing duplicates: the unique
    index must NOT be created and startup must fail with a report."""
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    db.execute_sql("DROP INDEX uq_tracks_folder_relpath")
    Track.create(
        library=lib, folder=lib.test_folder, album=album,
        title="dup", relative_path="A/Alb1/01.flac",
        disc_number=1, track_number=99, duration_ms=1)

    dups = find_duplicate_track_paths()
    assert len(dups) == 1
    assert dups[0][1] == "A/Alb1/01.flac"
    assert dups[0][2] == 2

    with pytest.raises(DuplicateTracksError) as exc_info:
        _ensure_track_indexes()
    assert "A/Alb1/01.flac" in str(exc_info.value)

    # No unique index was sneaked in alongside the failure.
    names = {row[1] for row in
             db.execute_sql("PRAGMA index_list('tracks')").fetchall()}
    assert "uq_tracks_folder_relpath" not in names

    # After the user fixes the duplicate, startup succeeds.
    Track.delete().where(Track.title == "dup").execute()
    _ensure_track_indexes()
    names = {row[1] for row in
             db.execute_sql("PRAGMA index_list('tracks')").fetchall()}
    assert "uq_tracks_folder_relpath" in names
