"""v3.3 groundwork: import profiles and the auto_generated flag.

The load-bearing rule: an import profile is a REAL, user-visible profile,
but it must never count as evidence that a track is already assigned —
otherwise creating one would instantly silence Find Unused for exactly
the tracks it was created to help assign.
"""

from music_manager.core.database import (
    PlaylistProfile, ProfileSelection, Track,
)
from music_manager.core.engine import find_unused_tracks
from music_manager.core.selection import (
    create_import_profile, resolve_selections, user_profile_filter,
    visible_profile_filter,
)

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
