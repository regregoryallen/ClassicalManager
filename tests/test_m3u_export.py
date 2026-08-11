"""v3.7: the M3U export path.

M3USerializer had no direct test coverage — no test module imported it —
despite being the oldest output format and the one the Plex target writes
its handoff file with. These pin the behaviour that matters: the extended
header form, order, encoding, both path styles, and overwrite-in-place.

Also covers the shared profile-filename helper that `generate-all` uses to
name each file, and the M3U half of config validation.
"""

import json

import pytest

from music_manager.core.config import ConfigError, _validate
from music_manager.core.engine import ResolvedTrack
from music_manager.core.paths import (find_filename_collisions,
                                      safe_profile_filename)
from music_manager.core.serializers.m3u import M3USerializer


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


def write(playlist, output_path, **target_config):
    """Serialize to output_path and return the lines written."""
    config = {"output_path": str(output_path)}
    config.update(target_config)
    M3USerializer().serialize(playlist, config)
    return output_path.read_text(encoding="utf-8").splitlines()


def paths_in(lines):
    return [line for line in lines if not line.startswith("#")]


def base_config(**targets):
    """A minimal whole-file config that passes validation."""
    return {"active_library": 1, "targets": targets}


# --- Filenames ----------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Sleep", "Sleep"),
    ("My Sleep", "My_Sleep"),
    ("Baroque/Strings", "Baroque_Strings"),
    ("Dvořák Favourites", "Dvořák_Favourites"),
    ("Late Night / Quiet", "Late_Night___Quiet"),
])
def test_sanitizer_replaces_spaces_and_slashes(name, expected):
    assert safe_profile_filename(name) == expected


def test_collisions_are_detected_not_silently_merged():
    # generate-all would otherwise write one profile over another.
    collisions = find_filename_collisions(["My Sleep", "My/Sleep", "Other"])
    assert collisions == {"My_Sleep": ["My Sleep", "My/Sleep"]}


def test_no_collision_when_names_are_distinct():
    assert find_filename_collisions(["A", "B", "C"]) == {}


# --- The file the serializer writes -------------------------------------------

def test_extended_header_and_one_entry_per_track(tmp_path):
    tracks = [make_track(1, rel="Bach/Cantatas/01.flac"),
              make_track(2, rel="Bach/Cantatas/02.flac")]

    lines = write(tracks, tmp_path / "p.m3u")

    assert lines[0] == "#EXTM3U"
    assert len(lines) == 1 + 2 * len(tracks)
    assert lines[1] == "#EXTINF:185,J.S. Bach - Cantata BWV 82: Aria"


def test_duration_is_whole_seconds(tmp_path):
    track = make_track()
    track.duration_ms = 185_400
    lines = write([track], tmp_path / "p.m3u")
    assert lines[1].startswith("#EXTINF:185,")


def test_playlist_order_is_preserved(tmp_path):
    tracks = [make_track(n, rel=f"Bach/{n:02d}.flac", title=f"Track {n}")
              for n in (3, 1, 2)]

    lines = write(tracks, tmp_path / "p.m3u")

    displays = [ln for ln in lines if ln.startswith("#EXTINF")]
    assert [d.rsplit(": ", 1)[-1] for d in displays] == \
        ["Track 3", "Track 1", "Track 2"]


def test_written_as_utf8_without_a_bom(tmp_path):
    output = tmp_path / "p.m3u"
    write([make_track(composer="Antonín Dvořák", work="Symphony No. 9")],
          output)

    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "Antonín Dvořák".encode("utf-8") in raw


def test_regenerating_overwrites_in_place_and_does_not_append(tmp_path):
    output = tmp_path / "p.m3u"
    write([make_track(1), make_track(2)], output)
    lines = write([make_track(1)], output)

    assert list(tmp_path.glob("*.m3u")) == [output]
    assert len(lines) == 3


def test_the_output_directory_is_created_if_absent(tmp_path):
    output = tmp_path / "nested" / "deeper" / "p.m3u"
    write([make_track()], output)
    assert output.is_file()


# --- Path styles --------------------------------------------------------------

def test_absolute_is_the_default_style(tmp_path):
    lines = write([make_track(root="/music", rel="Bach/01.flac")],
                  tmp_path / "p.m3u")
    assert paths_in(lines) == ["/music/Bach/01.flac"]


def test_path_rules_rewrite_the_prefix(tmp_path):
    # How a playlist is made readable on another machine — the mount
    # prefix is rewritten rather than the paths being made relative.
    lines = write([make_track(root="/mnt/MediaLib/Albums", rel="Bach/01.flac")],
                  tmp_path / "p.m3u",
                  path_rules=[{"find": "/mnt/MediaLib",
                               "replace": "/media/MediaLib"}])
    assert paths_in(lines) == ["/media/MediaLib/Albums/Bach/01.flac"]


