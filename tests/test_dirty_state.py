"""v3.1: baseline-diff dirty tracking for the playlist builder.

The builder's dirty state must be exact (no false positives from
toggle-on/toggle-off) and must treat a crash-restored autosave as dirty.
These tests drive the mixin's logic with widget stubs — no Tk needed.
"""

from music_manager.core.selection import load_library_index
from music_manager.interfaces.gui.builder_tab import BuilderTabMixin

from tests.conftest import make_album, work_key


class _Entry:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def delete(self, *_a):
        self._value = ""

    def insert(self, _idx, value):
        self._value = value


class _Combo(_Entry):
    def set(self, value):
        self._value = value


class _Check:
    def __init__(self, value=0):
        self._value = value

    def get(self):
        return self._value

    def select(self):
        self._value = 1

    def deselect(self):
        self._value = 0


class _App(BuilderTabMixin):
    """Builder state without Tk: enough for snapshot/dirty logic."""

    def __init__(self, index=None):
        self.active_library = object() if index else None
        self._lib_index = index
        self._current_selections = []
        self._builder_baseline = None
        self.profile_name_entry = _Entry()
        self.shuffle_mode = _Combo("work")
        self.work_integrity = _Combo("enforce")
        self.length_mode = _Combo("all")
        self.length_value = _Entry()
        self.seed_entry = _Entry()
        self.no_repeat_var = _Check(1)
        self.sep_composer_var = _Check()
        self.sep_album_var = _Check()
        self.sep_form_var = _Check()

    def add(self, level, key, excluded=False, pin_position=None):
        self._current_selections.append(
            {"level": level, "key": key, "excluded": excluded,
             "pin_position": pin_position, "track_paths": None,
             "display": ""})

    def remove(self, level, key):
        self._current_selections = [
            s for s in self._current_selections
            if not (s["level"] == level and s["key"] == key)]


def test_no_baseline_means_not_dirty():
    app = _App()
    assert app._is_builder_dirty() is False


def test_selection_change_makes_dirty():
    app = _App()
    app._mark_builder_clean()
    assert not app._is_builder_dirty()

    app.add("album", "A/Alb1")
    assert app._is_builder_dirty()

    app._mark_builder_clean()
    assert not app._is_builder_dirty()


def test_toggle_on_then_off_is_not_dirty():
    """The reason for baseline-diff over a mutation flag."""
    app = _App()
    app.add("album", "A/Alb1")
    app._mark_builder_clean()

    app.add("track", "A/Alb1/01.flac")
    assert app._is_builder_dirty()
    app.remove("track", "A/Alb1/01.flac")
    assert not app._is_builder_dirty()


def test_rule_order_does_not_affect_dirtiness():
    app = _App()
    app.add("album", "A/Alb1")
    app.add("album", "A/Alb2")
    app._mark_builder_clean()

    app._current_selections.reverse()
    assert not app._is_builder_dirty()


def test_settings_changes_make_dirty():
    for attr, new in (("shuffle_mode", "track"),
                      ("work_integrity", "respect_selection"),
                      ("length_mode", "count")):
        app = _App()
        app._mark_builder_clean()
        getattr(app, attr).set(new)
        assert app._is_builder_dirty(), attr

    app = _App()
    app._mark_builder_clean()
    app.seed_entry.insert(0, "42")
    assert app._is_builder_dirty()

    app = _App()
    app._mark_builder_clean()
    app.sep_composer_var.select()
    assert app._is_builder_dirty()

    app = _App()
    app._mark_builder_clean()
    app.profile_name_entry.insert(0, "Renamed")
    assert app._is_builder_dirty()


def test_pin_change_makes_dirty(lib):
    index = load_library_index(lib)
    app = _App(index)
    wk = work_key("A/Alb1", "Work One", 1)
    app.add("work", wk)
    app._mark_builder_clean()

    app._current_selections[0]["pin_position"] = 2
    assert app._is_builder_dirty()


def test_exclusion_flip_makes_dirty():
    app = _App()
    app.add("track", "A/Alb1/01.flac", excluded=False)
    app._mark_builder_clean()

    app._current_selections[0]["excluded"] = True
    assert app._is_builder_dirty()


def test_breadcrumbs_alone_do_not_make_dirty():
    """Backfill fills track_paths on load; that is not a user edit."""
    app = _App()
    app.add("work", "k")
    app._mark_builder_clean()

    app._current_selections[0]["track_paths"] = '["a.flac"]'
    assert not app._is_builder_dirty()
