"""Phase 6 test: webhook m3u filename sanitization (allowlist)."""

import os

from music_manager.interfaces.webhook import JobManager


def _manager():
    return JobManager(
        python_path="/usr/bin/python", main_path="/app/main.py",
        config_arg=[], library_name="Lib",
        allowed_commands=["m3u"], m3u_output_dir="/out")


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
