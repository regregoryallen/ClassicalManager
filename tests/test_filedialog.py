"""v3.2: save dialogs must pre-populate the suggested filename.

The M3U/JSON export dialogs passed a bare filename ("Morning Mix.m3u")
when no export directory had been saved yet. GTK (zenity) and kdialog
need an ABSOLUTE path — given a relative one they silently ignore it,
leaving the Name field empty and opening in the process CWD (/tmp).
"""

import os

from music_manager.interfaces.filedialog import _save_start_path


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
    monkeypatch.setattr(fd, "_run", lambda cmd: calls["zenity"].append(cmd) or "")
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
