"""Characterization tests for post-rescan selection reconciliation.

Covers the breadcrumb (track_paths) remapping in
selection.reconcile_selections:
  - valid keys are untouched
  - orphaned key + breadcrumbs → remapped to the majority work
  - orphaned key + no breadcrumbs → counted orphaned, row RETAINED
    (this is what the V3 Rules window will surface as status=orphaned)
  - orphaned key + all breadcrumb tracks gone → row deleted
  - remap collision with an existing selection → orphan row merged away
"""

import json

from music_manager.core.database import ProfileSelection, Work
from music_manager.core.selection import reconcile_selections, key_for_work

from tests.conftest import make_album, make_profile, add_sel, work_key


def _breadcrumbs(album_key, nums):
    return json.dumps([f"{album_key}/{n:02d}.flac" for n in nums])


def test_valid_keys_untouched(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "work", work_key("A/Alb1", "Work One", 1),
            track_paths=_breadcrumbs("A/Alb1", [1, 2, 3]))

    result = reconcile_selections(lib)
    assert result == {"remapped": 0, "orphaned": 0, "details": []}


def test_orphaned_key_remapped_via_breadcrumbs(lib):
    album = make_album(lib, "A/Alb1", [("Old Name", 3)])
    p = make_profile(lib)
    add_sel(p, "work", work_key("A/Alb1", "Old Name", 1),
            track_paths=_breadcrumbs("A/Alb1", [1, 2, 3]))

    # Simulate a rescan regrouping: the work gets a new name.
    work = album.works.first()
    work.work_name = "New Name"
    work.save()

    result = reconcile_selections(lib)
    assert result["remapped"] == 1
    assert result["orphaned"] == 0

    sel = ProfileSelection.get(ProfileSelection.profile == p)
    assert sel.key == key_for_work(Work.get_by_id(work.id))
    assert json.loads(sel.track_paths)  # breadcrumbs refreshed


def test_orphaned_without_breadcrumbs_is_kept(lib):
    """No breadcrumbs → cannot remap; row survives and is reported."""
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "work", work_key("A/Alb1", "Ghost Work", 9),
            track_paths=None)

    result = reconcile_selections(lib)
    assert result["orphaned"] == 1
    assert result["remapped"] == 0
    assert ProfileSelection.select().where(
        ProfileSelection.profile == p).count() == 1


def test_orphan_with_dead_breadcrumbs_is_deleted(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)
    add_sel(p, "work", work_key("A/Alb1", "Ghost Work", 9),
            track_paths=_breadcrumbs("Z/Gone", [1, 2]))

    result = reconcile_selections(lib)
    assert result["orphaned"] == 1
    assert ProfileSelection.select().where(
        ProfileSelection.profile == p).count() == 0


def test_remap_collision_merges_into_existing_selection(lib):
    album = make_album(lib, "A/Alb1", [("Old Name", 3)])
    p = make_profile(lib)
    add_sel(p, "work", work_key("A/Alb1", "Old Name", 1),
            track_paths=_breadcrumbs("A/Alb1", [1, 2, 3]))

    work = album.works.first()
    work.work_name = "New Name"
    work.save()
    # A selection already exists at the post-rescan key.
    add_sel(p, "work", key_for_work(work),
            track_paths=_breadcrumbs("A/Alb1", [1, 2, 3]))

    result = reconcile_selections(lib)
    assert result["remapped"] == 1
    sels = list(ProfileSelection.select().where(
        ProfileSelection.profile == p))
    assert len(sels) == 1
    assert sels[0].key == key_for_work(work)


def test_internal_profiles_are_skipped(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib, name="__autosave__")
    add_sel(p, "work", work_key("A/Alb1", "Ghost Work", 9))

    result = reconcile_selections(lib)
    assert result == {"remapped": 0, "orphaned": 0, "details": []}


def test_redetect_reconciles_work_selections(lib):
    """Regrouping rebuilds every Work, so work keys change. Without
    reconciliation a re-detect silently breaks saved playlists."""
    from music_manager.core.scanner import redetect_works
    from music_manager.core.database import Track, Work

    album = make_album(lib, "A/Alb1", [("Sym", 3)])
    # Tag data drives redetect; give the tracks a WORK tag so the rebuilt
    # work is named differently from the original.
    Track.update(work_tag="Symphony No. 1").where(
        Track.album == album).execute()

    p = make_profile(lib)
    original_key = work_key("A/Alb1", "Sym", 1)
    add_sel(p, "work", original_key,
            track_paths=_breadcrumbs("A/Alb1", [1, 2, 3]))

    result = redetect_works(lib)

    assert result["selections_remapped"] == 1
    sel = ProfileSelection.get(ProfileSelection.profile == p)
    assert sel.key != original_key
    rebuilt = Work.get(Work.album == album)
    assert sel.key == key_for_work(rebuilt)
    assert rebuilt.work_name == "Symphony No. 1"
