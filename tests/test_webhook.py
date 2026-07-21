"""Webhook tests: m3u filename sanitization and thumbs-down argv building."""

import os

import pytest

from music_manager.interfaces.webhook import JobManager


def _manager(commands=("m3u",)):
    return JobManager(
        python_path="/usr/bin/python", main_path="/app/main.py",
        config_arg=[], library_name="Lib",
        allowed_commands=list(commands), m3u_output_dir="/out")


def _m3u_path(profile):
    steps = _manager()._build_steps("m3u", profile=profile)
    argv = steps[0]
    return argv[argv.index("--output") + 1]


def test_normal_profile_name():
    assert _m3u_path("Sunday Classical") == os.path.join(
        "/out", "Sunday_Classical.m3u")


def test_path_traversal_attempts_are_neutralized():
    for evil in ("../../etc/cron.d/x", "..\\..\\win", "...", "/abs/path"):
        path = _m3u_path(evil)
        name = os.path.basename(path)
        assert path == os.path.join("/out", name)
        assert not name.startswith(".")
        assert "/" not in name and "\\" not in name


def test_empty_after_sanitization_falls_back():
    # All-dots strips to nothing → generic fallback name.
    assert _m3u_path("...") == os.path.join("/out", "playlist.m3u")


# ---------------------------------------------------------------------------
# Thumbs-down (exclude-track)
# ---------------------------------------------------------------------------

def _exclude_argv(profile, track):
    mgr = _manager(["exclude-track"])
    (argv,) = mgr._build_steps("exclude-track", profile=profile, track=track)
    return argv


def test_exclude_track_argv_from_now_playing():
    argv = _exclude_argv("Morning Mix", {
        "title": "Adagio", "album": "Spartacus", "artist": "Bolshoi"})
    assert argv[argv.index("--profile") + 1] == "Morning Mix"
    assert argv[argv.index("--title") + 1] == "Adagio"
    assert argv[argv.index("--album") + 1] == "Spartacus"
    assert argv[argv.index("--artist") + 1] == "Bolshoi"
    assert "--scope" not in argv  # defaults to track


def test_exclude_track_omits_absent_fields_and_passes_scope():
    argv = _exclude_argv("P", {"path": "A/Alb1/01.flac", "scope": "work"})
    assert "--title" not in argv
    assert "--album" not in argv
    assert argv[argv.index("--path") + 1] == "A/Alb1/01.flac"
    assert argv[argv.index("--scope") + 1] == "work"


def test_exclude_track_requires_profile_and_identifier():
    mgr = _manager(["exclude-track"])
    with pytest.raises(ValueError):
        mgr._build_steps("exclude-track", track={"title": "X"})
    with pytest.raises(ValueError):
        mgr._build_steps("exclude-track", profile="P", track={})


def test_unknown_command_still_rejected():
    mgr = _manager(["m3u"])
    with pytest.raises(ValueError):
        mgr.submit("exclude-track")  # not in allowed_commands
