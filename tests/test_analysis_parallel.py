"""Parallel similarity analysis.

Analysis is CPU-bound — unlike scanning, which is I/O-latency bound and was
measured as not worth parallelising. One reader already saturates the share
(~100 MB/s against ~114 for sixteen), so extra workers buy CPU, not I/O.

These tests use a stubbed analyze_file: the point is the batching, progress,
cancellation and write path, not librosa. Real timings live in V3-PLAN.md.
"""

import json

import pytest

from music_manager.core.database import Track
from music_manager.core import similarity as sim
from music_manager.core.similarity import (
    AnalysisCancelled, TrackAnalysis, analyze_library, default_worker_count,
    ensure_table,
)

from tests.conftest import make_album


@pytest.fixture()
def analysable(lib):
    ensure_table()
    make_album(lib, "A/Alb", [("W1", 3), ("W2", 2)])
    return lib


def _fake_analysis(path):
    """Deterministic stand-in keyed on the path, so results are checkable."""
    seed = float(len(path))
    return [seed + i for i in range(31)], seed / 100.0


def test_every_track_is_analysed_and_written(analysable, monkeypatch):
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)
    stats = analyze_library(analysable, workers=1)

    assert stats["analyzed"] == 5
    assert stats["failed"] == 0
    assert TrackAnalysis.select().count() == 5
    for analysis in TrackAnalysis.select():
        assert len(json.loads(analysis.features)) == 31
        assert analysis.feature_version == sim.FEATURE_VERSION


def test_results_are_written_against_the_right_track(analysable, monkeypatch):
    """A worker returns a track id, not an object — a mix-up would attach a
    vector to the wrong track and be invisible."""
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)
    analyze_library(analysable, workers=1)

    for analysis in TrackAnalysis.select(TrackAnalysis, Track).join(Track):
        expected, _ = _fake_analysis(sim._track_file_path(analysis.track))
        assert json.loads(analysis.features) == expected


def test_already_analysed_tracks_are_skipped(analysable, monkeypatch):
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)
    analyze_library(analysable, workers=1)
    stats = analyze_library(analysable, workers=1)

    assert stats["analyzed"] == 0
    assert stats["skipped"] == 5
    assert TrackAnalysis.select().count() == 5


def test_reanalysis_replaces_rather_than_duplicates(analysable, monkeypatch):
    """track has a UNIQUE constraint; the write path deletes then inserts."""
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)
    analyze_library(analysable, workers=1)
    TrackAnalysis.update(feature_version=0).execute()   # force staleness

    stats = analyze_library(analysable, workers=1)
    assert stats["analyzed"] == 5
    assert TrackAnalysis.select().count() == 5


def test_a_failing_file_is_counted_not_fatal(analysable, monkeypatch):
    def sometimes_fails(path):
        if path.endswith("02.flac"):
            raise RuntimeError("unreadable")
        return _fake_analysis(path)

    monkeypatch.setattr(sim, "analyze_file", sometimes_fails)
    stats = analyze_library(analysable, workers=1)

    assert stats["failed"] == 1
    assert stats["analyzed"] == 4
    assert TrackAnalysis.select().count() == 4


def test_progress_reports_each_track(analysable, monkeypatch):
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)
    seen = []
    analyze_library(analysable, workers=1,
                    progress_callback=lambda c, t, m: seen.append((c, t)))

    assert [c for c, _ in seen] == [1, 2, 3, 4, 5]
    assert {t for _, t in seen} == {5}


def test_cancellation_keeps_completed_work(analysable, monkeypatch):
    """Cancelling must not throw away what has already been analysed."""
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)

    def cancel_after_two(current, total, message):
        if current >= 2:
            raise AnalysisCancelled()

    stats = analyze_library(analysable, workers=1,
                            progress_callback=cancel_after_two)
    assert stats["analyzed"] == 2
    assert TrackAnalysis.select().count() == 2


def test_worker_count_is_bounded_by_the_work(analysable, monkeypatch):
    monkeypatch.setattr(sim, "analyze_file", _fake_analysis)
    stats = analyze_library(analysable, workers=999)
    assert stats["workers"] == 5          # five tracks, five workers at most


def test_default_worker_count_leaves_headroom():
    import os
    cores = os.cpu_count() or 2
    assert 1 <= default_worker_count() <= cores
    if cores >= 4:
        assert default_worker_count() < cores


def test_nothing_to_do_is_not_an_error(lib):
    ensure_table()
    stats = analyze_library(lib)
    assert stats == {"analyzed": 0, "skipped": 0, "failed": 0,
                     "total": 0, "workers": 1}
