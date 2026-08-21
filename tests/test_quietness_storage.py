"""v3.8: storage for the quietness metrics, and the migration that adds it.

The failure this file exists to prevent is not a crash. It is a column
that is added to the model, forgotten in one of the four places that
copy it, and comes back blank after a full rescan — reported hours later
as empty cells in Find Similar, with the feature vector intact so nothing
looks broken.
"""

import peewee as pw
import pytest

from music_manager.core.database import Track, database
from music_manager.core.quietness import playback_offset
from music_manager.core.similarity import (
    LOUDNESS_FIELDS,
    AnalysisSnapshot,
    TrackAnalysis,
    _loudness_columns,
    ensure_table,
)
from tests.conftest import make_album


# ---------------------------------------------------------------------------
# The four places that must agree
# ---------------------------------------------------------------------------

def test_both_tables_carry_every_loudness_field():
    """TrackAnalysis and AnalysisSnapshot must not drift apart.

    Miss the snapshot and the metrics are silently lost on the next full
    rescan while the feature vector survives.
    """
    for model in (TrackAnalysis, AnalysisSnapshot):
        missing = set(LOUDNESS_FIELDS) - set(model._meta.fields)
        assert not missing, f"{model.__name__} is missing {sorted(missing)}"


def test_the_migration_matches_the_models():
    """`_loudness_columns()` is what an existing database gets added.

    If it and LOUDNESS_FIELDS disagree, new installs and upgraded ones
    end up with different schemas — and only one of them gets tested.
    """
    assert set(_loudness_columns()) == set(LOUDNESS_FIELDS)


def test_every_loudness_column_is_nullable():
    """A non-null add_column makes peewee rebuild the table.

    `track_analysis` is CASCADE-linked to `Track`, so a rebuild takes the
    analyses with it. This has bitten before.
    """
    for name, field in _loudness_columns().items():
        assert field.null is True, f"{name} must be null=True"


def test_the_migration_returns_fresh_field_instances():
    """Peewee fields bind to the model that declares them.

    Handing the same instance to two tables corrupts both, so the
    factory must not memoise.
    """
    first, second = _loudness_columns(), _loudness_columns()
    for name in first:
        assert first[name] is not second[name]


# ---------------------------------------------------------------------------
# Round trip through a full rescan
# ---------------------------------------------------------------------------

def restorable_track(lib):
    """A track the restore path will actually accept.

    `_restore_analyses` re-links an analysis only when mtime *and* size
    match the snapshot — a changed file needs re-analysis. `make_album`
    leaves both null, which the restore correctly refuses, so a
    round-trip test has to give the track a file identity first.
    """
    make_album(lib, "A/Alb1", [("Work One", 1)])
    track = Track.select().where(Track.library == lib).first()
    track.file_mtime = 1_700_000_000.5
    track.file_size = 4_096
    track.save()
    return track


SAMPLE = {
    "startle_local": 12.5,
    "startle_delta": 4.25,
    "rise_rate": 18.0,
    "lra": 9.75,
    "head_level": -6.5,
    "tail_level": -22.0,
    "loud_at_ms": 91_500,
    "integrated_lufs": -17.25,
    "loudness_version": 1,
}


def test_metrics_survive_a_full_rescan(lib):
    """Snapshot and restore must carry every metric, not just the vector.

    Exercises `_snapshot_analyses` and `_restore_analyses` directly,
    which is where the hand-written column lists live.
    """
    from music_manager.core.scanner import _restore_analyses, _snapshot_analyses

    track = restorable_track(lib)
    TrackAnalysis.create(
        track=track, features="[0.0]", volatility=11.0,
        analyzed_at="2026-08-13 00:00:00", feature_version=1, **SAMPLE)

    assert _snapshot_analyses(lib) == 1

    # The rescan deletes the analysis (CASCADE in production; directly
    # here, which is the same starting state for the restore).
    TrackAnalysis.delete().execute()
    assert TrackAnalysis.select().count() == 0

    assert _restore_analyses(lib) == 1
    restored = TrackAnalysis.get(TrackAnalysis.track == track)
    for name, expected in SAMPLE.items():
        assert getattr(restored, name) == expected, f"{name} was lost"


