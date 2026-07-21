"""Phase 2 tests: track path indexes (F9/D3) and similarity-analysis
preservation across full rescans (F8).

The scan itself needs real audio files, so the snapshot/restore helpers
are tested directly against fabricated rows — the same code path
scan_library runs before/after its delete-and-rebuild.

The snapshot is DURABLE (a table in the same DB, consumed only on
successful restore) after a production incident where an in-memory
snapshot was lost to a suspend mid-rescan (2026-07-20).
"""

import json
from datetime import datetime, timezone

import pytest

from music_manager.core.database import (
    DuplicateTracksError, Track, _ensure_track_indexes,
    find_duplicate_track_paths,
)
from music_manager.core.scanner import _restore_analyses, _snapshot_analyses
from music_manager.core.similarity import (
    FEATURE_VERSION, AnalysisSnapshot, TrackAnalysis,
)

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

def _simulate_rescan(lib, album, specs):
    """Delete the album's tracks and recreate them per (path, mtime, size)."""
    Track.delete().where(Track.album == album).execute()
    for i, (path, mtime, size) in enumerate(specs, start=1):
        Track.create(
            library=lib, folder=lib.test_folder, album=album,
            title=f"rescanned {i}", relative_path=path,
            disc_number=1, track_number=i, duration_ms=60_000,
            file_mtime=mtime, file_size=size)


def test_snapshot_and_restore_preserves_unchanged_analyses(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    for t in Track.select().where(Track.album == album):
        _analyze_fake(t, features=[float(t.id)] * 31)

    assert _snapshot_analyses(lib) == 3
    # The snapshot is durable — real rows in the DB, not process memory.
    assert AnalysisSnapshot.select().count() == 3

    old_paths = [t.relative_path for t in
                 Track.select().where(Track.album == album)]
    _simulate_rescan(lib, album,
                     [(p, 1000.0, 4096) for p in old_paths])
    assert TrackAnalysis.select().count() == 0  # CASCADE took them

    assert _restore_analyses(lib) == 3
    assert TrackAnalysis.select().count() == 3
    # Consumed exactly once — on success.
    assert AnalysisSnapshot.select().count() == 0

    for ta in TrackAnalysis.select():
        assert ta.track.title.startswith("rescanned")
        assert len(json.loads(ta.features)) == 31
        assert ta.feature_version == FEATURE_VERSION


def test_restore_skips_changed_and_unknown_files(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    for t in Track.select().where(Track.album == album):
        _analyze_fake(t)

    _snapshot_analyses(lib)
    old_paths = sorted(t.relative_path for t in
                       Track.select().where(Track.album == album))
    # Track 1: unchanged. Track 2: mtime changed. Track 3: size changed.
    _simulate_rescan(lib, album, [
        (old_paths[0], 1000.0, 4096),
        (old_paths[1], 2000.0, 4096),
        (old_paths[2], 1000.0, 9999),
    ])

    assert _restore_analyses(lib) == 1
    (ta,) = list(TrackAnalysis.select())
    assert ta.track.relative_path == old_paths[0]


def test_restore_skips_tracks_without_mtime(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    _set_file_stats(album, mtime=1000.0)
    (track,) = list(Track.select().where(Track.album == album))
    _analyze_fake(track)

    _snapshot_analyses(lib)
    _simulate_rescan(lib, album, [(track.relative_path, None, None)])

    assert _restore_analyses(lib) == 0


def test_empty_snapshot_is_noop(lib):
    assert _restore_analyses(lib) == 0


def test_failed_restore_is_retried_by_the_next_scan(lib):
    """The 2026-07-20 incident: restore never ran (crash), snapshot must
    survive and be consumable by a later scan's restore attempt."""
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    for t in Track.select().where(Track.album == album):
        _analyze_fake(t)

    old_paths = [t.relative_path for t in
                 Track.select().where(Track.album == album)]
    _snapshot_analyses(lib)
    _simulate_rescan(lib, album,
                     [(p, 1000.0, 4096) for p in old_paths])
    # Crash here: no restore ran. Snapshot rows still present.
    assert AnalysisSnapshot.select().count() == 2
    assert TrackAnalysis.select().count() == 0

    # ... time passes; a later scan (e.g. incremental) retries:
    assert _restore_analyses(lib) == 2
    assert AnalysisSnapshot.select().count() == 0


def test_retry_skips_tracks_already_reanalyzed(lib):
    """If the user re-analyzed some tracks between the crash and the
    retry, the leftover snapshot must not collide with them."""
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    for t in Track.select().where(Track.album == album):
        _analyze_fake(t)

    old_paths = sorted(t.relative_path for t in
                       Track.select().where(Track.album == album))
    _snapshot_analyses(lib)
    _simulate_rescan(lib, album,
                     [(p, 1000.0, 4096) for p in old_paths])

    # User manually re-analyzed track 1 before the retry.
    t1 = Track.get(Track.relative_path == old_paths[0])
    _analyze_fake(t1, features=[9.9] * 31)

    assert _restore_analyses(lib) == 1  # only track 2 restored
    assert TrackAnalysis.select().count() == 2
    ta1 = TrackAnalysis.get(TrackAnalysis.track == t1)
    assert json.loads(ta1.features) == [9.9] * 31  # fresh one kept


def test_resnapshot_updates_rows_without_losing_leftovers(lib):
    """A new scan's snapshot upserts current analyses but keeps leftover
    rows for paths it doesn't cover (pending restore from a crash)."""
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    _set_file_stats(album, mtime=1000.0, size=4096)
    (track,) = list(Track.select().where(Track.album == album))
    _analyze_fake(track)

    # Leftover from an earlier crashed scan, different path.
    AnalysisSnapshot.create(
        library=lib, folder_id=lib.test_folder.id,
        relative_path="A/Gone/01.flac", features="[1]",
        volatility=None, analyzed_at=datetime.now(timezone.utc),
        feature_version=FEATURE_VERSION, file_mtime=1.0, file_size=1)

    assert _snapshot_analyses(lib) == 1
    assert AnalysisSnapshot.select().count() == 2  # upsert + leftover


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
