"""Startup config checking (v3.11).

The point of check_config is that a broken config.json stops being
silent. Before this, resolve_db_settings swallowed ConfigError and
returned the default SQLite path, so a typo opened a different database
without saying so.

These cover the three outcomes the entry points branch on: fine,
absent, and present-but-wrong.
"""

import json

import pytest

from music_manager.core.config import check_config


def _write(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8")
    return path


VALID = {"active_library": 1, "targets": {}}


# ---------------------------------------------------------------------------
# The three outcomes
# ---------------------------------------------------------------------------

def test_a_valid_config_is_ok_with_nothing_to_say(tmp_path):
    status = check_config(_write(tmp_path, VALID))

    assert status.ok
    assert not status.missing
    assert status.error is None
    assert status.warnings == ()


def test_an_absent_file_is_missing_not_an_error(tmp_path):
    """A first run has no config. That must not read as a failure."""
    status = check_config(tmp_path / "config.json")

    assert status.missing
    assert status.ok
    assert status.error is None


def test_malformed_json_reports_line_and_column(tmp_path):
    status = check_config(_write(tmp_path, '{"active_library": 1,,}'))

    assert not status.ok
    assert "Invalid JSON" in status.error
    assert "line 1" in status.error
    assert "column" in status.error


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------

def test_a_missing_required_key_is_an_error(tmp_path):
    status = check_config(_write(tmp_path, {"targets": {}}))

    assert not status.ok
    assert "active_library" in status.error


def test_a_bad_value_is_an_error(tmp_path):
    status = check_config(
        _write(tmp_path, {"active_library": "one", "targets": {}}))

    assert not status.ok
    assert "active_library" in status.error


def test_the_error_does_not_repeat_the_path(tmp_path):
    """Callers print status.path themselves; naming it twice reads badly."""
    path = _write(tmp_path, {"targets": {}})
    status = check_config(path)

    assert not status.error.startswith(str(path))
    assert status.path == path


def test_an_invalid_database_section_is_caught(tmp_path):
    status = check_config(_write(tmp_path, {
        "active_library": 1,
        "targets": {},
        "database": {"backend": "postgres"},
    }))

    assert not status.ok
    assert "backend" in status.error


# ---------------------------------------------------------------------------
# Warnings are not errors
# ---------------------------------------------------------------------------

def test_warnings_do_not_make_a_config_unusable(tmp_path):
    """Warnings flag settings that read as active and do nothing.

    Worth saying once; never a reason to refuse to start. base_path was
    removed in v3.6.1 and is the standing example.
    """
    status = check_config(_write(tmp_path, {
        "active_library": 1,
        "targets": {"m3u": {"base_path": "/srv/music"}},
    }))

    assert status.ok
    assert status.error is None
    assert any("base_path" in w for w in status.warnings)


# ---------------------------------------------------------------------------
# check_config must not raise, whatever it is given
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "",                      # empty file
    "[]",                    # valid JSON, wrong shape
    "null",
    '{"active_library": 0, "targets": {}}',
    "\x00\x01\x02",
])
def test_hostile_files_are_reported_not_raised(tmp_path, payload):
    status = check_config(_write(tmp_path, payload))

    assert not status.ok
    assert isinstance(status.error, str) and status.error


# ---------------------------------------------------------------------------
# What the GUI does with each outcome
#
# The dialogs are stubbed: what matters is the branching, in particular
# that the default answer to a broken config is "do not start". Starting
# on the fallback means working in a different database, which is the
# failure this whole check exists to stop being silent.
# ---------------------------------------------------------------------------

@pytest.fixture
def preflight(tmp_path, monkeypatch):
    """Run _config_preflight against a config file we control."""
    from unittest import mock

    import music_manager.interfaces.gui.app as gui_app
    from music_manager.core import config as config_mod

    path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "_config_path_override", path)

    def run(payload, answer=False, prefs=None):
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _write(tmp_path, payload)
        prefs = {} if prefs is None else prefs
        with mock.patch("tkinter.Tk"), \
             mock.patch("tkinter.messagebox.askyesno",
                        return_value=answer) as ask, \
             mock.patch("tkinter.messagebox.showwarning") as warn, \
             mock.patch.object(gui_app, "_save_prefs"):
            started = gui_app._config_preflight(prefs)
        return started, ask, warn, prefs

    return run


def test_gui_starts_on_a_valid_config_without_asking(preflight):
    started, ask, warn, _ = preflight(VALID)

    assert started
    assert not ask.called
    assert not warn.called


def test_gui_starts_on_a_missing_config_without_asking(preflight):
    started, ask, _, _ = preflight(None)

    assert started
    assert not ask.called


def test_gui_does_not_start_when_the_answer_is_no(preflight):
    """No is the default button: a broken config stops the app."""
    started, ask, _, _ = preflight('{"active_library": 1,,}', answer=False)

    assert ask.called
    assert not started


def test_gui_starts_on_defaults_only_when_explicitly_chosen(preflight):
    started, ask, _, _ = preflight('{"active_library": 1,,}', answer=True)

    assert ask.called
    assert started


def test_warnings_are_shown_once_and_then_acknowledged(preflight):
    payload = json.dumps({"active_library": 1,
                          "targets": {"m3u": {"base_path": "/srv/music"}}})

    started, _, warn, prefs = preflight(payload)
    assert started and warn.called
    assert "config_warnings_ack" in prefs

    # Same warnings, already acknowledged: stay quiet.
    _, _, warn_again, _ = preflight(payload, prefs=prefs)
    assert not warn_again.called


def test_the_acknowledgement_is_keyed_on_path_and_warnings(preflight,
                                                          tmp_path):
    """Not a blanket "never warn again" flag.

    Stored as the config path plus its warnings, so a different config
    file — or the same file developing a different problem — is a
    different signature and speaks up again.
    """
    payload = json.dumps({"active_library": 1,
                          "targets": {"m3u": {"base_path": "/srv/music"}}})
    _, _, warn, prefs = preflight(payload)
    assert warn.called

    signature = prefs["config_warnings_ack"]
    assert str(tmp_path / "config.json") in signature
    assert any("base_path" in part for part in signature[1:])