def test_a_metric_of_zero_survives_the_round_trip(lib):
    """0.0 is data. It must not be confused with "not measured".

    `head_level` of exactly 0 means the track opens at its body level —
    a real and common measurement.
    """
    from music_manager.core.scanner import _restore_analyses, _snapshot_analyses

    track = restorable_track(lib)
    zeros = {name: 0 for name in LOUDNESS_FIELDS}
    TrackAnalysis.create(
        track=track, features="[0.0]", analyzed_at="2026-08-13 00:00:00",
        **zeros)

    _snapshot_analyses(lib)
    TrackAnalysis.delete().execute()
    _restore_analyses(lib)

    restored = TrackAnalysis.get(TrackAnalysis.track == track)
    for name in LOUDNESS_FIELDS:
        assert getattr(restored, name) == 0, f"{name} came back non-zero"


def test_unmeasured_metrics_stay_null_through_the_round_trip(lib):
    """An unmeasured track must not acquire values it never had."""
    from music_manager.core.scanner import _restore_analyses, _snapshot_analyses

    track = restorable_track(lib)
    TrackAnalysis.create(track=track, features="[0.0]",
                         analyzed_at="2026-08-13 00:00:00")

    _snapshot_analyses(lib)
    TrackAnalysis.delete().execute()
    _restore_analyses(lib)

    restored = TrackAnalysis.get(TrackAnalysis.track == track)
    for name in LOUDNESS_FIELDS:
        assert getattr(restored, name) is None


# ---------------------------------------------------------------------------
# Independent versioning
# ---------------------------------------------------------------------------

def test_the_two_versions_are_independent(lib):
    """Bumping feature_version must not invalidate loudness data.

    The entire reason the quietness metrics are a separate pass: the
    librosa analysis costs 219 MB + 93 MB per audio-minute per worker,
    and forcing it to rerun because an ffmpeg metric changed — or the
    reverse — is the coupling being avoided.
    """
    make_album(lib, "A/Alb1", [("Work One", 1)])
    track = Track.select().where(Track.library == lib).first()
    row = TrackAnalysis.create(
        track=track, features="[0.0]", analyzed_at="2026-08-13 00:00:00",
        feature_version=1, **SAMPLE)

    row.feature_version = 99
    row.save()

    reread = TrackAnalysis.get_by_id(row.id)
    assert reread.loudness_version == 1
    assert reread.startle_local == SAMPLE["startle_local"]

    reread.loudness_version = 42
    reread.save()
    assert TrackAnalysis.get_by_id(row.id).feature_version == 99


# ---------------------------------------------------------------------------
# The migration itself
# ---------------------------------------------------------------------------

@pytest.fixture()
def rebuilt_analysis_tables(db):
    """Put the analysis tables back after a test has replaced them.

    A test that stands in a hand-written v3.7-shaped table has to clean
    up after itself, and on MySQL that is not optional: the suite shares
    one schema for the whole session and `_ensure_schema` only rebuilds
    when `tracks` is missing, so a mangled `track_analysis` survives into
    every later test.

    The symptom is not a schema error either. A hand-written
    `id INTEGER NOT NULL PRIMARY KEY` has no AUTO_INCREMENT under MySQL,
    so every subsequent insert is assigned id 0 and the failure surfaces
    two files away as "Duplicate entry '0' for key 'PRIMARY'".
    """
    yield
    database.execute_sql("DROP TABLE IF EXISTS track_analysis")
    database.execute_sql("DROP TABLE IF EXISTS track_analysis_snapshot")
    ensure_table()


