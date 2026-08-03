"""v3.5 Phase 3: copying a database between backends.

These run SQLite -> SQLite so they need no server. That cannot exercise
type mapping (SQLite has one numeric type and ignores column widths), so
the cross-backend fidelity checks live in test_mysql_schema.py.
"""

import json
from datetime import datetime, timezone

import pytest

from music_manager.core.config import DbSettings
from music_manager.core.database import (
    Album, Composer, Library, Override, SourceFolder, Track, Work,
    initialize_database, database,
)
from music_manager.core.db_migrate import _normalize, migrate_database


def _build_source(path):
    """A small library with the awkward values: unicode, a precise mtime,
    a tz-aware timestamp, and a NULL foreign key."""
    initialize_database(path)
    lib = Library.create(name="Src")
    folder = SourceFolder.create(library=lib, root_path="/music")
    composer = Composer.create(library=lib, name="Dvořák", norm_key="dvořák")
    album = Album.create(library=lib, folder=folder, album_key="A", title="Álbum")
    work = Work.create(album=album, composer=composer, work_name="Œuvre",
                       work_sequence=1, work_source="work_tag")
    for i in (1, 2):
        Track.create(library=lib, folder=folder, album=album, work=work,
                     composer=composer, title=f"Träck {i}",
                     relative_path=f"A/{i:02d}.flac", disc_number=1,
                     track_number=i, duration_ms=60_000,
                     file_mtime=1666807963.287016 + i, file_size=1234)
    # A work with no composer: the NULL FK must survive.
    Work.create(album=album, work_name="No composer", work_sequence=2,
                work_source="heuristic")
    Override.create(library=lib, scope="track", field="composer",
                    value="Dvořák", match_relative_path="A/01.flac",
                    updated_at=datetime.now(timezone.utc))
    from music_manager.core.similarity import TrackAnalysis, ensure_table
    ensure_table()
    TrackAnalysis.create(track=Track.get(Track.track_number == 1),
                         features=json.dumps([0.25] * 31), volatility=0.5,
                         analyzed_at=datetime.now(timezone.utc),
                         feature_version=1)
    database.close()


@pytest.fixture()
def source(tmp_path):
    path = tmp_path / "source.db"
    _build_source(path)
    return DbSettings(backend="sqlite", path=path)


@pytest.fixture()
def target(tmp_path):
    return DbSettings(backend="sqlite", path=tmp_path / "target.db")


def _rows(settings, model):
    initialize_database(settings.path)
    out = list(model.select().order_by(model.id).dicts())
    database.close()
    return out


def test_every_table_is_copied_and_verified(source, target):
    report = migrate_database(source, target)
    assert report.ok, [t.mismatch for t in report.tables if t.mismatch]
    counts = {t.table: t.copied for t in report.tables}
    assert counts["tracks"] == 2
    assert counts["works"] == 2
    assert counts["composers"] == 1
    assert counts["track_analysis"] == 1
    assert all(t.verified is True for t in report.tables if t.source_rows)


def test_primary_keys_are_preserved(source, target):
    """Selections and overrides key on ids and paths; renumbering would
    quietly detach them."""
    before = _rows(source, Track)
    migrate_database(source, target)
    after = _rows(target, Track)
    assert [r["id"] for r in before] == [r["id"] for r in after]
    assert [r["album"] for r in before] == [r["album"] for r in after]


def test_values_survive_including_unicode_and_precision(source, target):
    migrate_database(source, target)
    tracks = _rows(target, Track)
    assert tracks[0]["title"] == "Träck 1"
    # The FLOAT-vs-DOUBLE bug: this must be exact, not rounded to ~7 digits.
    assert tracks[0]["file_mtime"] == 1666807964.287016
    assert _rows(target, Composer)[0]["name"] == "Dvořák"


def test_null_foreign_keys_survive(source, target):
    migrate_database(source, target)
    works = _rows(target, Work)
    assert [w["composer"] for w in works] == [1, None]


def test_a_non_empty_target_is_refused(source, target):
    migrate_database(source, target)
    report = migrate_database(source, target)
    assert not report.ok
    assert "already contains data" in report.error
    assert "tracks=2" in report.error


def test_force_replaces_the_target(source, target):
    migrate_database(source, target)
    report = migrate_database(source, target, force=True)
    assert report.ok
    assert len(_rows(target, Track)) == 2  # not doubled


def test_dry_run_writes_nothing(source, target):
    report = migrate_database(source, target, dry_run=True)
    assert report.dry_run
    assert sum(t.source_rows for t in report.tables) > 0
    assert report.total_rows == 0
    assert not target.path.exists() or not _rows(target, Track)


def test_verification_catches_a_corrupted_copy(source, target, monkeypatch):
    """The check must fail when values change, not merely when counts do —
    that is what caught mtimes being truncated by MySQL's FLOAT."""
    import music_manager.core.db_migrate as mod
    real = mod._read_rows
    track_reads = {"n": 0}

    def corrupt_on_readback(db, model):
        rows = real(db, model)
        if model is not Track:
            return rows
        track_reads["n"] += 1
        # Read 1 is the source; read 2 is the post-write verification read.
        # Corrupting the source instead would just copy the bad value across
        # and verify clean, proving nothing.
        if track_reads["n"] == 2 and rows:
            first = list(rows[0])
            first[-1] = 999999
            rows = [tuple(first)] + list(rows[1:])
        return rows

    monkeypatch.setattr(mod, "_read_rows", corrupt_on_readback)
    report = migrate_database(source, target)
    tracks = next(t for t in report.tables if t.table == "tracks")
    assert tracks.verified is False
    assert tracks.mismatch
    assert not report.ok


# ---------------------------------------------------------------------------
# Value normalization
# ---------------------------------------------------------------------------

def test_aware_and_naive_utc_compare_equal():
    """SQLite keeps '+00:00' in text; MySQL DATETIME has no timezone. The
    instant is the same and must not read as a mismatch."""
    aware = datetime(2026, 7, 24, 18, 1, 28, tzinfo=timezone.utc)
    assert _normalize(aware) == _normalize(datetime(2026, 7, 24, 18, 1, 28))
    assert _normalize("2026-07-24 18:01:28+00:00") == _normalize(aware)


def test_sub_second_precision_is_ignored_for_timestamps():
    """DATETIME stores whole seconds."""
    assert (_normalize(datetime(2026, 7, 24, 18, 1, 28, 500000))
            == _normalize(datetime(2026, 7, 24, 18, 1, 28)))


def test_floats_are_compared_exactly():
    """Rounding here would have hidden the FLOAT precision loss."""
    assert _normalize(1666807963.287016) != _normalize(1666807963.287017)


def test_non_datetime_strings_are_left_alone():
    assert _normalize("A/01.flac") == "A/01.flac"
    assert _normalize("Dvořák") == "Dvořák"
