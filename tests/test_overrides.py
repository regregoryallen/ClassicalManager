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
