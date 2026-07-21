"""v3.1: merged scan-mode gating and audio-analysis gap reporting."""

import json
from datetime import datetime, timezone

from music_manager.core.database import Track
from music_manager.core.scanner import can_scan_incremental
from music_manager.core.similarity import FEATURE_VERSION, TrackAnalysis
from music_manager.interfaces.gui.similarity_ui import SimilarityUIMixin

from tests.conftest import make_album


# ---------------------------------------------------------------------------
# Scan mode availability (drives the dialog's Quick option)
# ---------------------------------------------------------------------------

def test_quick_scan_unavailable_for_empty_library(lib):
    assert can_scan_incremental(lib) is False


def test_quick_scan_unavailable_without_mtime_data(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])  # no file_mtime set
    assert can_scan_incremental(lib) is False


def test_quick_scan_available_once_mtime_recorded(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    t = Track.select().where(Track.album == album).first()
    t.file_mtime = 1000.0
    t.file_size = 4096
    t.save()
    assert can_scan_incremental(lib) is True


def test_quick_scan_availability_is_per_library(lib, db):
    from music_manager.core.database import Library, SourceFolder
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    t = Track.select().where(Track.album == album).first()
    t.file_mtime = 1.0
    t.save()

    other = Library.create(name="Other")
    other.test_folder = SourceFolder.create(library=other, root_path="/o")
    make_album(other, "B/Alb1", [("Work", 1)])

    assert can_scan_incremental(lib) is True
    assert can_scan_incremental(other) is False


# ---------------------------------------------------------------------------
# Analysis gap + estimate (drives Analyze Audio and Find Similar prompts)
# ---------------------------------------------------------------------------

class _App(SimilarityUIMixin):
    def __init__(self, library):
        self.active_library = library


def _analyze(track, version=FEATURE_VERSION):
    TrackAnalysis.create(
        track=track, features=json.dumps([0.1] * 31), volatility=0.1,
        analyzed_at=datetime.now(timezone.utc), feature_version=version)


def test_analysis_gap_counts(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    app = _App(lib)
    assert app._analysis_gap() == (3, 3)

    tracks = list(Track.select().where(Track.album == album))
    _analyze(tracks[0])
    assert app._analysis_gap() == (2, 3)

    for t in tracks[1:]:
        _analyze(t)
    assert app._analysis_gap() == (0, 3)


def test_stale_feature_version_counts_as_unanalyzed(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    for t in Track.select().where(Track.album == album):
        _analyze(t, version=FEATURE_VERSION - 1)

    assert _App(lib)._analysis_gap() == (2, 2)


def test_empty_library_gap(lib):
    assert _App(lib)._analysis_gap() == (0, 0)


def test_analysis_estimate_scales():
    est = SimilarityUIMixin._analysis_estimate
    assert "under a minute" in est(10)
    assert "minutes" in est(300)
    assert "hours" in est(5000)
