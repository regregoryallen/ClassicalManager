"""v3.2: save dialogs must pre-populate the suggested filename.

The M3U/JSON export dialogs passed a bare filename ("Morning Mix.m3u")
when no export directory had been saved yet. GTK (zenity) and kdialog
need an ABSOLUTE path — given a relative one they silently ignore it,
leaving the Name field empty and opening in the process CWD (/tmp).
"""

import os
import sys

import pytest

from music_manager.interfaces.filedialog import _save_start_path

# _save_start_path builds an absolute path for zenity/kdialog, which only run
# on Linux (Windows/macOS use tkinter's native dialog and never call it). The
# assertions here are POSIX by nature; scope the module to Linux.
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="_save_start_path serves zenity/kdialog, which are Linux-only")


def test_dir_and_file_join_absolute():
    assert _save_start_path("/home/u/Playlists", "Sunday.m3u") == \
        "/home/u/Playlists/Sunday.m3u"


def test_file_without_dir_falls_back_to_home():
    """The reported bug: no saved export dir yet."""
    result = _save_start_path(None, "Morning Mix.m3u")
    assert os.path.isabs(result), "must be absolute or GTK ignores it"
    assert result.endswith("/Morning Mix.m3u")
    assert result.startswith(os.path.expanduser("~"))


def test_empty_string_dir_is_treated_as_missing():
    """prefs default to '' rather than None."""
    result = _save_start_path("", "Sunday.m3u")
    assert os.path.isabs(result)
    assert result.endswith("/Sunday.m3u")


def test_dir_only_returns_trailing_slash_dir():
    result = _save_start_path("/home/u/Playlists", "")
    assert result == "/home/u/Playlists/"


def test_nothing_supplied_returns_home_dir():
    result = _save_start_path(None, "")
    assert result.rstrip("/") == os.path.expanduser("~").rstrip("/")
    assert result.endswith("/")


def test_relative_dir_is_made_absolute():
    result = _save_start_path("Playlists", "Sunday.m3u")
    assert os.path.isabs(result)
    assert result.endswith("Playlists/Sunday.m3u")


def test_spaces_and_unicode_preserved():
    result = _save_start_path("/tmp/My Music", "Sünday Größe.m3u")
    assert result == "/tmp/My Music/Sünday Größe.m3u"


# ---------------------------------------------------------------------------
# Backend routing: zenity 4 cannot pre-fill a save dialog's name
# ---------------------------------------------------------------------------

def _patch_backends(monkeypatch, zenity=True, kdialog=False):
    from music_manager.interfaces import filedialog as fd
    monkeypatch.setattr(fd, "_ZENITY", "/usr/bin/zenity" if zenity else None)
    monkeypatch.setattr(fd, "_KDIALOG", "/usr/bin/kdialog" if kdialog else None)
    calls = {"zenity": [], "tk": []}
    monkeypatch.setattr(fd, "_run",
                        lambda cmd, parent=None: calls["zenity"].append(cmd) or "")
    monkeypatch.setattr(fd.filedialog, "asksaveasfilename",
                        lambda **kw: calls["tk"].append(kw) or "")
    return fd, calls


def test_suggested_name_bypasses_zenity(monkeypatch):
    """zenity 4 silently drops the suggested name, so tk handles these."""
    fd, calls = _patch_backends(monkeypatch)
    fd.asksaveasfilename(title="Export M3U", initialfile="Morning Mix.m3u",
                         initialdir="/home/u/Playlists",
                         defaultextension=".m3u")
    assert not calls["zenity"], "must not use zenity when a name is suggested"
    assert calls["tk"], "tk dialog should handle it"
    assert calls["tk"][0]["initialfile"] == "Morning Mix.m3u"


def test_no_suggested_name_still_uses_native_zenity(monkeypatch):
    fd, calls = _patch_backends(monkeypatch)
    fd.asksaveasfilename(title="Save", initialdir="/home/u")
    assert calls["zenity"], "no name to lose — keep the native dialog"
    assert not calls["tk"]
    cmd = calls["zenity"][0]
    assert "--filename" in cmd
    assert os.path.isabs(cmd[cmd.index("--filename") + 1])


def test_kdialog_keeps_save_dialogs(monkeypatch):
    """KDE's dialog pre-fills correctly; only zenity is affected."""
    fd, calls = _patch_backends(monkeypatch, zenity=False, kdialog=True)
    fd.asksaveasfilename(title="Export", initialfile="Sunday.m3u",
                         initialdir="/home/u")
    assert calls["zenity"], "kdialog path runs through _run too"
    assert not calls["tk"]
    assert "/home/u/Sunday.m3u" in calls["zenity"][0]


