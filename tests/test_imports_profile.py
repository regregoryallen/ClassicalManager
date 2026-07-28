"""v3.3 groundwork: import profiles and the auto_generated flag.

The load-bearing rule: an import profile is a REAL, user-visible profile,
but it must never count as evidence that a track is already assigned —
otherwise creating one would instantly silence Find Unused for exactly
the tracks it was created to help assign.
"""

from music_manager.core.database import (
    PlaylistProfile, ProfileSelection, Track,
)
from music_manager.core.engine import (
    assigned_track_ids, find_unused_tracks, unassigned_track_ids,
)
from music_manager.core.selection import (
    create_import_profile, load_library_index, resolve_effective_state,
    resolve_selections, user_profile_filter, visible_profile_filter,
)
from music_manager.core.viewmodel import library_tree_rows

from tests.conftest import make_album, make_profile, add_sel


def test_create_import_profile_holds_the_added_tracks(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    paths = ["A/Alb1/01.flac", "A/Alb1/03.flac"]

    profile = create_import_profile(lib, paths)

    assert profile is not None
    assert profile.auto_generated is True
    assert profile.name.startswith("Imports ")
    selected = resolve_selections(profile).track_ids
    assert len(selected) == 2


def test_no_profile_when_nothing_was_added(lib):
    assert create_import_profile(lib, []) is None
    assert create_import_profile(lib, None) is None
    assert PlaylistProfile.select().count() == 0


def test_duplicate_paths_collapse(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    profile = create_import_profile(
        lib, ["A/Alb1/01.flac", "A/Alb1/01.flac"])
    assert ProfileSelection.select().where(
        ProfileSelection.profile == profile).count() == 1


def test_same_minute_imports_do_not_collide(lib):
    from datetime import datetime
    make_album(lib, "A/Alb1", [("Work One", 2)])
    when = datetime(2026, 7, 28, 14, 30)

    first = create_import_profile(lib, ["A/Alb1/01.flac"], when=when)
    second = create_import_profile(lib, ["A/Alb1/02.flac"], when=when)

    assert first.name != second.name
    assert second.name.endswith("(2)")


# ---------------------------------------------------------------------------
# The critical interaction with Find Unused
# ---------------------------------------------------------------------------

def test_import_profile_does_not_mark_tracks_as_used(lib):
    """Without the auto_generated exclusion this returns nothing, and the
    whole imports workflow collapses."""
    album = make_album(lib, "A/Alb1", [("Work One", 3)])
    create_import_profile(
        lib, [t.relative_path for t in
              Track.select().where(Track.album == album)])

    unused_albums, unused_works, unused_tracks = find_unused_tracks(lib)
    assert unused_albums, "newly imported album must still read as unused"


def test_real_profile_does_mark_tracks_as_used(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib, name="Morning Mix")
    add_sel(p, "album", "A/Alb1")

    unused_albums, unused_works, unused_tracks = find_unused_tracks(lib)
    assert not unused_albums and not unused_works and not unused_tracks


def test_promoted_import_profile_counts_as_used(lib):
    """Clearing the flag (the rename gesture) makes it a normal profile."""
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    profile = create_import_profile(
        lib, [t.relative_path for t in
              Track.select().where(Track.album == album)])

    assert find_unused_tracks(lib)[0], "still unused while auto-generated"

    profile.auto_generated = False
    profile.name = "Kept These"
    profile.save()

    unused_albums, unused_works, unused_tracks = find_unused_tracks(lib)
    assert not (unused_albums or unused_works or unused_tracks)


# ---------------------------------------------------------------------------
# Filters must be NULL-safe for profiles predating the column
# ---------------------------------------------------------------------------

def test_filters_include_legacy_null_profiles(lib):
    """Rows created before the migration have auto_generated = NULL;
    `NOT (col = 1)` is NULL in SQL, which would drop them silently."""
    p = make_profile(lib, name="Legacy")
    PlaylistProfile.update(auto_generated=None).where(
        PlaylistProfile.id == p.id).execute()

    user_names = [x.name for x in PlaylistProfile.select().where(
        (PlaylistProfile.library == lib) & user_profile_filter())]
    assert "Legacy" in user_names


def test_visible_filter_includes_imports_but_not_internal(lib):
    make_album(lib, "A/Alb1", [("Work One", 1)])
    make_profile(lib, name="Morning Mix")
    make_profile(lib, name="__autosave__")
    create_import_profile(lib, ["A/Alb1/01.flac"])

    visible = [x.name for x in PlaylistProfile.select().where(
        (PlaylistProfile.library == lib) & visible_profile_filter())]
    assert "Morning Mix" in visible
    assert any(n.startswith("Imports ") for n in visible)
    assert "__autosave__" not in visible

    user_only = [x.name for x in PlaylistProfile.select().where(
        (PlaylistProfile.library == lib) & user_profile_filter())]
    assert "Morning Mix" in user_only
    assert not any(n.startswith("Imports ") for n in user_only)


# ---------------------------------------------------------------------------
# Library-pane scope: Entire library / Unassigned / a profile
# ---------------------------------------------------------------------------

def test_unassigned_ids_ignore_import_profiles(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2)])
    ids = {t.id for t in Track.select().where(Track.album == album)}

    assert unassigned_track_ids(lib) == ids

    create_import_profile(lib, [t.relative_path for t in
                                Track.select().where(Track.album == album)])
    assert unassigned_track_ids(lib) == ids, "imports must not count"

    p = make_profile(lib, name="Real")
    add_sel(p, "track", "A/Alb1/01.flac")
    assert len(unassigned_track_ids(lib)) == 1
    assert len(assigned_track_ids(lib)) == 1


def test_restrict_ids_narrows_the_library_tree(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    make_album(lib, "A/Alb2", [("Work Three", 2)])
    index = load_library_index(lib)
    state = resolve_effective_state(index, [])

    everything = library_tree_rows(index, state)
    assert len(everything) == 2

    keep = {index.track_id_by_path["A/Alb1/03.flac"]}
    narrowed = library_tree_rows(index, state, restrict_ids=keep)

    assert len(narrowed) == 1                     # Alb2 disappears
    (album_row,) = narrowed
    assert [w.text for w in album_row.children] == ["Work Two"]
    assert len(album_row.children[0].children) == 1
    assert album_row.values[3] == "1 trk"         # count reflects the scope


def test_empty_restrict_set_shows_nothing(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    index = load_library_index(lib)
    state = resolve_effective_state(index, [])
    assert library_tree_rows(index, state, restrict_ids=set()) == []


def test_restrict_composes_with_hide_single(lib):
    make_album(lib, "A/Alb1", [("Big", 3), ("Lone", 1)])
    index = load_library_index(lib)
    state = resolve_effective_state(index, [])

    all_ids = set(index.tracks)
    rows = library_tree_rows(index, state, hide_single=True,
                             restrict_ids=all_ids)
    (album_row,) = rows
    assert [w.text for w in album_row.children] == ["Big"]