def test_relative_paths_are_relative_to_the_playlist(tmp_path):
    playlist_dir = tmp_path / "Albums" / "Playlists"
    track = make_track(root=str(tmp_path / "Albums"),
                       rel="Bach/Cantatas/01.flac")

    lines = write([track], playlist_dir / "p.m3u",
                  path_style="relative_to_playlist")

    assert paths_in(lines) == ["../Bach/Cantatas/01.flac"]


def test_a_track_outside_the_playlist_root_still_resolves(tmp_path):
    # The relative_to failure branch: no shared prefix, so a computed ../
    # chain rather than an absolute path.
    lines = write([make_track(root="/elsewhere", rel="Bach/01.flac")],
                  tmp_path / "Albums" / "Playlists" / "p.m3u",
                  path_style="relative_to_playlist")

    line = paths_in(lines)[0]
    assert line.startswith("../")
    assert line.endswith("/elsewhere/Bach/01.flac")


def test_relative_mode_ignores_path_rules(tmp_path):
    # Documented behaviour, and the reason config warns about the pair.
    lines = write([make_track(root=str(tmp_path), rel="Bach/01.flac")],
                  tmp_path / "p.m3u", path_style="relative_to_playlist",
                  path_rules=[{"find": str(tmp_path), "replace": "/nowhere"}])
    assert paths_in(lines) == ["Bach/01.flac"]


def test_base_path_is_no_longer_applied(tmp_path):
    # Removed in v3.7: it was inert in relative mode and was mistaken for
    # an output directory. A config still carrying it must not silently
    # change the paths written.
    lines = write([make_track(root="/music", rel="Bach/01.flac")],
                  tmp_path / "p.m3u", base_path="/media/MediaLib")
    assert paths_in(lines) == ["/music/Bach/01.flac"]


# --- Display text -------------------------------------------------------------

def test_composer_and_work_lead_the_display(tmp_path):
    lines = write([make_track(composer="Beethoven", work="Symphony No. 5",
                              title="Allegro con brio")], tmp_path / "p.m3u")
    assert lines[1] == "#EXTINF:185,Beethoven - Symphony No. 5: Allegro con brio"


def test_a_title_matching_the_work_is_not_repeated(tmp_path):
    lines = write([make_track(composer="Beethoven", work="Egmont Overture",
                              title="Egmont Overture")], tmp_path / "p.m3u")
    assert lines[1] == "#EXTINF:185,Beethoven - Egmont Overture"


def test_the_simple_template_drops_the_work(tmp_path):
    lines = write([make_track(composer="Beethoven", work="Symphony No. 5",
                              title="Allegro")], tmp_path / "p.m3u",
                  display_template="simple")
    assert lines[1] == "#EXTINF:185,Beethoven - Allegro"


# --- Config validation --------------------------------------------------------

def test_a_valid_m3u_block_is_accepted(tmp_path):
    config = base_config(m3u={"path_style": "absolute", "path_rules": []})
    assert _validate(config, tmp_path / "config.json") == []


def test_an_invalid_path_style_is_rejected(tmp_path):
    config = base_config(m3u={"path_style": "sideways"})
    with pytest.raises(ConfigError, match=r"targets\.m3u\.path_style"):
        _validate(config, tmp_path / "config.json")


def test_path_rules_with_relative_paths_warns(tmp_path):
    config = base_config(m3u={
        "path_style": "relative_to_playlist",
        "path_rules": [{"find": "/music", "replace": "/media"}]})
    warnings = _validate(config, tmp_path / "config.json")
    assert len(warnings) == 1
    assert "path_rules" in warnings[0] and "ignores them" in warnings[0]


def test_path_rules_with_absolute_paths_do_not_warn(tmp_path):
    config = base_config(m3u={
        "path_style": "absolute",
        "path_rules": [{"find": "/music", "replace": "/media"}]})
    assert _validate(config, tmp_path / "config.json") == []


def test_a_leftover_base_path_warns(tmp_path):
    # It still loads — the warning says the key does nothing now.
    config = base_config(m3u={"path_style": "absolute",
                              "base_path": "/mnt/MediaLib/Albums/Playlists"})
    warnings = _validate(config, tmp_path / "config.json")
    assert len(warnings) == 1
    assert "no longer applied" in warnings[0]


def test_an_empty_base_path_does_not_warn(tmp_path):
    config = base_config(m3u={"path_style": "absolute", "base_path": ""})
    assert _validate(config, tmp_path / "config.json") == []


def test_the_shipped_example_config_is_valid(tmp_path):
    from music_manager.core.config import PROJECT_ROOT
    example = json.loads(
        (PROJECT_ROOT / "config.example.json").read_text(encoding="utf-8"))
    assert _validate(example, tmp_path / "config.json") == []
