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


# ---------------------------------------------------------------------------
# Worker count: config, and honest estimates
# ---------------------------------------------------------------------------

def test_config_overrides_the_default_worker_count(tmp_path, monkeypatch):
    import json
    import music_manager.core.config as cfg
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_library": 1, "targets": {},
                                "analysis_workers": 3}))
    monkeypatch.setattr(cfg, "_config_path_override", path)
    assert default_worker_count() == 3


def test_config_worker_count_is_capped_at_the_core_count(tmp_path, monkeypatch):
    import json, os
    import music_manager.core.config as cfg
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_library": 1, "targets": {},
                                "analysis_workers": 9999}))
    monkeypatch.setattr(cfg, "_config_path_override", path)
    assert default_worker_count() == (os.cpu_count() or 2)


def test_a_bad_worker_count_is_rejected_by_validation(tmp_path):
    import json
    from music_manager.core.config import ConfigError, load_config, set_config_path
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_library": 1, "targets": {},
                                "analysis_workers": 0}))
    set_config_path(path)
    try:
        with pytest.raises(ConfigError, match="analysis_workers"):
            load_config()
    finally:
        import music_manager.core.config as cfg
        cfg._config_path_override = None


def test_estimates_never_promise_linear_speedup():
    """The GUI shows this before a multi-hour job; it must not flatter."""
    from music_manager.core.similarity import expected_speedup
    assert expected_speedup(1) == 1.0
    assert expected_speedup(8) < 8          # measured 6.4
    assert expected_speedup(24) < 24        # measured 9.5
    # Monotonic, so more workers never reads as slower.
    values = [expected_speedup(w) for w in range(1, 33)]
    assert values == sorted(values)


def test_estimate_shrinks_as_workers_rise():
    from music_manager.interfaces.gui.similarity_ui import SimilarityUIMixin
    one = SimilarityUIMixin._analysis_estimate(7279, workers=1)
    many = SimilarityUIMixin._analysis_estimate(7279, workers=12)
    assert "21" in one and "hours" in one
    assert "2.8 hours" in many


def test_every_modal_grabs_only_after_the_window_is_visible():
    """A regression guard for an empty Analyze Audio dialog.

    tk raises TclError when grab_set() is called on a window that is not yet
    mapped. The exception aborted the dialog builder before it created any
    widget or applied its geometry, so the symptom was a small blank window
    rather than an error. Cheap to check statically, invisible otherwise —
    there is no display in CI to catch it at runtime.
    """
    import pathlib

    offenders = []
    root = pathlib.Path(__file__).resolve().parent.parent / "music_manager"
    for path in (root / "interfaces").rglob("*.py"):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if ".grab_set()" not in line:
                continue
            window = line.strip().split(".grab_set")[0]
            preceding = "\n".join(lines[max(0, i - 12):i])
            if f"{window}.wait_visibility()" not in preceding:
                offenders.append(f"{path.name}:{i + 1}")
    assert offenders == [], (
        "grab_set() without a preceding wait_visibility(): " + ", ".join(offenders))
