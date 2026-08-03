"""Characterization tests for the overlay-correction system (overrides.py)."""

import json

import pytest

from music_manager.core.database import Album, Composer, Override, Track
from music_manager.core.overrides import (
    set_override, delete_override, apply_overrides,
    export_overrides, import_overrides,
)

from tests.conftest import make_album


def test_set_override_validates_scope_field_and_match_keys(lib):
    with pytest.raises(ValueError):
        set_override(lib, "track", "not_a_field", "x",
                     match_relative_path="a/b.flac")
    with pytest.raises(ValueError):
        set_override(lib, "album", "title", "x",  # track field, album scope
                     match_relative_path="a")
    with pytest.raises(ValueError):
        set_override(lib, "track", "title", "x")  # no match key at all


def test_set_override_upserts_on_same_match_key(lib):
    ov1 = set_override(lib, "track", "title", "First",
                       match_relative_path="A/Alb1/01.flac")
    ov2 = set_override(lib, "track", "title", "Second",
                       match_relative_path="A/Alb1/01.flac")
    assert ov1.id == ov2.id
    assert Override.select().count() == 1
    assert Override.get_by_id(ov1.id).value == "Second"


def test_apply_track_overrides(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    set_override(lib, "track", "title", "Corrected Title",
                 match_relative_path="A/Alb1/01.flac")
    set_override(lib, "track", "composer", "Antonín Dvořák",
                 match_relative_path="A/Alb1/02.flac")

    counts = apply_overrides(lib)
    assert counts["tracks_updated"] == 2
    assert counts["skipped"] == 0

    t1 = Track.get(Track.relative_path == "A/Alb1/01.flac")
    assert t1.title == "Corrected Title"
    t2 = Track.get(Track.relative_path == "A/Alb1/02.flac")
    assert t2.composer.name == "Antonín Dvořák"
    # Composer created via normalization machinery
    assert Composer.select().where(Composer.library == lib).count() == 1


def test_apply_album_override_by_album_key(lib):
    make_album(lib, "A/Alb1", [("Work One", 1)])
    set_override(lib, "album", "year", "1963",
                 match_relative_path="A/Alb1")

    counts = apply_overrides(lib)
    assert counts["albums_updated"] == 1
    assert Album.get(Album.album_key == "A/Alb1").year == 1963


def test_unmatched_override_is_skipped_not_fatal(lib):
    make_album(lib, "A/Alb1", [("Work One", 1)])
    set_override(lib, "track", "title", "X",
                 match_relative_path="Z/Gone/01.flac")

    counts = apply_overrides(lib)
    assert counts["skipped"] == 1
    assert counts["tracks_updated"] == 0


def test_delete_override(lib):
    ov = set_override(lib, "track", "title", "X",
                      match_relative_path="A/Alb1/01.flac")
    assert delete_override(ov.id) is True
    assert delete_override(ov.id) is False


def test_export_import_round_trip(lib, tmp_path):
    set_override(lib, "track", "title", "Corrected",
                 match_relative_path="A/Alb1/01.flac")
    set_override(lib, "album", "year", "1963",
                 match_relative_path="A/Alb1")

    out = tmp_path / "overrides.json"
    assert export_overrides(lib, out) == 2
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["count"] == 2

    # Re-import into the same library: both should be updates, no dups.
    counts = import_overrides(lib, out)
    assert counts == {"imported": 0, "updated": 2, "errors": 0}
    assert Override.select().count() == 2

    # Wipe and import fresh.
    Override.delete().execute()
    counts = import_overrides(lib, out)
    assert counts == {"imported": 2, "updated": 0, "errors": 0}
    assert Override.select().count() == 2


# ---------------------------------------------------------------------------
# v3.4: a recording is not a file
# ---------------------------------------------------------------------------
#
# A compilation reuses recordings that also sit on the original albums, so
# one MusicBrainz recording ID can cover several files. Matching on it alone
# meant a correction aimed at one file updated the row belonging to another
# album's copy, and only one of the copies could ever be reached.
# Found on "Waltzes (Prokofiev; Scottish National Orchestra, Neeme Jarvi)":
# applying a composer to all 18 tracks stored 8 overrides (2026-07-31).

def _shared_recording(lib, mbid="shared-rec-1"):
    """Two albums whose first track is the same recording."""
    a1 = make_album(lib, "A/Original", [("Work One", 2)])
    a2 = make_album(lib, "B/Compilation", [("Work One", 2)])
    for album in (a1, a2):
        t = Track.get((Track.album == album) & (Track.track_number == 1))
        t.musicbrainz_recording_id = mbid
        t.save()
    return a1, a2


def test_same_recording_on_two_albums_gets_two_overrides(lib):
    a1, a2 = _shared_recording(lib)
    t1 = Track.get((Track.album == a1) & (Track.track_number == 1))
    t2 = Track.get((Track.album == a2) & (Track.track_number == 1))

    for t in (t1, t2):
        set_override(library=lib, scope="track", field="composer",
                     value="Prokofiev", match_relative_path=t.relative_path,
                     match_mb_id=t.musicbrainz_recording_id)

    assert Override.select().where(Override.field == "composer").count() == 2
    assert {o.match_relative_path for o in Override.select()} == {
        t1.relative_path, t2.relative_path}


def test_override_on_one_copy_does_not_move_to_the_other(lib):
    """The failure that hid the bug: writing the same value everywhere looks
    harmless. A different value would have rewritten the other album."""
    a1, a2 = _shared_recording(lib)
    t1 = Track.get((Track.album == a1) & (Track.track_number == 1))
    t2 = Track.get((Track.album == a2) & (Track.track_number == 1))

    set_override(library=lib, scope="track", field="composer", value="Bach",
                 match_relative_path=t1.relative_path, match_mb_id="shared-rec-1")
    set_override(library=lib, scope="track", field="composer", value="Handel",
                 match_relative_path=t2.relative_path, match_mb_id="shared-rec-1")

    apply_overrides(lib)
    assert Track.get_by_id(t1.id).composer.name == "Bach"
    assert Track.get_by_id(t2.id).composer.name == "Handel"


def test_every_copy_is_reachable_by_apply(lib):
    a1, a2 = _shared_recording(lib)
    for album in (a1, a2):
        for t in Track.select().where(Track.album == album):
            set_override(library=lib, scope="track", field="composer",
                         value="Prokofiev", match_relative_path=t.relative_path,
                         match_mb_id=t.musicbrainz_recording_id)

    apply_overrides(lib)
    composers = [t.composer.name if t.composer else None
                 for t in Track.select().where(Track.album.in_([a1, a2]))]
    assert composers == ["Prokofiev"] * 4


def test_rename_still_carries_the_override_forward(lib):
    """The MB ID fallback exists for renames and must keep working."""
    album = make_album(lib, "A/Original", [("Work One", 1)])
    track = Track.get(Track.album == album)
    track.musicbrainz_recording_id = "rec-solo"
    track.save()
    set_override(library=lib, scope="track", field="composer", value="Bach",
                 match_relative_path=track.relative_path, match_mb_id="rec-solo")

    track.relative_path = "A/Original/01 renamed.flac"
    track.save()

    apply_overrides(lib)
    assert Track.get_by_id(track.id).composer.name == "Bach"

    # Re-setting it adopts the orphaned row and refreshes the stale path,
    # rather than accumulating a second row for the same file.
    set_override(library=lib, scope="track", field="composer", value="Handel",
                 match_relative_path=track.relative_path, match_mb_id="rec-solo")
    assert Override.select().where(Override.field == "composer").count() == 1
    assert Override.get().match_relative_path == "A/Original/01 renamed.flac"


def test_ambiguous_recording_with_missing_path_is_skipped(lib):
    """If the path is gone and the MB ID matches several tracks, there is no
    basis for choosing — skip rather than edit an arbitrary album."""
    _shared_recording(lib)
    set_override(library=lib, scope="track", field="composer", value="Bach",
                 match_relative_path="A/Gone/01.flac", match_mb_id="shared-rec-1")

    counts = apply_overrides(lib)
    assert counts["skipped"] == 1
    assert not any(t.composer for t in Track.select())
