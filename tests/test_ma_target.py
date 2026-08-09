"""v3.7: the Music Assistant export target.

MA imports playlists by scanning a directory, so the target is a thin
caller over M3USerializer — which had no direct test coverage before this
module. The cases that matter are the ones the design rests on: the output
path is derived and not supplied, paths come out relative, files are
overwritten rather than appended, and nothing in the directory is ever
deleted.
"""

import json

import pytest

from music_manager.core.config import ConfigError, _validate
from music_manager.core.engine import ResolvedTrack
from music_manager.core.paths import (find_filename_collisions,
                                      safe_profile_filename)
from music_manager.core.serializers.ma import (MATargetError,
                                               find_unwritten_files,
                                               ma_output_path,
                                               ma_target_config, push_to_ma)


# --- Helpers -----------------------------------------------------------------

def make_track(n=1, root="/music", rel="Bach/Cantatas/01.flac",
               title="Aria", work="Cantata BWV 82", composer="J.S. Bach"):
    """A ResolvedTrack with only the fields the M3U serializer reads."""
    return ResolvedTrack(
        track_id=n, title=title, relative_path=rel, disc_number=1,
        track_number=n, movement_number=None, duration_ms=185_000,
        mb_recording_id=None, album_id=1, album_title="Cantatas",
        album_key="Bach/Cantatas", work_id=1, work_name=work,
        work_source="work_tag", composer_id=1, composer_name=composer,
        genre=None, performer=None, conductor=None, ensemble=None,
        folder_id=1, folder_root_path=root, order_key=n,
    )


def ma_config(output_dir, **overrides):
    """An enabled MA target config pointing at output_dir."""
    config = {"enabled": True, "output_dir": str(output_dir)}
    config.update(overrides)
    return {"targets": {"ma": config}}


def base_config(**targets):
    """A minimal whole-file config that passes validation."""
    return {"active_library": 1, "targets": targets}


# --- Filename derivation ------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Sleep", "Sleep"),
    ("My Sleep", "My_Sleep"),
    ("Baroque/Strings", "Baroque_Strings"),
    ("Dvořák Favourites", "Dvořák_Favourites"),
    ("Late Night / Quiet", "Late_Night___Quiet"),
])
def test_sanitizer_replaces_spaces_and_slashes(name, expected):
    assert safe_profile_filename(name) == expected


def test_output_path_is_derived_from_output_dir_and_profile(tmp_path):
    config = ma_target_config(ma_config(tmp_path))
    assert ma_output_path(config, "My Sleep") == tmp_path / "My_Sleep.m3u"


def test_output_path_keeps_diacritics_and_the_m3u_extension(tmp_path):
    config = ma_target_config(ma_config(tmp_path))
    path = ma_output_path(config, "Dvořák / Late Night")
    assert path == tmp_path / "Dvořák___Late_Night.m3u"


def test_output_dir_expands_a_leading_tilde():
    config = ma_target_config(ma_config("~/Playlists"))
    assert "~" not in str(ma_output_path(config, "P"))


def test_collisions_are_detected_not_silently_merged():
    collisions = find_filename_collisions(["My Sleep", "My/Sleep", "Other"])
    assert collisions == {"My_Sleep": ["My Sleep", "My/Sleep"]}


def test_no_collision_when_names_are_distinct():
    assert find_filename_collisions(["A", "B", "C"]) == {}


# --- The enabled gate ---------------------------------------------------------

def test_disabled_target_refuses_and_names_the_config_key(tmp_path):
    config = ma_config(tmp_path)
    config["targets"]["ma"]["enabled"] = False
    with pytest.raises(MATargetError, match="targets.ma.enabled"):
        ma_target_config(config)


def test_absent_target_refuses(tmp_path):
    with pytest.raises(MATargetError):
        ma_target_config({"targets": {}})


def test_enabled_target_defaults_to_relative_paths(tmp_path):
    config = ma_target_config(ma_config(tmp_path))
    assert config["path_style"] == "relative_to_playlist"


def test_an_explicit_path_style_is_not_overridden(tmp_path):
    config = ma_target_config(ma_config(tmp_path, path_style="absolute"))
    assert config["path_style"] == "absolute"


def test_the_returned_config_is_a_copy(tmp_path):
    original = ma_config(tmp_path)
    config = ma_target_config(original)
    config["output_path"] = "/somewhere/else.m3u"
    assert "output_path" not in original["targets"]["ma"]


# --- Writing the playlist -----------------------------------------------------

def test_writes_extended_m3u_with_header_and_one_entry_per_track(tmp_path):
    playlist_dir = tmp_path / "Albums" / "Playlists"
    tracks = [make_track(1, rel="Bach/Cantatas/01.flac"),
              make_track(2, rel="Bach/Cantatas/02.flac")]

    path = push_to_ma(tracks, "Morning", ma_config(playlist_dir))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#EXTM3U"
    assert len(lines) == 1 + 2 * len(tracks)
    assert lines[1] == "#EXTINF:185,J.S. Bach - Cantata BWV 82: Aria"


