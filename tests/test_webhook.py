"""Webhook tests: m3u filename sanitization and thumbs-down argv building."""

import os

import pytest

from music_manager.interfaces.webhook import JobManager


def _manager(commands=("m3u",), library_dirs=None):
    return JobManager(
        python_path="/usr/bin/python", main_path="/app/main.py",
        config_arg=[], library_name="Lib",
        allowed_commands=list(commands), m3u_output_dir="/out",
        library_dirs=library_dirs)


# The daily/holiday split this was built for: two libraries, two
# directories, chosen per request.
SEASONAL = {"MainMusic": "/mnt/Albums/Playlists",
            "XmasMusic": "/mnt/Albums/XmasPlaylists"}


def _seasonal(commands=("m3u", "scan+m3u", "plex", "scan")):
    mgr = _manager(commands, library_dirs=SEASONAL)
    mgr._library = "MainMusic"  # the configured default
    return mgr


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


# ---------------------------------------------------------------------------
# Per-library output directories
# ---------------------------------------------------------------------------

def _out_dir(mgr, command="m3u", library=None):
    (argv,) = mgr._build_steps(command, library=library)
    return argv[argv.index("--output-dir") + 1]


def _lib_arg(argv):
    return argv[argv.index("--library") + 1]


def test_each_library_writes_to_its_own_directory():
    mgr = _seasonal()
    assert _out_dir(mgr, library="MainMusic") == "/mnt/Albums/Playlists"
    assert _out_dir(mgr, library="XmasMusic") == "/mnt/Albums/XmasPlaylists"


def test_omitted_library_uses_the_configured_default():
    mgr = _seasonal()
    (argv,) = mgr._build_steps("m3u")
    assert _lib_arg(argv) == "MainMusic"
    assert _out_dir(mgr) == "/mnt/Albums/Playlists"


def test_unlisted_library_is_refused_not_defaulted():
    # The point of the strict map: an unlisted library must not quietly
    # write into the default library's directory.
    mgr = _seasonal()
    with pytest.raises(ValueError, match="unknown library"):
        mgr._build_steps("m3u", library="PartyMusic")


def test_scan_and_generate_target_the_same_library():
    mgr = _seasonal()
    scan_argv, m3u_argv = mgr._build_steps("scan+m3u", library="XmasMusic")
    assert _lib_arg(scan_argv) == "XmasMusic"
    assert _lib_arg(m3u_argv) == "XmasMusic"
    assert m3u_argv[m3u_argv.index("--output-dir") + 1] == \
        "/mnt/Albums/XmasPlaylists"


def test_plex_push_honours_the_requested_library():
    mgr = _seasonal()
    (argv,) = mgr._build_steps("plex", library="XmasMusic")
    assert _lib_arg(argv) == "XmasMusic"
    assert argv[argv.index("--target") + 1] == "plex"


def test_single_profile_m3u_lands_in_that_librarys_directory():
    mgr = _seasonal()
    (argv,) = mgr._build_steps("m3u", profile="Carols", library="XmasMusic")
    assert argv[argv.index("--output") + 1] == os.path.join(
        "/mnt/Albums/XmasPlaylists", "Carols.m3u")


def test_libraries_property_lists_default_first():
    assert _seasonal().libraries == ["MainMusic", "XmasMusic"]


# ---------------------------------------------------------------------------
# Back-compat: no map configured
# ---------------------------------------------------------------------------

def test_without_a_map_the_service_behaves_as_before():
    mgr = _manager(["m3u"])
    (argv,) = mgr._build_steps("m3u")
    assert _lib_arg(argv) == "Lib"
    assert _out_dir(mgr) == "/out"


def test_without_a_map_naming_the_served_library_is_fine():
    assert _out_dir(_manager(["m3u"]), library="Lib") == "/out"


def test_without_a_map_naming_another_library_is_refused():
    mgr = _manager(["m3u"])
    with pytest.raises(ValueError, match="serves 'Lib' only"):
        mgr._build_steps("m3u", library="XmasMusic")


def test_libraries_property_without_a_map():
    assert _manager(["m3u"]).libraries == ["Lib"]


# ---------------------------------------------------------------------------
# submit() records and validates the library
# ---------------------------------------------------------------------------

def test_submit_records_library_and_output_dir():
    mgr = _seasonal()
    mgr._run_job = lambda job: None  # don't shell out
    job = mgr.submit("m3u", library="XmasMusic")
    assert job["library"] == "XmasMusic"
    assert job["output_dir"] == "/mnt/Albums/XmasPlaylists"


def test_submit_omits_output_dir_for_non_m3u_commands():
    mgr = _seasonal()
    mgr._run_job = lambda job: None
    job = mgr.submit("plex", library="XmasMusic")
    assert job["library"] == "XmasMusic"
    assert "output_dir" not in job


def test_submit_rejects_unknown_library_before_starting_a_job():
    mgr = _seasonal()
    with pytest.raises(ValueError, match="unknown library"):
        mgr.submit("m3u", library="PartyMusic")
    assert mgr.get_current() is None  # nothing was started


def test_exclude_track_ignores_library():
    # It edits a profile, not a library, so an unlisted name is not an
    # error here — there is nothing to resolve.
    mgr = _manager(["exclude-track"], library_dirs=SEASONAL)
    mgr._run_job = lambda job: None
    job = mgr.submit("exclude-track", profile="P", track={"title": "T"},
                     library="PartyMusic")
    assert "library" not in job


