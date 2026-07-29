"""v3.3: "Show in Folder" path resolution.

The platform dispatch itself needs a desktop, but which path each menu
entry resolves to is pure logic and worth pinning — a work reveals its
first track, an album reveals its folder, and a vanished file degrades
to its parent directory rather than erroring.
"""

from pathlib import Path

from music_manager.core.database import Track, Work
from music_manager.interfaces.gui.app import App

from tests.conftest import make_album


class _RevealApp:
    """Captures what _show_in_folder would be handed."""

    _show_track_in_folder = App._show_track_in_folder
    _show_album_in_folder = App._show_album_in_folder
    _show_work_in_folder = App._show_work_in_folder

    def __init__(self):
        self.revealed = []

    def _show_in_folder(self, path):
        self.revealed.append(Path(path))


def test_track_resolves_to_its_file(lib):
    album = make_album(lib, "Bach/Cantatas", [("BWV 140", 2)])
    track = Track.select().where(Track.album == album).first()

    app = _RevealApp()
    app._show_track_in_folder(track.id)

    assert app.revealed == [Path("/music/Bach/Cantatas/01.flac")]


def test_album_resolves_to_its_folder(lib):
    album = make_album(lib, "Bach/Cantatas", [("BWV 140", 2)])

    app = _RevealApp()
    app._show_album_in_folder(album.id)

    assert app.revealed == [Path("/music/Bach/Cantatas")]


def test_work_resolves_via_its_first_track(lib):
    album = make_album(lib, "Bach/Cantatas", [("BWV 140", 2), ("BWV 147", 2)])
    second = Work.get(Work.work_name == "BWV 147")

    app = _RevealApp()
    app._show_work_in_folder(second.id)

    # Third track overall is the first of the second work.
    assert app.revealed == [Path("/music/Bach/Cantatas/03.flac")]


def test_trackless_work_falls_back_to_the_album(lib):
    album = make_album(lib, "Bach/Cantatas", [("BWV 140", 1)])
    ghost = Work.create(album=album, work_name="Ghost", work_sequence=9,
                        work_source="standalone")

    app = _RevealApp()
    app._show_work_in_folder(ghost.id)

    assert app.revealed == [Path("/music/Bach/Cantatas")]


def test_missing_entities_do_not_raise(lib):
    app = _RevealApp()
    app._show_track_in_folder(9999)
    app._show_album_in_folder(9999)
    app._show_work_in_folder(9999)
    assert app.revealed == []


def test_vanished_file_degrades_to_its_folder(tmp_path, monkeypatch):
    """A deleted file should still open the folder it lived in."""
    import subprocess

    import music_manager.interfaces.gui.app as app_mod

    opened = []
    monkeypatch.setattr(app_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, *a, **k: opened.append(cmd))
    monkeypatch.setattr(App, "_linux_reveal", staticmethod(lambda p: False))

    app = App.__new__(App)
    app._show_in_folder(tmp_path / "gone.flac")

    assert opened == [["xdg-open", str(tmp_path)]]
