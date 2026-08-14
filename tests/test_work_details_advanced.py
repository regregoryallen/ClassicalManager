"""The advanced metrics block in the Details window (v3.9).

It renders columns that are nullable everywhere — a track can be tagged
but unanalyzed, analyzed but unmeasured, or measured with individual
metrics missing — so every combination has to produce text rather than a
traceback inside a Tk callback, where the failure is a window that half
draws and no message anywhere.
"""

import json

import pytest

from music_manager.core.similarity import FEATURE_DIMS, TrackAnalysis
from music_manager.interfaces.gui.cleanup_tab import CleanupTabMixin

from tests.conftest import make_album


class _FakeText:
    """Captures what would have been inserted, with its tags."""

    def __init__(self):
        self.chunks = []

    def insert(self, _index, chunk, tag=None):
        self.chunks.append(chunk)

    def text(self):
        return "".join(self.chunks)


def _render(track, analysis):
    widget = _FakeText()

    def _add(label, value):
        widget.insert("end", f"{label}: {value}\n")

    CleanupTabMixin._add_advanced_track_details(widget, _add, track, analysis)
    return widget.text()


@pytest.fixture
def track(lib):
    make_album(lib, "A/Alb1", [("Work One", 1)])
    from music_manager.core.database import Track
    return Track.get(Track.relative_path == "A/Alb1/01.flac")


def test_unanalyzed_track_says_so(track):
    out = _render(track, None)
    assert "not analyzed" in out
    # The tag and file sections still render — they do not depend on it.
    assert "Genre" in out and "Track gain" in out


def test_missing_values_render_as_a_dash(track):
    out = _render(track, None)
    assert "Genre: —" in out
    assert "Performer: —" in out


def test_analyzed_but_unmeasured_track(track):
    analysis = TrackAnalysis.create(
        track=track, features=json.dumps([0.5] * FEATURE_DIMS),
        volatility=12.5, analyzed_at="2026-08-14 10:00:00",
        feature_version=1, loudness_version=None)
    out = _render(track, analysis)
    assert "quietness not measured" in out
    assert "Startle:" not in out
    # Every feature group is labelled, so 30 bare numbers are readable.
    assert "Timbre" in out and "Harmony" in out


def test_measured_track_shows_metrics_and_flags_diagnostics(track):
    analysis = TrackAnalysis.create(
        track=track, features=json.dumps([0.5] * FEATURE_DIMS),
        volatility=12.5, analyzed_at="2026-08-14 10:00:00",
        feature_version=1, loudness_version=1,
        startle_local=6.2, head_level=-3.0, tail_level=-1.5,
        integrated_lufs=-22.4, loud_at_ms=754_000,
        startle_delta=2.0, rise_rate=1.1, lra=9.0)
    out = _render(track, analysis)
    assert "Startle: 6.2 LU" in out
    assert "Loudest at: 12:34" in out
    assert "Integrated: -22.4 LUFS" in out
    # A4 §3.2: these must never read as a second opinion on Startle.
    assert "diagnostics" in out
    assert out.index("diagnostics") < out.index("Startle delta")


def test_corrupt_feature_json_does_not_raise(track):
    """A truncated features column must not take the whole window down."""
    analysis = TrackAnalysis.create(
        track=track, features="[0.1, 0.2,", volatility=None,
        analyzed_at="2026-08-14 10:00:00", feature_version=1)
    out = _render(track, analysis)
    assert "Feature version" in out
    assert "Timbre" not in out          # nothing to show, nothing claimed


def test_partial_quietness_row_renders_the_gaps(track):
    """loudness_version set but individual metrics null — the shape a
    measurement that hit a silent track leaves behind."""
    analysis = TrackAnalysis.create(
        track=track, features=json.dumps([0.0] * FEATURE_DIMS),
        volatility=None, analyzed_at="2026-08-14 10:00:00",
        feature_version=1, loudness_version=1)
    out = _render(track, analysis)
    assert "Startle: —" in out
    assert "Loudest at: —" in out