def test_ensure_table_adds_columns_to_an_existing_database(
        rebuilt_analysis_tables):
    """The upgrade path: a table created without the v3.8 columns.

    Runs on whichever backend the suite is pointed at — SQLite alone
    cannot catch a MySQL type-mapping fault.
    """
    database.execute_sql("DROP TABLE IF EXISTS track_analysis")
    database.execute_sql("DROP TABLE IF EXISTS track_analysis_snapshot")
    # A v3.7-shaped table: no quietness columns at all.
    database.execute_sql(
        "CREATE TABLE track_analysis ("
        " id INTEGER NOT NULL PRIMARY KEY, track_id INTEGER NOT NULL,"
        " features TEXT NOT NULL, volatility DOUBLE,"
        " analyzed_at TIMESTAMP NOT NULL, feature_version INTEGER NOT NULL)")

    before = {c.name for c in database.get_columns("track_analysis")}
    assert not (set(LOUDNESS_FIELDS) & before)

    ensure_table()

    after = {c.name for c in database.get_columns("track_analysis")}
    assert set(LOUDNESS_FIELDS) <= after
    # And the pre-existing columns are still there — a rebuild would be
    # the failure, not a fix.
    assert before <= after


def test_ensure_table_is_idempotent(db):
    """Called on every startup, so running twice must be free."""
    ensure_table()
    first = {c.name for c in database.get_columns("track_analysis")}
    ensure_table()
    assert {c.name for c in database.get_columns("track_analysis")} == first


def test_ensure_table_preserves_rows(lib):
    """The CASCADE hazard, asserted rather than trusted.

    If a migration rebuilt `track_analysis`, this row would vanish.
    """
    make_album(lib, "A/Alb1", [("Work One", 1)])
    track = Track.select().where(Track.library == lib).first()
    TrackAnalysis.create(track=track, features="[1.0]",
                         analyzed_at="2026-08-13 00:00:00", **SAMPLE)

    ensure_table()

    assert TrackAnalysis.select().count() == 1
    assert TrackAnalysis.get().startle_local == SAMPLE["startle_local"]


# ---------------------------------------------------------------------------
# ReplayGain on Track, and the derived offset
# ---------------------------------------------------------------------------

def test_replaygain_columns_round_trip_including_zero(lib):
    """0.0 is what every standalone work scores. It must not become NULL."""
    make_album(lib, "A/Alb1", [("Work One", 1)])
    track = Track.select().where(Track.library == lib).first()
    track.rg_track_gain = 0.0
    track.rg_album_gain = 0.0
    track.save()

    reread = Track.get_by_id(track.id)
    assert reread.rg_track_gain == 0.0
    assert reread.rg_album_gain == 0.0
    assert playback_offset(reread.rg_track_gain, reread.rg_album_gain) == 0.0


def test_the_offset_is_derived_not_stored():
    """Storing it would let the tags and their difference disagree."""
    assert "playback_offset" not in Track._meta.fields
    assert "rg_offset" not in Track._meta.fields
    assert playback_offset(-9.5, -6.25) == pytest.approx(3.25)


def test_an_untagged_track_has_no_offset_rather_than_zero():
    """The distinction the whole axis depends on.

    A standalone work scores a true 0.0 and plays at the reference
    level. An untagged file gets no gain from MA at all, so it plays at
    its own loudness and is not on this axis. Scoring it 0.0 would put
    the least-known tracks in the safest part of a sleep pool.
    """
    assert playback_offset(None, None) is None
    assert playback_offset(-5.0, None) is None
    assert playback_offset(None, -5.0) is None
    assert playback_offset(0.0, 0.0) == 0.0


def test_the_offset_is_reference_independent():
    """ALBUM - TRACK cancels the reference, so Opus's -23 LUFS is fine."""
    at_18 = playback_offset(-9.0, -4.0)
    at_23 = playback_offset(-9.0 - 5.0, -4.0 - 5.0)
    assert at_18 == at_23 == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Reading the tags out of real files
# ---------------------------------------------------------------------------
#
# `_extract_replaygain` is the one piece of v3.8 that touches every audio
# format, and the container differs in each. Asserted against real files
# rather than mocks: the failure mode is a format whose tags are read as
# absent, and a mock cannot reproduce that.

from tests.rg_audio import make_audio, needs_ffmpeg   # noqa: E402


