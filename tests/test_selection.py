"""Characterization tests for selection resolution (V3-PLAN Phase 0).

These pin CURRENT behavior, including known oddities flagged in the plan:
  - F2: track/work ADDs inside an album-level EXCEPT are included by the
    engine (specificity: most-specific match wins; album EXCEPT is least
    specific and never consulted for those tracks).
  - F4: empty selections resolve to an empty set (pure additive), despite
    the V2 GUI label claiming "empty = all tracks".
"""

from music_manager.core.selection import (
    COMPOSITE_SEP, key_for_work, parse_work_key, resolve_selections,
    resolve_key_to_track_ids, display_name_for_selection,
)

from tests.conftest import (
    make_album, make_profile, add_sel, work_key, track_ids,
)


def test_album_add_selects_all_tracks(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1")

    res = resolve_selections(p)
    assert res.track_ids == track_ids(album)
    assert all(v.startswith("album:") for v in res.admission_map.values())
    assert res.excluded_work_keys == set()
    assert res.excluded_track_paths == set()


def test_album_add_with_work_except(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1")
    add_sel(p, "work", work_key("A/Alb1", "Work Two", 2), excluded=True)

    res = resolve_selections(p)
    assert res.track_ids == track_ids(album, "Work One")
    assert res.excluded_work_keys == {work_key("A/Alb1", "Work Two", 2)}


def test_album_add_with_track_except(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1")
    add_sel(p, "track", "A/Alb1/02.flac", excluded=True)

    res = resolve_selections(p)
    assert len(res.track_ids) == 2
    assert res.track_ids < track_ids(album)
    assert res.excluded_track_paths == {"A/Alb1/02.flac"}


def test_track_add_inside_excluded_work(lib):
    """Specificity: a track-level ADD wins over its work's EXCEPT."""
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1")
    add_sel(p, "work", work_key("A/Alb1", "Work One", 1), excluded=True)
    add_sel(p, "track", "A/Alb1/02.flac")

    res = resolve_selections(p)
    assert len(res.track_ids) == 1
    (tid,) = res.track_ids
    assert res.admission_map[tid] == "track:A/Alb1/02.flac"


def test_track_add_inside_excluded_album_is_included_F2(lib):
    """F2 characterization: engine includes track ADDs under album EXCEPT.

    The V2 playlist tree hides these (display bug); the engine is the
    authority and this behavior is intended to survive V3.
    """
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1", excluded=True)
    add_sel(p, "track", "A/Alb1/03.flac")

    assert len(resolve_selections(p).track_ids) == 1


def test_work_add_inside_excluded_album_is_included_F2(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1", excluded=True)
    add_sel(p, "work", work_key("A/Alb1", "Work Two", 2))

    assert resolve_selections(p).track_ids == track_ids(album, "Work Two")


def test_album_except_alone_is_noop_F5(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1", excluded=True)

    assert resolve_selections(p).track_ids == set()


def test_empty_selections_yield_empty_set_F4(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)

    res = resolve_selections(p)
    assert res.track_ids == set()
    assert res.admission_map == {}
    assert res.excluded_work_keys == set()


def test_unknown_keys_resolve_to_nothing(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "album", "Z/Missing")
    add_sel(p, "work", work_key("A/Alb1", "No Such Work", 9))
    add_sel(p, "track", "A/Alb1/99.flac")

    assert resolve_selections(p).track_ids == set()


def test_resolve_key_to_track_ids_levels(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 1)])
    assert resolve_key_to_track_ids(lib, "album", "A/Alb1") == track_ids(album)
    assert resolve_key_to_track_ids(
        lib, "work", work_key("A/Alb1", "Work One", 1)
    ) == track_ids(album, "Work One")
    assert len(resolve_key_to_track_ids(lib, "track", "A/Alb1/01.flac")) == 1
    assert resolve_key_to_track_ids(lib, "bogus-level", "x") == set()


def test_work_key_round_trip(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    work = album.works.first()
    key = key_for_work(work)
    assert parse_work_key(key) == ("A/Alb1", "Work One", 1)
    assert parse_work_key("not-a-composite-key") is None


def test_display_name_fallback_for_orphaned_keys(lib):
    """Orphaned keys still render (the Rules window depends on this)."""
    assert "unknown album" in display_name_for_selection(
        lib, "album", "Z/Missing")
    assert "unknown track" in display_name_for_selection(
        lib, "track", "Z/Missing/01.flac")
    assert display_name_for_selection(
        lib, "work", work_key("Z/Missing", "Ghost Work", 1)) == "Ghost Work"
