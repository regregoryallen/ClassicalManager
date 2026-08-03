"""v3.5 Phase 1: resolving which database to connect to.

The backend is chosen from config, so these tests pin the resolution rules
rather than any connection behaviour — no server is needed. Live MariaDB
coverage arrives with the test matrix in a later phase.
"""

import json

import pytest

from music_manager.core.config import (
    ConfigError, DbSettings, resolve_db_settings, set_config_path,
)
from music_manager.core.database import DATABASE_PATH


@pytest.fixture(autouse=True)
def _restore_config_path():
    """Each test points the loader at its own file; put it back afterwards."""
    import music_manager.core.config as cfg
    original = cfg._config_path_override
    yield
    cfg._config_path_override = original


def _write(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    set_config_path(path)
    return path


BASE = {"active_library": 1, "targets": {}}


# ---------------------------------------------------------------------------
# SQLite stays the default
# ---------------------------------------------------------------------------

def test_no_database_section_uses_sqlite_db_path(tmp_path):
    _write(tmp_path, {**BASE, "db_path": "/music/lib.db"})
    s = resolve_db_settings()
    assert s.backend == "sqlite"
    assert str(s.path) == "/music/lib.db"


def test_no_database_section_and_no_db_path_uses_default(tmp_path):
    _write(tmp_path, BASE)
    s = resolve_db_settings()
    assert s.backend == "sqlite"
    assert s.path == DATABASE_PATH


def test_explicit_sqlite_backend_honours_its_own_path(tmp_path):
    _write(tmp_path, {**BASE, "db_path": "/old/ignored.db",
                      "database": {"backend": "sqlite", "path": "/new/lib.db"}})
    assert str(resolve_db_settings().path) == "/new/lib.db"


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------

MYSQL = {"backend": "mysql", "host": "db.lan", "port": 3307,
         "name": "cm", "user": "u", "password": "secret"}


def test_mysql_section_is_resolved(tmp_path):
    _write(tmp_path, {**BASE, "database": MYSQL})
    s = resolve_db_settings()
    assert (s.backend, s.host, s.port, s.name, s.user) == \
        ("mysql", "db.lan", 3307, "cm", "u")
    assert s.password == "secret"
    assert s.charset == "utf8mb4"      # defaulted; the server hands out latin1


def test_password_env_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CM_TEST_DB_PW", "from-env")
    _write(tmp_path, {**BASE,
                      "database": {**MYSQL, "password_env": "CM_TEST_DB_PW"}})
    assert resolve_db_settings().password == "from-env"


def test_password_env_unset_falls_back_to_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CM_TEST_DB_PW", raising=False)
    _write(tmp_path, {**BASE,
                      "database": {**MYSQL, "password_env": "CM_TEST_DB_PW"}})
    assert resolve_db_settings().password == "secret"


def test_password_env_unset_with_no_file_password_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("CM_TEST_DB_PW", raising=False)
    db = {k: v for k, v in MYSQL.items() if k != "password"}
    _write(tmp_path, {**BASE, "database": {**db, "password_env": "CM_TEST_DB_PW"}})
    with pytest.raises(ConfigError, match="CM_TEST_DB_PW"):
        resolve_db_settings()


def test_describe_never_leaks_the_password():
    """describe() goes into logs and error dialogs."""
    s = DbSettings(backend="mysql", host="h", name="n", user="u",
                   password="hunter2")
    assert "hunter2" not in s.describe()
    assert s.describe() == "mysql://u@h:3306/n"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section, expected", [
    ({"backend": "postgres"}, "must be one of"),
    ({"backend": "mysql", "password": "p"}, "'database.name' is required"),
    ({"backend": "mysql", "name": "cm", "password": "p", "port": 0},
     "must be an integer 1-65535"),
    ({"backend": "mysql", "name": "cm", "port": "3306", "password": "p"},
     "must be an integer"),
    ({"backend": "mysql", "name": "cm"}, "requires either 'password'"),
    ({"backend": "mysql", "name": 5, "password": "p"}, "must be a string"),
])
def test_invalid_database_sections_are_rejected(tmp_path, section, expected):
    _write(tmp_path, {**BASE, "database": section})
    with pytest.raises(ConfigError, match=expected):
        resolve_db_settings()