def _tagged_flac(path, track_gain, album_gain):
    from mutagen.flac import FLAC
    make_audio(path, seconds=1.0)
    audio = FLAC(path)
    audio["REPLAYGAIN_TRACK_GAIN"] = track_gain
    audio["REPLAYGAIN_ALBUM_GAIN"] = album_gain
    audio.save()
    return path


@needs_ffmpeg
def test_scanner_reads_replaygain_from_flac(tmp_path):
    from music_manager.core.scanner import extract_tags

    path = _tagged_flac(tmp_path / "a.flac", "-9.50 dB", "-6.25 dB")
    tags = extract_tags(path)

    assert tags.rg_track_gain == pytest.approx(-9.50)
    assert tags.rg_album_gain == pytest.approx(-6.25)
    assert playback_offset(tags.rg_track_gain,
                           tags.rg_album_gain) == pytest.approx(3.25)


@needs_ffmpeg
def test_scanner_reads_replaygain_from_mp3_txxx(tmp_path):
    """ID3 keys these by TXXX description, in whatever case it likes."""
    from mutagen.id3 import ID3, TXXX

    from music_manager.core.scanner import extract_tags

    path = tmp_path / "a.mp3"
    make_audio(path, seconds=1.0)
    frames = ID3(path)
    frames.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN",
                    text="-11.00 dB"))
    frames.add(TXXX(encoding=3, desc="replaygain_album_gain",
                    text="-8.00 dB"))
    frames.save(path)

    tags = extract_tags(path)
    assert tags.rg_track_gain == pytest.approx(-11.0)
    assert tags.rg_album_gain == pytest.approx(-8.0)


@needs_ffmpeg
def test_an_untagged_file_reads_as_none_not_zero(tmp_path):
    """The distinction the axis depends on, at the scanner boundary."""
    from music_manager.core.scanner import extract_tags

    path = tmp_path / "plain.flac"
    make_audio(path, seconds=1.0)
    tags = extract_tags(path)

    assert tags.rg_track_gain is None
    assert tags.rg_album_gain is None


@needs_ffmpeg
def test_a_standalone_works_zero_gain_is_preserved(tmp_path):
    """Equal gains mean offset 0.0, and 0.0 must reach the database.

    68.8% of the library scores exactly this. An `or None` anywhere on
    the write path would turn all of it into "unmeasured".
    """
    from music_manager.core.scanner import extract_tags

    path = _tagged_flac(tmp_path / "solo.flac", "-7.25 dB", "-7.25 dB")
    tags = extract_tags(path)

    assert tags.rg_track_gain == pytest.approx(-7.25)
    assert playback_offset(tags.rg_track_gain, tags.rg_album_gain) == 0.0


@needs_ffmpeg
def test_a_garbled_gain_tag_costs_only_the_gain(tmp_path):
    """The rest of the file's metadata must still come through."""
    from music_manager.core.scanner import extract_tags

    path = _tagged_flac(tmp_path / "bad.flac", "not a number", "-6.00 dB")
    tags = extract_tags(path)

    assert tags.rg_track_gain is None
    assert tags.rg_album_gain == pytest.approx(-6.00)
    assert playback_offset(tags.rg_track_gain, tags.rg_album_gain) is None
    assert tags.duration_ms > 0          # the file was still parsed


@needs_ffmpeg
def test_replaygain_is_written_to_the_track_row(lib, tmp_path):
    """End to end: tags on disk reach Track, zero included."""
    from music_manager.core.scanner import extract_tags

    path = _tagged_flac(tmp_path / "b.flac", "-3.00 dB", "-3.00 dB")
    tags = extract_tags(path)

    make_album(lib, "A/Alb1", [("Work One", 1)])
    track = Track.select().where(Track.library == lib).first()
    track.rg_track_gain = tags.rg_track_gain
    track.rg_album_gain = tags.rg_album_gain
    track.save()

    reread = Track.get_by_id(track.id)
    assert reread.rg_track_gain == pytest.approx(-3.0)
    assert playback_offset(reread.rg_track_gain, reread.rg_album_gain) == 0.0


# ---------------------------------------------------------------------------
# The guard for the mistake that shipped
# ---------------------------------------------------------------------------

