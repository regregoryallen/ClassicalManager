"""v3.6.1: the settings dialog folds its fields into the loaded config.

The dialog shows Database, Plex and M3U. It does not show the
database *connection* block, cron, webhook, or autosave — and it used to
rebuild config.json from its fields alone, deleting every one of them.
For a MariaDB install that silently dropped the server and fell back to
SQLite. These tests pin what a save must leave alone.
"""

import pytest

from music_manager.core.config import ConfigError, validate_config
from music_manager.interfaces.gui.dialogs import apply_settings_fields


DEFAULT_FIELDS = {
    "plex_base_url": "",
    "plex_token": "",
    "plex_token_env": "",
    "plex_music_section": "",
    "plex_path_rules": [],
    "m3u_path_style": "absolute",
    "m3u_path_rules": [],
    "db_path": "",
}


def fields(**overrides):
    """Dialog field values, defaulting to an untouched dialog."""
    values = dict(DEFAULT_FIELDS)
    values.update(overrides)
    return values


def full_config():
    """A config shaped like a real MariaDB install."""
    return {
        "active_library": 1,
        "db_path": "",
        "autosave_interval": 60,
        "database": {
            "backend": "mysql", "host": "mariadb.lan", "port": 3306,
            "name": "classical_manager", "user": "cmanager",
            "password_env": "CM_DB_PASSWORD", "charset": "utf8mb4",
        },
        "targets": {
            "plex": {"base_url": "http://plex:32400", "token_env": "TOK",
                     "strategy": "item_match", "path_rules": []},
            "m3u": {"path_style": "absolute", "path_rules": []},
        },
        "cron": {"library": "MainMusic", "mode": "plex", "verbosity": "-q"},
        "webhook": {"host": "0.0.0.0", "port": 5588,
                    "allowed_commands": ["plex", "scan"]},
    }


# --- What a save must not destroy ---------------------------------------------

@pytest.mark.parametrize("key", ["database", "cron", "webhook",
                                 "autosave_interval"])
def test_unshown_sections_survive_a_save(key):
    original = full_config()
    saved = apply_settings_fields(original, fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved[key] == original[key]


def test_the_database_connection_is_not_dropped():
    # The regression that mattered: losing this block sends a MariaDB
    # install back to SQLite without saying so.
    saved = apply_settings_fields(full_config(), fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved["database"]["backend"] == "mysql"
    assert saved["database"]["name"] == "classical_manager"


def test_target_keys_without_a_field_survive():
    # 'strategy' is read by plex.py but has no widget in the dialog.
    saved = apply_settings_fields(full_config(), fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved["targets"]["plex"]["strategy"] == "item_match"


def test_the_original_config_is_not_mutated():
    original = full_config()
    apply_settings_fields(original, fields(db_path="/tmp/other.db"))
    assert original["db_path"] == ""


def test_an_untouched_dialog_round_trips_the_config():
    original = full_config()
    saved = apply_settings_fields(original, fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved == original


# --- The fields the dialog does own -------------------------------------------

def test_plex_fields_are_applied():
    saved = apply_settings_fields(full_config(), fields(
        plex_base_url="http://new:32400", plex_token="abc",
        plex_music_section="Classical",
        plex_path_rules=[{"find": "/a", "replace": "/b"}]))
    plex = saved["targets"]["plex"]
    assert plex["base_url"] == "http://new:32400"
    assert plex["token"] == "abc"
    assert plex["music_section"] == "Classical"
    assert plex["path_rules"] == [{"find": "/a", "replace": "/b"}]


def test_clearing_a_plex_field_removes_that_key():
    config = full_config()
    config["targets"]["plex"]["music_section"] = "Music"
    saved = apply_settings_fields(config, fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert "music_section" not in saved["targets"]["plex"]


def test_clearing_the_plex_url_removes_the_target():
    saved = apply_settings_fields(full_config(), fields())
    assert "plex" not in saved["targets"]


def test_m3u_fields_are_applied():
    saved = apply_settings_fields(full_config(), fields(
        m3u_path_style="relative_to_playlist",
        m3u_path_rules=[{"find": "/a", "replace": "/b"}]))
    m3u = saved["targets"]["m3u"]
    assert m3u["path_style"] == "relative_to_playlist"
    assert m3u["path_rules"] == [{"find": "/a", "replace": "/b"}]


def test_db_path_is_applied_when_set():
    saved = apply_settings_fields(full_config(), fields(db_path="/tmp/x.db"))
    assert saved["db_path"] == "/tmp/x.db"


def test_an_empty_db_path_leaves_the_existing_one():
    config = full_config()
    config["db_path"] = "/keep/me.db"
    assert apply_settings_fields(config, fields())["db_path"] == "/keep/me.db"


# --- Validating before writing ------------------------------------------------

def test_a_config_the_dialog_builds_is_valid(tmp_path):
    saved = apply_settings_fields(full_config(), fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert validate_config(saved, tmp_path / "config.json") == []


def test_an_invalid_path_style_is_caught_before_writing(tmp_path):
    # The dialog validates and refuses to save rather than writing a
    # config.json the app cannot load on its next start.
    saved = apply_settings_fields(full_config(), fields(
        m3u_path_style="sideways"))
    with pytest.raises(ConfigError, match=r"targets\.m3u\.path_style"):
        validate_config(saved, tmp_path / "config.json")


def test_a_leftover_base_path_warns_but_still_saves(tmp_path):
    config = full_config()
    config["targets"]["m3u"]["base_path"] = "/mnt/MediaLib/Albums/Playlists"
    saved = apply_settings_fields(config, fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    warnings = validate_config(saved, tmp_path / "config.json")
    assert len(warnings) == 1 and "no longer applied" in warnings[0]
