"""v3.1: thumbs-down — exclude a playing track from a profile.

The feature is one EXCEPT rule; these tests pin the identification
ladder (never guess), the rule mechanics (idempotent, converts a
conflicting ADD), and — most importantly — that the engine actually
stops playing the track afterwards, including under enforce integrity.
"""

import pytest

from music_manager.core.database import ProfileSelection, Track
from music_manager.core.engine import generate_playlist
from music_manager.core.selection import (
    AmbiguousTrack, TrackNotFound, exclude_track_from_profile, find_track,
    key_for_work,
)

from tests.conftest import make_album, make_composer, make_profile, add_sel


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------

def test_find_by_title_case_insensitive(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    track = find_track(lib, title="work one - PART 1")
    assert track.relative_path == "A/Alb1/01.flac"


def test_find_by_path_is_exact(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    assert find_track(lib, relative_path="A/Alb1/02.flac").track_number == 2
    with pytest.raises(TrackNotFound):
        find_track(lib, relative_path="A/Alb1/99.flac")


def test_ambiguous_title_refuses(lib):
    """Same title on two albums must not be guessed at."""
    make_album(lib, "A/Alb1", [("Sym", 1)])
    make_album(lib, "A/Alb2", [("Sym", 1)])
    for t in Track.select():
        t.title = "Same Title"
        t.save()

    with pytest.raises(AmbiguousTrack) as exc:
        find_track(lib, title="Same Title")
    assert len(exc.value.matches) == 2


def test_album_disambiguates(lib):
    make_album(lib, "A/Alb1", [("Sym", 1)], title="First")
    make_album(lib, "A/Alb2", [("Sym", 1)], title="Second")
    for t in Track.select():
        t.title = "Same Title"
        t.save()

    track = find_track(lib, title="Same Title", album="Second")
    assert track.album.title == "Second"


def test_artist_disambiguates(lib):
    make_album(lib, "A/Alb1", [("Sym", 1)])
    make_album(lib, "A/Alb2", [("Sym", 1)])
    tracks = list(Track.select())
    for t in tracks:
        t.title = "Same Title"
        t.save()
    tracks[1].performer = "Hilary Hahn"
    tracks[1].save()

    found = find_track(lib, title="Same Title", artist="hilary hahn")
    assert found.id == tracks[1].id


def test_missing_title_and_path_errors(lib):
    with pytest.raises(TrackNotFound):
        find_track(lib)


def test_unknown_title_errors(lib):
    make_album(lib, "A/Alb1", [("Work One", 1)])
    with pytest.raises(TrackNotFound):
        find_track(lib, title="Nonexistent")


# ---------------------------------------------------------------------------
# Rule mechanics
# ---------------------------------------------------------------------------

def test_exclude_creates_rule_and_is_idempotent(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1")
    track = find_track(lib, relative_path="A/Alb1/02.flac")

    first = exclude_track_from_profile(p, track)
    assert first["action"] == "excluded"

    second = exclude_track_from_profile(p, track)
    assert second["action"] == "already_excluded"

    rules = ProfileSelection.select().where(
        (ProfileSelection.profile == p)
        & (ProfileSelection.level == "track"))
    assert rules.count() == 1  # unique index respected, no duplicate


def test_exclude_converts_a_conflicting_add(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "track", "A/Alb1/02.flac")  # explicitly added
    track = find_track(lib, relative_path="A/Alb1/02.flac")

    result = exclude_track_from_profile(p, track)
    assert result["action"] == "converted_add_to_exclude"
    row = ProfileSelection.get(
        (ProfileSelection.profile == p)
        & (ProfileSelection.key == "A/Alb1/02.flac"))
    assert row.excluded is True


def test_exclude_work_scope(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    p = make_profile(lib)
    add_sel(p, "album", "A/Alb1")
    track = find_track(lib, relative_path="A/Alb1/01.flac")

    result = exclude_track_from_profile(p, track, scope="work")
    assert result["level"] == "work"
    assert result["key"] == key_for_work(album.works.first())

    played = {rt.relative_path for rt in generate_playlist(p).playlist}
    assert played == {"A/Alb1/03.flac", "A/Alb1/04.flac"}


def test_invalid_scope_rejected(lib):
    make_album(lib, "A/Alb1", [("Work One", 1)])
    p = make_profile(lib)
    track = find_track(lib, relative_path="A/Alb1/01.flac")
    with pytest.raises(ValueError):
        exclude_track_from_profile(p, track, scope="album")


# ---------------------------------------------------------------------------
# End-to-end: the track actually stops playing
# ---------------------------------------------------------------------------

def test_excluded_track_disappears_from_playlist(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib, work_integrity="respect_selection")
    add_sel(p, "album", "A/Alb1")
    assert len(generate_playlist(p).playlist) == 3

    exclude_track_from_profile(
        p, find_track(lib, relative_path="A/Alb1/02.flac"))

    played = {rt.relative_path for rt in generate_playlist(p).playlist}
    assert played == {"A/Alb1/01.flac", "A/Alb1/03.flac"}


def test_exclusion_survives_enforce_integrity(lib):
    """Without D1 this would silently re-add the thumbed-down movement."""
    make_album(lib, "A/Alb1", [("Work One", 4)])
    p = make_profile(lib, work_integrity="enforce")
    add_sel(p, "album", "A/Alb1")

    exclude_track_from_profile(
        p, find_track(lib, relative_path="A/Alb1/03.flac"))

    played = {rt.relative_path for rt in generate_playlist(p).playlist}
    assert "A/Alb1/03.flac" not in played
    assert len(played) == 3
