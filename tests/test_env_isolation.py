"""Dev checkout vs installed copy must not be confusable.

A development copy rewrote the shared .desktop launcher on every start,
so the menu entry silently pointed at dev code — which then loaded dev
config and a dev database. These tests pin the guard and the title that
makes the active database visible.
"""

from pathlib import Path

import music_manager.interfaces.gui.app as app_mod
from music_manager.interfaces.gui.app import App


class _FakeRoot:
    """Records what the app would write, without touching Tk."""

    def __init__(self):
        self.icon_calls = []

    def wm_iconphoto(self, *_a):
        self.icon_calls.append("photo")


def _make_app(tmp_path, monkeypatch, *, is_dev):
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)
    if is_dev:
        (tmp_path / ".git").mkdir()
    return tmp_path


def test_dev_checkout_does_not_write_desktop_entry(tmp_path, monkeypatch):
    project = _make_app(tmp_path / "proj", monkeypatch, is_dev=True)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    app = App.__new__(App)
    app._install_desktop_entry(project / "app_icon.png")

    desktop = home / ".local" / "share" / "applications"
    assert not desktop.exists(), "dev copy must not touch the launcher"


def test_installed_copy_writes_desktop_entry(tmp_path, monkeypatch):
    project = _make_app(tmp_path / "proj", monkeypatch, is_dev=False)
    project.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    app = App.__new__(App)
    app._install_desktop_entry(project / "app_icon.png")

    entry = home / ".local" / "share" / "applications" / \
        "classical-manager.desktop"
    assert entry.exists()
    text = entry.read_text()
    assert str(project / "main.py") in text
    assert "StartupWMClass=classical-manager" in text


def test_title_names_the_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "music_manager.core.config.get_db_path",
        lambda: Path("/mnt/MediaLib/music_manager.db"))

    title = App._window_title()
    assert "music_manager.db" in title
    assert "[dev]" not in title


def test_title_flags_dev_checkout(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "music_manager.core.config.get_db_path",
        lambda: Path("/tmp/scratch.db"))

    title = App._window_title()
    assert title.endswith("scratch.db [dev]")


def test_title_survives_config_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)

    def boom():
        raise RuntimeError("no config")
    monkeypatch.setattr("music_manager.core.config.get_db_path", boom)

    assert App._window_title() == "Classical Music Playlist Manager"


def test_empty_db_path_resolves_to_default(tmp_path, monkeypatch):
    """The dev config had db_path: '' — falsy, so it silently fell back
    to the bundled database. Settings must show that effective path."""
    import json
    from music_manager.core import config as config_mod

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(
        {"active_library": 1, "targets": {}, "db_path": ""}))
    monkeypatch.setattr(config_mod, "_config_path_override", cfg)

    from music_manager.core.database import DATABASE_PATH
    assert config_mod.get_db_path() == DATABASE_PATH