# ---------------------------------------------------------------------------
# v3.6.2: confirmoverwrite=False means the file is being *chosen*
#
# Opening a second database pointed the Settings browse button at an
# existing .db and got "A file named music_manager.db already exists. Do
# you want to replace it?" — GTK4 dropped the property that turns that
# prompt off, so zenity 4 always asks and no argument suppresses it. The
# flag was being passed and silently ignored on Linux.
# ---------------------------------------------------------------------------

def test_choosing_an_existing_file_bypasses_zenity(monkeypatch):
    fd, calls = _patch_backends(monkeypatch)
    fd.asksaveasfilename(title="Select Database File", confirmoverwrite=False)
    assert not calls["zenity"], "zenity would prompt before replacing"
    assert calls["tk"], "tk honours confirmoverwrite"
    assert calls["tk"][0]["confirmoverwrite"] is False


def test_choosing_an_existing_file_bypasses_kdialog(monkeypatch):
    fd, calls = _patch_backends(monkeypatch, zenity=False, kdialog=True)
    fd.asksaveasfilename(title="Select Database File", confirmoverwrite=False)
    assert not calls["zenity"], "kdialog prompts too"
    assert calls["tk"][0]["confirmoverwrite"] is False


def test_a_real_save_still_confirms(monkeypatch):
    """Overwriting a playlist on export must keep asking."""
    fd, calls = _patch_backends(monkeypatch)
    fd.asksaveasfilename(title="Export M3U", initialfile="Sunday.m3u",
                         initialdir="/home/u")
    assert calls["tk"][0]["confirmoverwrite"] is True


def test_a_real_save_without_a_name_keeps_zenity(monkeypatch):
    """The confirmoverwrite branch must not steal the native dialog."""
    fd, calls = _patch_backends(monkeypatch)
    fd.asksaveasfilename(title="Save", initialdir="/home/u")
    assert calls["zenity"] and not calls["tk"]


# ---------------------------------------------------------------------------
# v3.6.1: an external dialog must not run under a Tk input grab.
#
# zenity and kdialog are separate applications. A modal Tk dialog that
# holds a grab stops every other window on the display receiving input,
# so the file chooser appears and cannot be clicked — and because Tk keeps
# the grab while it waits for the chooser to exit, the whole desktop is
# frozen until the app is killed from another machine.
# ---------------------------------------------------------------------------

class _FakeWidget:
    """Enough of a Tk widget to record grab handling."""

    def __init__(self, holder="self"):
        self.events = []
        self._holder = self if holder == "self" else holder

    def grab_current(self):
        return self._holder

    def grab_release(self):
        self.events.append("release")

    def grab_set(self):
        self.events.append("set")

    def update_idletasks(self):
        self.events.append("flush")


def _patch_subprocess(monkeypatch, result="/mnt/Playlists", fail=False):
    from music_manager.interfaces import filedialog as fd

    class _Result:
        returncode = 0
        stdout = result

    def fake_run(cmd, **kwargs):
        if fail:
            raise OSError("zenity is not installed")
        return _Result()

    monkeypatch.setattr(fd.subprocess, "run", fake_run)
    return fd


def test_grab_is_released_while_the_chooser_is_open(monkeypatch):
    fd = _patch_subprocess(monkeypatch)
    parent = _FakeWidget()

    assert fd._run(["zenity"], parent) == "/mnt/Playlists"
    # Released before the wait, restored after — never the other way round.
    assert parent.events == ["release", "flush", "set"]


def test_the_grab_is_restored_even_when_the_chooser_fails(monkeypatch):
    fd = _patch_subprocess(monkeypatch, fail=True)
    parent = _FakeWidget()

    assert fd._run(["zenity"], parent) == ""
    assert parent.events[-1] == "set", "a crash must not leave the app grabless"


def test_a_grab_held_by_another_widget_is_the_one_restored(monkeypatch):
    fd = _patch_subprocess(monkeypatch)
    holder = _FakeWidget()
    parent = _FakeWidget(holder=holder)

    fd._run(["zenity"], parent)
    assert holder.events == ["release", "set"]
    assert parent.events == ["flush"], "parent only flushes; it holds no grab"


def test_nothing_happens_when_no_grab_is_held(monkeypatch):
    fd = _patch_subprocess(monkeypatch)
    parent = _FakeWidget(holder=None)

    fd._run(["zenity"], parent)
    assert parent.events == []


def test_no_parent_is_tolerated(monkeypatch):
    fd = _patch_subprocess(monkeypatch)
    assert fd._run(["zenity"]) == "/mnt/Playlists"


def test_the_settings_folder_browser_passes_its_parent(monkeypatch):
    """The regression path: Settings is modal, so parent must reach _run."""
    fd, calls = _patch_backends(monkeypatch)
    seen = {}
    monkeypatch.setattr(fd, "_run",
                        lambda cmd, parent=None: seen.update(parent=parent) or "")
    sentinel = object()

    fd.askdirectory(title="Select Playlist Folder", parent=sentinel)
    assert seen["parent"] is sentinel
