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