def test_paths_are_relative_to_the_playlist_directory(tmp_path):
    # The playlist directory is a sibling of the album directories, which
    # is the layout MA is configured against.
    playlist_dir = tmp_path / "Albums" / "Playlists"
    track = make_track(root=str(tmp_path / "Albums"),
                       rel="Bach/Cantatas/01.flac")

    path = push_to_ma([track], "Morning", ma_config(playlist_dir))

    paths = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("#")]
    assert paths == ["../Bach/Cantatas/01.flac"]


def test_a_track_outside_the_playlist_root_still_resolves(tmp_path):
    # Exercises the relative_to failure branch: no shared prefix, so the
    # serializer falls back to a computed ../ chain rather than an
    # absolute path.
    playlist_dir = tmp_path / "Albums" / "Playlists"
    track = make_track(root="/elsewhere", rel="Bach/01.flac")

    path = push_to_ma([track], "Morning", ma_config(playlist_dir))

    line = [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if not ln.startswith("#")][0]
    assert line.startswith("../")
    assert line.endswith("/elsewhere/Bach/01.flac")


def test_absolute_path_style_emits_absolute_paths(tmp_path):
    playlist_dir = tmp_path / "Playlists"
    track = make_track(root="/music", rel="Bach/01.flac")

    path = push_to_ma([track], "Morning",
                      ma_config(playlist_dir, path_style="absolute"))

    paths = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("#")]
    assert paths == ["/music/Bach/01.flac"]


def test_playlist_order_is_preserved(tmp_path):
    tracks = [make_track(n, rel=f"Bach/{n:02d}.flac", title=f"Track {n}")
              for n in (3, 1, 2)]

    path = push_to_ma(tracks, "Ordered", ma_config(tmp_path))

    displays = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("#EXTINF")]
    assert [d.rsplit(": ", 1)[-1] for d in displays] == \
        ["Track 3", "Track 1", "Track 2"]


def test_written_as_utf8_without_a_bom(tmp_path):
    track = make_track(composer="Antonín Dvořák", work="Symphony No. 9")
    path = push_to_ma([track], "Dvořák", ma_config(tmp_path))

    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "Antonín Dvořák".encode("utf-8") in raw


def test_regenerating_overwrites_in_place_and_does_not_append(tmp_path):
    first = push_to_ma([make_track(1), make_track(2)], "Sleep",
                       ma_config(tmp_path))
    second = push_to_ma([make_track(1)], "Sleep", ma_config(tmp_path))

    assert first == second
    assert list(tmp_path.glob("*.m3u")) == [first]
    assert len(second.read_text(encoding="utf-8").splitlines()) == 3


def test_the_output_directory_is_created_if_absent(tmp_path):
    target = tmp_path / "Albums" / "Playlists"
    path = push_to_ma([make_track()], "Sleep", ma_config(target))
    assert path.parent == target and path.is_file()


def test_a_disabled_target_writes_nothing(tmp_path):
    config = ma_config(tmp_path)
    config["targets"]["ma"]["enabled"] = False
    with pytest.raises(MATargetError):
        push_to_ma([make_track()], "Sleep", config)
    assert list(tmp_path.iterdir()) == []


# --- Directory report ---------------------------------------------------------

def test_a_stale_file_is_reported(tmp_path):
    push_to_ma([make_track()], "Current", ma_config(tmp_path))
    (tmp_path / "Renamed_Away.m3u").write_text("#EXTM3U\n", encoding="utf-8")

    config = ma_target_config(ma_config(tmp_path))
    assert [p.name for p in find_unwritten_files(config, ["Current"])] == \
        ["Renamed_Away.m3u"]


def test_a_file_matching_a_current_profile_is_not_reported(tmp_path):
    push_to_ma([make_track()], "My Sleep", ma_config(tmp_path))

    config = ma_target_config(ma_config(tmp_path))
    assert find_unwritten_files(config, ["My Sleep"]) == []


def test_an_internal_profile_leftover_counts_as_unaccounted(tmp_path):
    # Internal '__' profiles are excluded from batch runs, so the caller
    # does not pass their names — their leftovers must be reported.
    (tmp_path / "__temp_something.m3u").write_text("#EXTM3U\n",
                                                   encoding="utf-8")

    config = ma_target_config(ma_config(tmp_path))
    assert [p.name for p in find_unwritten_files(config, ["Current"])] == \
        ["__temp_something.m3u"]


