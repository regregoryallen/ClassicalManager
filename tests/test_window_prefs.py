"""Remembered window geometry and tree column widths (v3.9).

Both are read back from a JSON file written by an earlier run, so the
input is whatever the last session left there — including a geometry
naming a monitor that has since been unplugged. Restoring a window onto
coordinates that no longer exist makes it invisible with nothing on
screen to explain why, so a saved geometry is validated before it is
trusted and the window is re-centred when it fails.
"""

import pytest

from music_manager.interfaces.gui.app import App


class _FakeRoot:
    """Screen dimensions and nothing else — that is all the check reads."""

    def __init__(self, width=1920, height=1080):
        self._w, self._h = width, height

    def winfo_screenwidth(self):
        return self._w

    def winfo_screenheight(self):
        return self._h


class _FakeWindow:
    def __init__(self):
        self.applied = None

    def geometry(self, spec):
        self.applied = spec


class _FakeApp:
    """Just the geometry helpers, unbound from the rest of App."""

    _GEOMETRY_RE = App._GEOMETRY_RE
    _apply_saved_geometry = App._apply_saved_geometry

    def __init__(self, screen=(1920, 1080)):
        self.root = _FakeRoot(*screen)


@pytest.mark.parametrize("saved", [
    "900x560+120+80",
    "1400x900+0+0",
    "780x420-10-20",        # offsets from the right/bottom edge
])
def test_usable_geometry_is_applied_verbatim(saved):
    app, win = _FakeApp(), _FakeWindow()
    assert app._apply_saved_geometry(win, saved) is True
    assert win.applied == saved


@pytest.mark.parametrize("saved", [
    None,                   # nothing saved yet
    "",
    "not a geometry",
    "900x560",              # size but no position
    "900560+10+10",
    "100x80+10+10",         # too small to hold anything
    "99999x560+10+10",      # implausible width
])
def test_unusable_geometry_is_refused(saved):
    app, win = _FakeApp(), _FakeWindow()
    assert app._apply_saved_geometry(win, saved) is False
    assert win.applied is None


def test_geometry_from_a_monitor_that_is_gone_is_refused():
    """The case that strands a window: saved on a second screen, opened
    without it. Falling back to centring is the only visible outcome."""
    app, win = _FakeApp(screen=(1920, 1080)), _FakeWindow()
    assert app._apply_saved_geometry(win, "900x560+3400+200") is False
    assert app._apply_saved_geometry(win, "900x560+200+2400") is False
    assert win.applied is None


def test_window_partly_off_the_left_edge_is_kept():
    """Dragging a window half off the edge is a choice, not a fault."""
    app, win = _FakeApp(), _FakeWindow()
    assert app._apply_saved_geometry(win, "900x560+-300+100") is True
    assert win.applied == "900x560+-300+100"


def test_tcl_failure_falls_back_rather_than_propagating():
    """A window torn down mid-restore must not take the caller with it."""
    import tkinter as tk

    class _Doomed(_FakeWindow):
        def geometry(self, spec):
            raise tk.TclError("bad window path name")

    app = _FakeApp()
    assert app._apply_saved_geometry(_Doomed(), "900x560+10+10") is False