def test_schema_matches_models(db):
    """Every model field must exist as a column, on every model.

    v3.8 added `tracks.rg_track_gain` and its migration, but left
    SCHEMA_VERSION at 1. `_schema_is_current()` therefore returned True
    on an already-initialised database, `_create_and_migrate` never ran,
    and the application died on startup with

        Unknown column 't1.rg_track_gain' in 'SELECT'

    — from a SELECT three call layers away in the GUI, with nothing in
    the traceback pointing at the missing bump.

    Deliberately generic rather than a list of v3.8's columns: the defect
    is not specific to these columns, and a test naming them would have
    to be remembered in exactly the same way SCHEMA_VERSION was not.
    """
    from music_manager.core.database import (
        Album, Composer, Library, Override, PlaylistProfile,
        ProfileSelection, SourceFolder, Work,
    )

    models = [Library, SourceFolder, Composer, Album, Work, Track,
              PlaylistProfile, ProfileSelection, Override,
              TrackAnalysis, AnalysisSnapshot]

    problems = []
    for model in models:
        table = model._meta.table_name
        columns = {c.name for c in database.get_columns(table)}
        for field in model._meta.sorted_fields:
            if field.column_name not in columns:
                problems.append(f"{table}.{field.column_name}")
    assert not problems, (
        "model fields with no column: " + ", ".join(problems)
        + " — did SCHEMA_VERSION get bumped?")


def test_schema_version_is_recorded_after_migrating(tmp_path):
    """A migrated database records the new version, so the next start skips.

    The other half of the same mechanism: if the bump happened but the
    version were not recorded, every startup would redo the DDL — which
    is the metadata-lock contention v3.6 removed.
    """
    from music_manager.core.database import (
        SCHEMA_VERSION, _schema_is_current, initialize_database,
    )

    initialize_database(tmp_path / "fresh.db")
    try:
        assert _schema_is_current()
        row = database.execute_sql(
            "SELECT version FROM schema_state").fetchone()
        assert row[0] == SCHEMA_VERSION
    finally:
        if not database.is_closed():
            database.close()


# The fingerprint of every table's columns, as the models declare them,
# pinned to the SCHEMA_VERSION that describes them.
#
# test_schema_matches_models cannot catch a missing version bump on its
# own: the suite builds a fresh database per test, `create_tables` makes
# every column straight from the models, and the columns therefore always
# agree. The bug only exists for a database that already exists — which
# is every real one, and none of the test ones.
#
# So the shape is pinned instead. Add a column and this fails, and it
# keeps failing until SCHEMA_VERSION is bumped and the new fingerprint
# recorded. That is precisely the reminder that was missing.
#
# Column names only, not types: peewee's internal type names are not a
# stable thing to hash across library upgrades, and a type change needs a
# hand-written migration anyway, which is not something a fingerprint
# would help with.
MODEL_SHAPE = {
    2: "ef30476cec06b0b5",   # v3.8: rg gains on tracks, quietness columns
    3: "d24afe77dda8d3db",   # v3.11: libraries.works_dirty
}


