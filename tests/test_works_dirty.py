"""Pending-regroup tracking (v3.11).

Setting a work_name override changes which tracks form a work, but
nothing regroups until Regroup Works is run. Between the two, the Works
browser and the saved playlists disagree with nothing on screen saying
so. Library.works_dirty is what closes that gap, so these pin where it
is raised and where it is cleared.

Raised in core rather than in the GUI so the CLI and an overrides import
raise it too; cleared in redetect_works so `--cli redetect` clears it.
"""

import json

from music_manager.core.database import Library, SourceFolder, Track
from music_manager.core.overrides import (
    import_overrides, set_override,
)
from music_manager.core.scanner import redetect_works

from tests.conftest import make_album


def _dirty(lib):
    """Re-read the flag from the database, not from a stale instance."""
    return bool(Library.get_by_id(lib.id).works_dirty)


def _first_track(lib):
    return Track.select().where(Track.library == lib).first()


def _second_library():
    """A second library carrying the source folder make_album needs."""
    library = Library.create(name="Other")
    library.test_folder = SourceFolder.create(
        library=library, root_path="/music2")
    return library


# ---------------------------------------------------------------------------
# What raises the flag
# ---------------------------------------------------------------------------

def test_a_new_library_is_not_dirty(lib):
    assert not _dirty(lib)


def test_a_work_name_override_marks_the_library_dirty(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)

    set_override(library=lib, scope="track", field="work_name",
                 value="Renamed Work",
                 match_relative_path=track.relative_path)

    assert _dirty(lib)


def test_marking_standalone_marks_the_library_dirty(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)

    set_override(library=lib, scope="track", field="work_name",
                 value="__standalone__",
                 match_relative_path=track.relative_path)

    assert _dirty(lib)


def test_updating_an_existing_override_marks_it_dirty_again(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)
    set_override(library=lib, scope="track", field="work_name", value="One",
                 match_relative_path=track.relative_path)
    redetect_works(lib)
    assert not _dirty(lib)

    set_override(library=lib, scope="track", field="work_name", value="Two",
                 match_relative_path=track.relative_path)

    assert _dirty(lib)


def test_an_imported_work_name_override_marks_it_dirty(lib, tmp_path):
    """Import writes Override rows directly, bypassing set_override."""
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)
    payload = tmp_path / "ov.json"
    payload.write_text(json.dumps({"overrides": [{
        "scope": "track", "field": "work_name", "value": "Imported Name",
        "match_relative_path": track.relative_path,
    }]}), encoding="utf-8")

    import_overrides(lib, payload)

    assert _dirty(lib)


# ---------------------------------------------------------------------------
# What does not
# ---------------------------------------------------------------------------

def test_a_composer_override_does_not_mark_it_dirty(lib):
    """Composer plays no part in work detection.

    detect_works consults the work_name override, the MB work id, the
    WORK tag and the title heuristic. Flagging a composer edit would ask
    for a regroup that changes nothing.
    """
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)

    set_override(library=lib, scope="track", field="composer",
                 value="Different Composer",
                 match_relative_path=track.relative_path)

    assert not _dirty(lib)


def test_an_imported_composer_override_does_not_mark_it_dirty(lib, tmp_path):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)
    payload = tmp_path / "ov.json"
    payload.write_text(json.dumps({"overrides": [{
        "scope": "track", "field": "composer", "value": "Someone",
        "match_relative_path": track.relative_path,
    }]}), encoding="utf-8")

    import_overrides(lib, payload)

    assert not _dirty(lib)


# ---------------------------------------------------------------------------
# What clears it
# ---------------------------------------------------------------------------

def test_regrouping_clears_the_flag(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)
    set_override(library=lib, scope="track", field="work_name", value="X",
                 match_relative_path=track.relative_path)
    assert _dirty(lib)

    redetect_works(lib)

    assert not _dirty(lib)


def test_the_flag_is_per_library(lib):
    other = _second_library()
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = _first_track(lib)

    set_override(library=lib, scope="track", field="work_name", value="X",
                 match_relative_path=track.relative_path)

    assert _dirty(lib)
    assert not _dirty(other)


def test_regrouping_one_library_does_not_clear_another(lib):
    other = _second_library()
    make_album(lib, "A/Alb1", [("Work One", 2)])
    make_album(other, "B/Alb1", [("Work Two", 2)])
    for library in (lib, other):
        track = Track.select().where(Track.library == library).first()
        set_override(library=library, scope="track", field="work_name",
                     value="X", match_relative_path=track.relative_path)

    redetect_works(lib)

    assert not _dirty(lib)
    assert _dirty(other)


# ---------------------------------------------------------------------------
# The prompt on the way out of the Cleanup tab
#
# Driven with stubs — no Tk. What matters is when the prompt appears and
# what accepting it does, not how the dialog looks.
# ---------------------------------------------------------------------------

class _Tabview:
    def __init__(self, current):
        self.current = current
        self.set_calls = []

    def get(self):
        return self.current

    def set(self, name):
        self.set_calls.append(name)
        self.current = name


def _tab_change(current_tab, pending, answer):
    from unittest import mock

    from music_manager.interfaces.gui.app import App

    app = App.__new__(App)          # the mixin method, without a window
    app.tabview = _Tabview(current_tab)
    app._works_regroup_pending = lambda: pending
    regrouped = []
    app._redetect_works = lambda: regrouped.append(True)

    with mock.patch("music_manager.interfaces.gui.app.messagebox.askyesno",
                    return_value=answer) as ask:
        app._on_tab_changed()
    return ask.called, bool(regrouped), app.tabview.set_calls


CLEANUP = "Cleanup / Overlay"
BUILDER = "Playlist Builder"


def test_no_prompt_while_still_on_the_cleanup_tab():
    prompted, _, _ = _tab_change(CLEANUP, pending=True, answer=False)
    assert not prompted


def test_no_prompt_when_nothing_is_pending():
    prompted, _, _ = _tab_change(BUILDER, pending=False, answer=False)
    assert not prompted


def test_declining_the_prompt_leaves_the_flag_alone():
    """Offered, not forced. The notice is still there next time."""
    prompted, regrouped, set_calls = _tab_change(BUILDER, pending=True,
                                                 answer=False)
    assert prompted
    assert not regrouped
    assert set_calls == []


def test_accepting_the_prompt_returns_to_the_tab_and_regroups():
    """Back to Cleanup first, so the result and the cleared notice show."""
    prompted, regrouped, set_calls = _tab_change(BUILDER, pending=True,
                                                 answer=True)
    assert prompted
    assert regrouped
    assert set_calls == [CLEANUP]