def test_non_playlist_files_are_ignored(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    config = ma_target_config(ma_config(tmp_path))
    assert find_unwritten_files(config, []) == []


def test_a_missing_directory_reports_nothing(tmp_path):
    config = ma_target_config(ma_config(tmp_path / "not-yet"))
    assert find_unwritten_files(config, ["Anything"]) == []


def test_reporting_deletes_nothing(tmp_path):
    push_to_ma([make_track()], "Current", ma_config(tmp_path))
    (tmp_path / "Handmade.m3u").write_text("#EXTM3U\n", encoding="utf-8")
    (tmp_path / "__temp_x.m3u").write_text("#EXTM3U\n", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())

    config = ma_target_config(ma_config(tmp_path))
    reported = find_unwritten_files(config, ["Current"])

    assert len(reported) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# --- Config validation --------------------------------------------------------

def test_a_valid_ma_block_is_accepted(tmp_path):
    config = base_config(ma={"enabled": True, "output_dir": "/mnt/Playlists"})
    assert _validate(config, tmp_path / "config.json") == []


def test_output_dir_is_required_when_enabled(tmp_path):
    config = base_config(ma={"enabled": True})
    with pytest.raises(ConfigError, match="requires 'output_dir'"):
        _validate(config, tmp_path / "config.json")


def test_output_dir_is_optional_when_disabled(tmp_path):
    config = base_config(ma={"enabled": False})
    assert _validate(config, tmp_path / "config.json") == []


def test_enabled_must_be_a_boolean(tmp_path):
    config = base_config(ma={"enabled": "yes", "output_dir": "/mnt/P"})
    with pytest.raises(ConfigError, match="must be a boolean"):
        _validate(config, tmp_path / "config.json")


def test_output_dir_must_be_a_string(tmp_path):
    config = base_config(ma={"enabled": True, "output_dir": 17})
    with pytest.raises(ConfigError, match="must be a string"):
        _validate(config, tmp_path / "config.json")


def test_an_invalid_path_style_is_rejected_with_the_ma_context(tmp_path):
    config = base_config(ma={"enabled": True, "output_dir": "/mnt/P",
                             "path_style": "sideways"})
    with pytest.raises(ConfigError, match="targets.ma.path_style"):
        _validate(config, tmp_path / "config.json")


def test_underscore_directory_warns(tmp_path):
    config = base_config(ma={"enabled": True,
                             "output_dir": "/mnt/Albums/_Playlists"})
    warnings = _validate(config, tmp_path / "config.json")
    assert len(warnings) == 1
    assert "skips those when scanning" in warnings[0]


def test_a_trailing_slash_does_not_hide_the_underscore(tmp_path):
    config = base_config(ma={"enabled": True,
                             "output_dir": "/mnt/Albums/_Playlists/"})
    assert len(_validate(config, tmp_path / "config.json")) == 1


def test_path_rules_with_relative_paths_warns(tmp_path):
    config = base_config(ma={
        "enabled": True, "output_dir": "/mnt/Albums/Playlists",
        "path_rules": [{"find": "/music", "replace": "/media"}]})
    warnings = _validate(config, tmp_path / "config.json")
    assert len(warnings) == 1
    assert "path_rules" in warnings[0] and "ignores them" in warnings[0]


def test_the_same_warning_applies_to_the_m3u_target(tmp_path):
    config = base_config(m3u={
        "path_style": "relative_to_playlist",
        "path_rules": [{"find": "/music", "replace": "/media"}]})
    warnings = _validate(config, tmp_path / "config.json")
    assert len(warnings) == 1
    assert "targets.m3u" in warnings[0]


def test_path_rules_with_absolute_paths_do_not_warn(tmp_path):
    config = base_config(m3u={
        "path_style": "absolute",
        "path_rules": [{"find": "/music", "replace": "/media"}]})
    assert _validate(config, tmp_path / "config.json") == []


def test_ma_and_m3u_are_validated_independently(tmp_path):
    # targets.m3u is invalid in a way targets.ma is not; the error must
    # name the section it came from.
    config = base_config(m3u={"path_style": "sideways"},
                         ma={"enabled": True, "output_dir": "/mnt/P"})
    with pytest.raises(ConfigError, match="targets.m3u.path_style"):
        _validate(config, tmp_path / "config.json")


def test_the_shipped_example_config_is_valid(tmp_path):
    from music_manager.core.config import PROJECT_ROOT
    example = json.loads(
        (PROJECT_ROOT / "config.example.json").read_text(encoding="utf-8"))
    assert _validate(example, tmp_path / "config.json") == []


# --- Cron and webhook accept the new modes ------------------------------------

@pytest.mark.parametrize("mode", ["ma", "scan+ma"])
def test_cron_accepts_the_ma_modes(tmp_path, mode):
    config = base_config()
    config["cron"] = {"library": "L", "mode": mode}
    assert _validate(config, tmp_path / "config.json") == []


@pytest.mark.parametrize("command", ["ma", "scan+ma"])
def test_webhook_accepts_the_ma_commands(tmp_path, command):
    config = base_config()
    config["webhook"] = {"library": "L", "allowed_commands": [command]}
    assert _validate(config, tmp_path / "config.json") == []