def test_unknown_command_still_rejected():
    mgr = _manager(["m3u"])
    with pytest.raises(ValueError):
        mgr.submit("exclude-track")  # not in allowed_commands


# ---------------------------------------------------------------------------
# Config validation must accept everything the webhook can run
# ---------------------------------------------------------------------------

def test_config_accepts_every_supported_webhook_command(tmp_path):
    """The validator and the JobManager must agree on the command set.

    They drifted once: 'exclude-track' worked in the webhook but made
    config.json fail validation, so the service refused to start.
    """
    import json
    from music_manager.core.config import _validate

    from music_manager.interfaces.webhook import JobManager

    commands = ["plex", "scan", "scan+plex", "scan+m3u", "m3u",
                "exclude-track"]
    config = {
        "active_library": 1,
        "targets": {},
        "webhook": {"host": "0.0.0.0", "port": 5588,
                    "allowed_commands": commands,
                    "token": "s3cret"},
    }
    _validate(config, tmp_path / "config.json")  # must not raise

    # And every one of them must be buildable by the job manager.
    mgr = JobManager(
        python_path="/usr/bin/python", main_path="/app/main.py",
        config_arg=[], library_name="Lib",
        allowed_commands=commands, m3u_output_dir="/out")
    for cmd in commands:
        track = ({"title": "T"} if cmd == "exclude-track" else None)
        steps = mgr._build_steps(cmd, profile="P", track=track)
        assert steps and all(isinstance(a, str) for s in steps for a in s)


def _validate_webhook_section(section, tmp_path):
    from music_manager.core.config import _validate
    _validate({"active_library": 1, "targets": {}, "webhook": section},
              tmp_path / "config.json")


def test_config_accepts_a_library_map(tmp_path):
    _validate_webhook_section(
        {"library": "MainMusic",
         "libraries": {
             "MainMusic": {"m3u_output_dir": "/mnt/Albums/Playlists"},
             "XmasMusic": {"m3u_output_dir": "/mnt/Albums/XmasPlaylists"}}},
        tmp_path)


@pytest.mark.parametrize("libraries", [
    ["MainMusic"],                                  # list, not a map
    {"MainMusic": "/mnt/Albums/Playlists"},         # bare string entry
    {"MainMusic": {}},                              # no output dir
    {"MainMusic": {"m3u_output_dir": 17}},          # wrong type
])
def test_config_rejects_a_malformed_library_map(libraries, tmp_path):
    from music_manager.core.config import ConfigError
    with pytest.raises(ConfigError, match="webhook.libraries"):
        _validate_webhook_section({"libraries": libraries}, tmp_path)


# ---------------------------------------------------------------------------
# Startup wiring: config.json -> start_server
# ---------------------------------------------------------------------------

def _run_webhook_startup(webhook_section, tmp_path, monkeypatch):
    """Invoke the `webhook` CLI command, capturing start_server's kwargs."""
    import json

    from music_manager.core import config as config_mod
    from music_manager.interfaces import cli as cli_mod
    from music_manager.interfaces import webhook as webhook_mod

    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "active_library": 1,
        "targets": {},
        "cron": {"m3u_output_dir": "/legacy"},
        "webhook": webhook_section,
    }))
    # setattr, not set_config_path, so the override is undone afterwards.
    monkeypatch.setattr(config_mod, "_config_path_override", path)

    monkeypatch.setattr(cli_mod, "_init_database", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "_get_library", lambda name: name)

    captured = {}
    monkeypatch.setattr(webhook_mod, "start_server",
                        lambda *a, **k: captured.update(args=a, kwargs=k))
    cli_mod.webhook(library=None, host=None, port=None, verbose=False)
    return captured


def test_startup_passes_the_expanded_library_map(tmp_path, monkeypatch):
    captured = _run_webhook_startup(
        {"library": "MainMusic",
         "libraries": {
             "MainMusic": {"m3u_output_dir": "/mnt/Albums/Playlists"},
             "XmasMusic": {"m3u_output_dir": "~/XmasPlaylists"}}},
        tmp_path, monkeypatch)

    dirs = captured["kwargs"]["library_dirs"]
    assert dirs["MainMusic"] == "/mnt/Albums/Playlists"
    assert dirs["XmasMusic"] == os.path.expanduser("~/XmasPlaylists")
    assert captured["args"][2] == "MainMusic"  # default library


def test_startup_without_a_map_passes_no_library_dirs(tmp_path, monkeypatch):
    captured = _run_webhook_startup({"library": "MainMusic"},
                                    tmp_path, monkeypatch)
    assert captured["kwargs"]["library_dirs"] == {}
    assert captured["args"][5] == "/legacy"  # cron m3u_output_dir


def test_startup_refuses_a_default_library_outside_the_map(tmp_path,
                                                           monkeypatch):
    # Otherwise every request that omits 'library' would 400 at runtime.
    import typer
    with pytest.raises(typer.Exit):
        _run_webhook_startup(
            {"library": "MainMusic",
             "libraries": {
                 "XmasMusic": {"m3u_output_dir": "/mnt/Albums/Xmas"}}},
            tmp_path, monkeypatch)
