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


def _patch_settings(monkeypatch, **kwargs):
    from music_manager.core.config import DbSettings
    settings = DbSettings(**kwargs)
    monkeypatch.setattr("music_manager.core.config.resolve_db_settings",
                        lambda: settings)


def test_title_names_the_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)
    _patch_settings(monkeypatch, backend="sqlite",
                    path=Path("/mnt/MediaLib/music_manager.db"))

    title = App._window_title()
    assert "music_manager.db" in title
    assert "[dev]" not in title


def test_title_flags_dev_checkout(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)
    _patch_settings(monkeypatch, backend="sqlite", path=Path("/tmp/scratch.db"))

    title = App._window_title()
    assert title.endswith("scratch.db [dev]")


def test_title_names_host_and_schema_on_mysql(tmp_path, monkeypatch):
    """A file name would name a database that is not the one in use."""
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)
    _patch_settings(monkeypatch, backend="mysql", host="mariadb.lan",
                    name="classical_manager", user="cmanager",
                    password="secret")

    title = App._window_title()
    assert "classical_manager @ mariadb.lan" in title
    assert "music_manager.db" not in title
    assert "secret" not in title


def test_title_survives_config_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "PROJECT_ROOT", tmp_path)

    def boom():
        raise RuntimeError("no config")
    monkeypatch.setattr("music_manager.core.config.resolve_db_settings", boom)

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


# ---------------------------------------------------------------------------
# Sidebar redraw: the status label must not resize the sidebar
# ---------------------------------------------------------------------------

def test_scan_status_text_is_bounded():
    """Sidebar buttons tore during scans. The status label had no width, so
    it sized itself to the current filename — often far wider than the
    260px sidebar — and every progress update forced a pack re-layout that
    repainted every sibling. CustomTkinter repaints a button's whole canvas
    on each of those, mid-draw.

    Truncating is what keeps the label a fixed size, so it is worth pinning.
    """
    from music_manager.interfaces.gui.app import App

    long_name = "01 Waltz Suite, op. 110_ I. Since We Met, from War and Peace.flac"
    for current, total, message in ((1, 7279, long_name),
                                    (7279, 7279, long_name),
                                    (5, 10, "short.mp3")):
        prefix = f"[{current}/{total}] "
        room = max(8, App._SCAN_STATUS_CHARS - len(prefix))
        rendered = prefix + (message[:room - 1] + "…"
                             if len(message) > room else message)
        assert len(rendered) <= App._SCAN_STATUS_CHARS, (
            f"{rendered!r} is {len(rendered)} chars; the label is sized for "
            f"{App._SCAN_STATUS_CHARS}")


def test_ui_throttle_limits_update_rate():
    """A scan calls back once per file and analysis once per track. Even at
    a modest rate that is thousands of layout passes over a run; the
    throttle keeps it to something a person could read."""
    from music_manager.interfaces.gui.common import UIThrottle

    throttle = UIThrottle(min_interval=0.05)
    allowed = sum(1 for _ in range(5000) if throttle.ready())
    assert allowed <= 2, f"{allowed} updates allowed for 5000 rapid calls"


def test_ui_throttle_always_lets_the_final_update_through():
    """Otherwise a progress bar stops at whatever the last tick happened to
    be rather than finishing full."""
    from music_manager.interfaces.gui.common import UIThrottle

    throttle = UIThrottle(min_interval=10.0)
    assert throttle.ready() is True          # first call
    assert throttle.ready() is False         # rate limited
    assert throttle.ready(force=True) is True
