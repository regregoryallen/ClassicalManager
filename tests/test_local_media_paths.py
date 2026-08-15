"""v3.10: media_access.path_rules — resolving stored paths to this machine's mount.

The library stores canonical POSIX paths from the machine that scanned it.
On another machine — a Windows install where the NAS is a drive letter — the
files live somewhere else, and playback/measurement/analysis must rewrite the
prefix. resolve_local_path does that; with no rule it is the identity, so the
scanning machine needs no configuration.

The rewrite itself (_apply_prefix_rules) is pure string work and OS-independent,
so the Windows drive-letter case is asserted there. resolve_local_path's
separator handling is OS-specific (os.sep / normpath run on the machine the
files live on), so those assertions use POSIX targets to stay host-neutral.
"""

import os
from pathlib import Path

import pytest

from music_manager.core.config import ConfigError, validate_config
from music_manager.core.paths import _apply_prefix_rules, resolve_local_path

WIN_RULE = [{"find": "/mnt/MediaLib", "replace": "M:"}]


# -- _apply_prefix_rules: pure, OS-independent --------------------------------

def test_a_prefix_rule_rewrites_to_a_windows_root():
    out = _apply_prefix_rules("/mnt/MediaLib/Bach/BWV988.flac", WIN_RULE)
    assert out == "M:/Bach/BWV988.flac"


def test_a_non_matching_rule_leaves_the_path_alone():
    out = _apply_prefix_rules("/other/place/x.flac", WIN_RULE)
    assert out == "/other/place/x.flac"


def test_no_rules_is_the_identity():
    assert _apply_prefix_rules("/mnt/MediaLib/x.flac", []) == "/mnt/MediaLib/x.flac"
    assert _apply_prefix_rules("/mnt/MediaLib/x.flac", None) == "/mnt/MediaLib/x.flac"


def test_only_a_prefix_match_fires_not_a_mid_path_one():
    # A share named MediaLibArchive must not be caught by a /mnt/MediaLib rule
    # partway through — startswith anchors at the front, which is enough here
    # because both begin at the root.
    out = _apply_prefix_rules("/srv/mnt/MediaLib/x.flac", WIN_RULE)
    assert out == "/srv/mnt/MediaLib/x.flac"


def test_rules_apply_in_order():
    rules = [{"find": "/a", "replace": "/b"}, {"find": "/b", "replace": "/c"}]
    # First rule turns /a/x into /b/x; the second then turns that into /c/x.
    assert _apply_prefix_rules("/a/x", rules) == "/c/x"


# -- resolve_local_path: joins, rewrites, normalizes --------------------------

def test_no_rule_returns_the_canonical_native_path():
    got = resolve_local_path("/mnt/MediaLib", "Bach/BWV988.flac", [])
    assert got == Path("/mnt/MediaLib/Bach/BWV988.flac")


def test_a_posix_rule_rewrites_the_root():
    got = resolve_local_path(
        "/mnt/MediaLib", "Bach/BWV988.flac",
        [{"find": "/mnt/MediaLib", "replace": "/media/nas"}])
    assert got == Path("/media/nas/Bach/BWV988.flac")


def test_a_trailing_slash_mismatch_is_collapsed():
    # Rule replace ends in a slash, find does not: the naive join would leave
    # "/media/nas//Bach". normpath must collapse the doubled separator.
    got = resolve_local_path(
        "/mnt/MediaLib", "Bach/x.flac",
        [{"find": "/mnt/MediaLib", "replace": "/media/nas/"}])
    assert got == Path("/media/nas/Bach/x.flac")
    assert f"{os.sep}{os.sep}" not in str(got)


# -- config validation --------------------------------------------------------

def _cfg(media_access):
    return {"active_library": 1, "targets": {}, "media_access": media_access}


def test_valid_media_access_rules_pass(tmp_path):
    cfg = _cfg({"path_rules": [{"find": "/mnt/MediaLib", "replace": "M:"}]})
    assert validate_config(cfg, tmp_path / "config.json") == []


def test_media_access_must_be_an_object(tmp_path):
    with pytest.raises(ConfigError, match="media_access"):
        validate_config(_cfg([]), tmp_path / "config.json")


def test_a_rule_missing_replace_is_rejected(tmp_path):
    cfg = _cfg({"path_rules": [{"find": "/mnt/MediaLib"}]})
    with pytest.raises(ConfigError, match="replace"):
        validate_config(cfg, tmp_path / "config.json")


def test_media_access_is_optional(tmp_path):
    assert validate_config(
        {"active_library": 1, "targets": {}}, tmp_path / "config.json") == []