def _model_shape_fingerprint():
    import hashlib

    from music_manager.core.database import (
        Album, Composer, Library, Override, PlaylistProfile,
        ProfileSelection, SourceFolder, Work,
    )

    models = [Library, SourceFolder, Composer, Album, Work, Track,
              PlaylistProfile, ProfileSelection, Override,
              TrackAnalysis, AnalysisSnapshot]
    parts = []
    for model in sorted(models, key=lambda m: m._meta.table_name):
        columns = sorted(f.column_name for f in model._meta.sorted_fields)
        parts.append(f"{model._meta.table_name}:{','.join(columns)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def test_schema_version_tracks_the_model_shape():
    """Changing the models without bumping SCHEMA_VERSION must fail here.

    An existing database records its version, `_schema_is_current()`
    short-circuits on a match, and `_create_and_migrate` never runs. The
    new column is then missing from a table whose model has it, and the
    application dies at the first SELECT — as v3.8 did, on startup,
    against the production MariaDB.
    """
    from music_manager.core.database import SCHEMA_VERSION

    fingerprint = _model_shape_fingerprint()
    assert SCHEMA_VERSION in MODEL_SHAPE, (
        f"SCHEMA_VERSION is {SCHEMA_VERSION} but MODEL_SHAPE only knows "
        f"{sorted(MODEL_SHAPE)}. If the models gained or lost a column, "
        f"record the new shape as {fingerprint!r}; if they did not, this "
        f"bump has no DDL behind it."
    )
    assert fingerprint == MODEL_SHAPE[SCHEMA_VERSION], (
        f"The models' columns changed but SCHEMA_VERSION is still "
        f"{SCHEMA_VERSION}. Existing databases will NOT get the new "
        f"column and will fail at the first query. Bump SCHEMA_VERSION, "
        f"add the migration to _create_and_migrate, and record "
        f"{fingerprint!r} in MODEL_SHAPE."
    )


# ---------------------------------------------------------------------------
# C4 — demand-driven measurement
# ---------------------------------------------------------------------------

def test_tracks_needing_quietness_keys_on_the_version_not_the_metric(lib):
    """A silent track measures fine and has no startle value.

    Keying the queue on `startle_local` being null would put it back in
    the queue on every pass, forever. `loudness_version` is the column
    whose job this is.
    """
    from music_manager.core.quietness import LOUDNESS_VERSION
    from music_manager.core.similarity import tracks_needing_quietness

    make_album(lib, "A/Alb1", [("Work One", 3)])
    tracks = list(Track.select().where(Track.library == lib))
    for track in tracks:
        TrackAnalysis.create(track=track, features="[0.0]",
                             analyzed_at="2026-08-13 00:00:00")
    ids = [t.id for t in tracks]

    assert tracks_needing_quietness(ids) == ids

    # Measured with a value.
    (TrackAnalysis.update(loudness_version=LOUDNESS_VERSION, startle_local=8.0)
     .where(TrackAnalysis.track == ids[0]).execute())
    # Measured, but silent: stamped, metrics still null.
    (TrackAnalysis.update(loudness_version=LOUDNESS_VERSION)
     .where(TrackAnalysis.track == ids[1]).execute())

    assert tracks_needing_quietness(ids) == [ids[2]]


def test_a_stale_loudness_version_is_re_queued(lib):
    from music_manager.core.quietness import LOUDNESS_VERSION
    from music_manager.core.similarity import tracks_needing_quietness

    make_album(lib, "A/Alb1", [("Work One", 1)])
    track = Track.select().where(Track.library == lib).first()
    TrackAnalysis.create(track=track, features="[0.0]",
                         analyzed_at="2026-08-13 00:00:00",
                         loudness_version=LOUDNESS_VERSION - 1,
                         startle_local=8.0)

    assert tracks_needing_quietness([track.id]) == [track.id]


@needs_ffmpeg
def test_measure_quietness_writes_every_metric(lib, tmp_path):
    """End to end: real audio in, populated columns out."""
    from music_manager.core.database import Album, SourceFolder, Work
    from music_manager.core.quietness import LOUDNESS_VERSION
    from music_manager.core.similarity import measure_quietness
    from tests.rg_audio import make_envelope

    folder = SourceFolder.create(library=lib, root_path=str(tmp_path))
    album = Album.create(library=lib, folder=folder, album_key="Q", title="Q")
    work = Work.create(album=album, work_name="W", work_sequence=1,
                       work_source="work_tag")
    make_envelope(tmp_path / "step.wav", [(40, -30, -30), (40, -10, -10)])
    track = Track.create(library=lib, folder=folder, album=album, work=work,
                         title="step", relative_path="step.wav",
                         disc_number=1, track_number=1, duration_ms=80_000)
    TrackAnalysis.create(track=track, features="[0.0]",
                         analyzed_at="2026-08-13 00:00:00")

    stats = measure_quietness([track.id])
    assert stats == {"measured": 1, "silent": 0, "failed": 0, "missing": 0}

    row = TrackAnalysis.get(TrackAnalysis.track == track)
    assert row.loudness_version == LOUDNESS_VERSION
    assert row.startle_local == pytest.approx(20.0, abs=3.0)
    assert row.loud_at_ms == pytest.approx(40_000, abs=5_000)
    assert row.integrated_lufs is not None
    assert row.head_level is not None
    assert row.tail_level is not None


@needs_ffmpeg
def test_a_silent_track_is_stamped_but_not_scored(lib, tmp_path):
    """Stamped so it is not re-queued; null so it is not called quiet."""
    from music_manager.core.database import Album, SourceFolder, Work
    from music_manager.core.quietness import LOUDNESS_VERSION
    from music_manager.core.similarity import (
        measure_quietness, tracks_needing_quietness,
    )

    folder = SourceFolder.create(library=lib, root_path=str(tmp_path))
    album = Album.create(library=lib, folder=folder, album_key="Q", title="Q")
    work = Work.create(album=album, work_name="W", work_sequence=1,
                       work_source="work_tag")
    make_audio(tmp_path / "silent.flac", seconds=20.0, silent=True)
    track = Track.create(library=lib, folder=folder, album=album, work=work,
                         title="silent", relative_path="silent.flac",
                         disc_number=1, track_number=1, duration_ms=20_000)
    TrackAnalysis.create(track=track, features="[0.0]",
                         analyzed_at="2026-08-13 00:00:00")

    stats = measure_quietness([track.id])
    assert stats["silent"] == 1
    assert stats["measured"] == 0

    row = TrackAnalysis.get(TrackAnalysis.track == track)
    assert row.loudness_version == LOUDNESS_VERSION
    assert row.startle_local is None
    # Stamped, so it does not come back round on the next pass.
    assert tracks_needing_quietness([track.id]) == []


@needs_ffmpeg
def test_a_missing_file_is_counted_not_raised(lib, tmp_path):
    from music_manager.core.database import Album, SourceFolder, Work
    from music_manager.core.similarity import measure_quietness

    folder = SourceFolder.create(library=lib, root_path=str(tmp_path))
    album = Album.create(library=lib, folder=folder, album_key="Q", title="Q")
    work = Work.create(album=album, work_name="W", work_sequence=1,
                       work_source="work_tag")
    track = Track.create(library=lib, folder=folder, album=album, work=work,
                         title="gone", relative_path="gone.wav",
                         disc_number=1, track_number=1, duration_ms=1000)
    TrackAnalysis.create(track=track, features="[0.0]",
                         analyzed_at="2026-08-13 00:00:00")

    stats = measure_quietness([track.id])
    assert stats["missing"] == 1
    # Not stamped: the file may come back, and it has not been measured.
    assert TrackAnalysis.get(
        TrackAnalysis.track == track).loudness_version is None


def test_measuring_nothing_is_not_an_error():
    from music_manager.core.similarity import measure_quietness
    assert measure_quietness([]) == {
        "measured": 0, "silent": 0, "failed": 0, "missing": 0}


def test_measuring_does_not_leak_a_connection_from_a_worker_thread(lib, tmp_path):
    """peewee keeps one connection per thread; nothing was closing it.

    Measure runs on the GUI's worker thread, so each run opened a fresh
    MariaDB connection and left it open. Slow, but real: a long curation
    session would walk toward the server's connection limit.

    The close is conditional on this thread having had no connection on
    entry — called from the main thread the connection belongs to
    somebody else, and closing it would break the caller.
    """
    import threading

    from music_manager.core.database import database
    from music_manager.core.similarity import measure_quietness

    # Main thread: the caller's connection must survive.
    assert not database.is_closed()
    measure_quietness([])
    assert not database.is_closed(), "closed a connection it did not open"

    seen = {}

    def worker():
        from music_manager.core.database import Track as T
        T.select().count()                  # opens this thread's connection
        seen["open_during"] = not database.is_closed()
        measure_quietness([])
        seen["open_after"] = not database.is_closed()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert seen["open_during"] is True
    # measure_quietness did not open this one, so it leaves it alone.
    assert seen["open_after"] is True
