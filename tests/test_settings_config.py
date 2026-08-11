"""v3.6.1: the settings dialog folds its fields into the loaded config.

The dialog shows Database, Plex and M3U. It does not show cron, webhook,
or autosave — and it used to rebuild config.json from its fields alone,
deleting every one of them. For a MariaDB install that silently dropped
the server and fell back to SQLite. These tests pin what a save must
leave alone.

v3.6.2: the database section is chosen in the dialog rather than being
one of the blocks it had to preserve blindly, so these also cover the
backend it writes.
"""

from pathlib import Path

import pytest

from music_manager.core.config import (
    ConfigError, DbSettings, resolve_db_settings, validate_config,
)
from music_manager.core.database import DATABASE_PATH
from music_manager.interfaces.gui.dialogs import apply_settings_fields


DEFAULT_FIELDS = {
    "plex_base_url": "",
    "plex_token": "",
    "plex_token_env": "",
    "plex_music_section": "",
    "plex_path_rules": [],
    "m3u_path_style": "absolute",
    "m3u_path_rules": [],
    # An untouched dialog shows the backend in use with its own settings;
    # mysql_fields() below fills these the way a MariaDB install would.
    "db_backend": "sqlite",
    "db_path": "",
    "db_host": "",
    "db_port": "",
    "db_name": "",
    "db_user": "",
    "db_password": "",
    "db_password_env": "",
    "db_charset": "",
}


def mysql_fields(**overrides):
    """Dialog fields as the MySQL panel prefills them from full_config()."""
    values = dict(
        db_backend="mysql", db_host="mariadb.lan", db_port="3306",
        db_name="classical_manager", db_user="cmanager", db_password="",
        db_password_env="CM_DB_PASSWORD", db_charset="utf8mb4")
    values.update(overrides)
    return fields(**values)


def fields(**overrides):
    """Dialog field values, defaulting to an untouched dialog."""
    values = dict(DEFAULT_FIELDS)
    values.update(overrides)
    return values


def full_config():
    """A config shaped like a real MariaDB install."""
    return {
        "active_library": 1,
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

@pytest.mark.parametrize("key", ["cron", "webhook", "autosave_interval"])
def test_unshown_sections_survive_a_save(key):
    original = full_config()
    saved = apply_settings_fields(original, mysql_fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved[key] == original[key]


def test_the_database_connection_is_not_dropped():
    # The regression that mattered: losing this block sends a MariaDB
    # install back to SQLite without saying so. The dialog now writes the
    # section rather than carrying it, so this pins the same outcome
    # against a different mechanism.
    saved = apply_settings_fields(full_config(), mysql_fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved["database"]["backend"] == "mysql"
    assert saved["database"]["name"] == "classical_manager"


def test_target_keys_without_a_field_survive():
    # 'strategy' is read by plex.py but has no widget in the dialog.
    saved = apply_settings_fields(full_config(), mysql_fields(
        plex_base_url="http://plex:32400", plex_token_env="TOK"))
    assert saved["targets"]["plex"]["strategy"] == "item_match"


def test_the_original_config_is_not_mutated():
    original = full_config()
    apply_settings_fields(original, fields(db_path="/tmp/other.db"))
    assert original["database"]["backend"] == "mysql"


def test_an_untouched_dialog_round_trips_the_config():
    original = full_config()
    saved = apply_settings_fields(original, mysql_fields(
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


# --- Choosing a backend -------------------------------------------------------

def test_switching_to_sqlite_writes_the_chosen_file():
    saved = apply_settings_fields(full_config(), fields(db_path="/tmp/x.db"))
    assert saved["database"]["backend"] == "sqlite"
    assert saved["database"]["path"] == "/tmp/x.db"
    assert resolve_db_settings(saved) == DbSettings(
        backend="sqlite", path=Path("/tmp/x.db"))


def test_switching_to_sqlite_keeps_the_server_settings():
    # So that a temporary switch does not cost you a retyped server.
    saved = apply_settings_fields(full_config(), fields(db_path="/tmp/x.db"))
    assert saved["database"]["host"] == "mariadb.lan"
    assert saved["database"]["name"] == "classical_manager"


def test_switching_to_mysql_writes_the_connection():
    config = {"active_library": 1, "targets": {},
              "database": {"backend": "sqlite", "path": "/tmp/x.db"}}
    saved = apply_settings_fields(config, mysql_fields(
        db_host="db.lan", db_name="cm", db_user="me", db_password="hunter2",
        db_password_env=""))
    assert saved["database"] == {
        "backend": "mysql", "path": "/tmp/x.db", "host": "db.lan",
        "port": 3306, "name": "cm", "user": "me", "password": "hunter2",
        "charset": "utf8mb4"}


def test_the_default_sqlite_path_is_not_written_out():
    # The field is prefilled with the path in use, so an untouched dialog
    # would otherwise pin the default into config.json and break the app
    # if the checkout ever moved.
    saved = apply_settings_fields(full_config(),
                                  fields(db_path=str(DATABASE_PATH)))
    assert "path" not in saved["database"]
    assert resolve_db_settings(saved).path == DATABASE_PATH


def test_the_legacy_db_path_is_dropped():
    # Both would mean config.json naming one database and the app opening
    # another, since resolve_db_settings prefers database.path.
    config = {**full_config(), "db_path": "/old/lib.db"}
    saved = apply_settings_fields(config, fields(db_path="/new/lib.db"))
    assert "db_path" not in saved
    assert saved["database"]["path"] == "/new/lib.db"


def test_an_empty_password_field_removes_the_password():
    config = full_config()
    config["database"]["password"] = "was-here"
    saved = apply_settings_fields(config, mysql_fields())
    assert "password" not in saved["database"]
    assert saved["database"]["password_env"] == "CM_DB_PASSWORD"


def test_a_typed_password_is_written():
    saved = apply_settings_fields(full_config(),
                                  mysql_fields(db_password="hunter2"))
    assert saved["database"]["password"] == "hunter2"


def test_an_empty_port_falls_back_to_the_default():
    saved = apply_settings_fields(full_config(), mysql_fields(db_port=""))
    assert saved["database"]["port"] == 3306


def test_a_typed_port_is_stored_as_a_number():
    saved = apply_settings_fields(full_config(), mysql_fields(db_port=" 3307 "))
    assert saved["database"]["port"] == 3307


def test_a_non_numeric_port_is_kept_for_validation_to_reject(tmp_path):
    # Substituting the default would connect somewhere the user did not ask
    # for; this way the dialog refuses to save and says which field is wrong.
    saved = apply_settings_fields(full_config(), mysql_fields(db_port="33o6"))
    with pytest.raises(ConfigError, match=r"database\.port"):
        validate_config(saved, tmp_path / "config.json")


def test_a_server_with_no_password_at_all_is_rejected(tmp_path):
    saved = apply_settings_fields(full_config(),
                                  mysql_fields(db_password_env=""))
    with pytest.raises(ConfigError, match="password"):
        validate_config(saved, tmp_path / "config.json")


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
