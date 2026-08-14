"""Phase 4 tests: pure tree-row viewmodel and the index-backed
_is_item_selected toggle helper.

The F2 regression test is the point of the phase: the playlist pane must
show what the engine will play, including ADDs inside an excluded album.
"""

from music_manager.core.selection import (
    Rule, load_library_index, resolve_effective_state,
)
from music_manager.core.viewmodel import library_tree_rows, playlist_tree_rows
from music_manager.interfaces.gui.builder_tab import BuilderTabMixin

from tests.conftest import make_album, work_key


def _rows(index, rules, fn=library_tree_rows, **kwargs):
    state = resolve_effective_state(index, rules)
    return fn(index, state, **kwargs)


def _flat(rows):
    out = []
    for r in rows:
        out.append(r)
        out.extend(_flat(r.children))
    return out


# ---------------------------------------------------------------------------
# Library pane
# ---------------------------------------------------------------------------

def test_library_rows_structure_and_tags(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    rules = [Rule("album", "A/Alb1"),
             Rule("track", "A/Alb1/01.flac", excluded=True)]
    (album_row,) = _rows(index, rules)

    assert album_row.tag == "partial"
    assert album_row.values[3] == "4 trk"
    w1, w2 = album_row.children
    assert w1.tag == "partial" and w2.tag == "included"
    t1, t2 = w1.children
    assert t1.tag == "excluded" and t2.tag == "included"
    assert t1.text.startswith("1-01:")


def test_library_rows_untouched_album_has_no_tag(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    index = load_library_index(lib)
    (album_row,) = _rows(index, [])
    assert album_row.tag == ""
    assert all(w.tag == "" for w in album_row.children)


def test_library_rows_hide_single(lib):
    make_album(lib, "A/Multi", [("Big Work", 2), ("Lone", 1)])
    make_album(lib, "A/Singles", [("S1", 1), ("S2", 1)])
    index = load_library_index(lib)

    rows = _rows(index, [], hide_single=True)
    assert [r.text for r in rows] == ["Multi"]
    assert [w.text for w in rows[0].children] == ["Big Work"]


def test_library_rows_search_text(lib):
    from music_manager.core.database import Track
    album = make_album(lib, "A/Alb1", [("Work One", 1)])
    t = Track.get(Track.album == album)
    t.performer = "Perlman"
    t.save()
    index = load_library_index(lib)

    (album_row,) = _rows(index, [])
    track_row = album_row.children[0].children[0]
    assert "Perlman" in track_row.search


# ---------------------------------------------------------------------------
# Playlist pane
# ---------------------------------------------------------------------------

def test_playlist_rows_show_adds_inside_excluded_album_F2(lib):
    """The F2 fix: engine includes these tracks, so the pane must too."""
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    rules = [Rule("album", "A/Alb1", excluded=True),
             Rule("track", "A/Alb1/03.flac")]
    rows = _rows(index, rules, fn=playlist_tree_rows)

    assert len(rows) == 1  # the excluded album still appears as container
    (album_row,) = rows
    assert [w.text for w in album_row.children] == ["Work Two"]
    (work_row,) = album_row.children
    assert [t.text for t in work_row.children] == ["1-03: Work Two - part 3"]
    assert album_row.values[3] == "1 trk"


def test_playlist_rows_respect_excepts_and_counts(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    rules = [Rule("album", "A/Alb1"),
             Rule("track", "A/Alb1/02.flac", excluded=True)]
    (album_row,) = _rows(index, rules, fn=playlist_tree_rows)
    (work_row,) = album_row.children
    assert len(work_row.children) == 2
    assert album_row.values[3] == "2 trk"


def test_playlist_rows_empty_rules_yield_no_rows_D2(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)
    assert _rows(index, [], fn=playlist_tree_rows) == []


def test_playlist_rows_mark_integrity_expanded_tracks(lib):
    """Expanded movements render with the 'integrity' tag, distinct from
    directly selected tracks (Phase 5 user-reported expectation gap)."""
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    rules = [Rule("track", "A/Alb1/02.flac")]
    state = resolve_effective_state(index, rules, work_integrity="enforce")
    (album_row,) = playlist_tree_rows(index, state)
    (work_row,) = album_row.children

    tags = {t.text.split(": ")[0]: t.tag for t in work_row.children}
    assert tags == {"1-01": "integrity", "1-02": "", "1-03": "integrity"}
    assert album_row.values[3] == "3 trk"  # counts include expansion


def test_playlist_rows_pin_decoration(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    wkey = work_key("A/Alb1", "Work Two", 2)
    rules = [Rule("album", "A/Alb1"),
             Rule("work", wkey, pin_position=3, track_paths="[]")]
    state = resolve_effective_state(index, rules)
    (album_row,) = playlist_tree_rows(index, state, pins={wkey: 3})

    by_text = {w.text: w for w in album_row.children}
    assert "[#3] Work Two" in by_text
    assert by_text["[#3] Work Two"].tag == "pinned"
    assert by_text["Work One"].tag == ""


def test_playlist_rows_hide_single_visible_tracks(lib):
    make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    index = load_library_index(lib)

    # Work Two reduced to one visible track → hidden when hide_single.
    rules = [Rule("album", "A/Alb1"),
             Rule("track", "A/Alb1/04.flac", excluded=True)]
    (album_row,) = _rows(index, rules, fn=playlist_tree_rows,
                         hide_single=True)
    assert [w.text for w in album_row.children] == ["Work One"]


# ---------------------------------------------------------------------------
# _is_item_selected (toggle-support logic, now index-backed)
# ---------------------------------------------------------------------------

class _FakeApp(BuilderTabMixin):
    """Just enough App surface to exercise the selection helpers."""

    def __init__(self, index):
        self.active_library = object()  # truthy; index is pre-seeded
        self._lib_index = index
        self._current_selections = []

    def add(self, level, key, excluded=False):
        self._current_selections.append(
            {"level": level, "key": key, "excluded": excluded,
             "pin_position": None, "track_paths": None, "display": ""})


def test_is_item_selected_matrix(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    wk1 = work_key("A/Alb1", "Work One", 1)

    app = _FakeApp(index)
    assert app._is_item_selected("track", "A/Alb1/01.flac") is False

    app.add("album", "A/Alb1")
    assert app._is_item_selected("track", "A/Alb1/01.flac") is True
    assert app._is_item_selected("work", wk1) is True
    assert app._is_item_selected("album", "A/Alb1") is True

    # Track EXCEPT wins over the album ADD (specificity).
    app.add("track", "A/Alb1/01.flac", excluded=True)
    assert app._is_item_selected("track", "A/Alb1/01.flac") is False
    assert app._is_item_selected("track", "A/Alb1/02.flac") is True

    # Work EXCEPT beats album ADD for its tracks.
    app.add("work", wk1, excluded=True)
    assert app._is_item_selected("track", "A/Alb1/02.flac") is False
    assert app._is_item_selected("work", wk1) is False

    # Unknown key falls back to direct-selection check only.
    assert app._is_item_selected("track", "Z/Missing/01.flac") is False


def test_remove_container_with_only_child_rules(lib):
    """Removing an album covered purely by child rules must clear them.

    V2 regression: with no direct album ADD, remove did nothing at all.
    """
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    wk1 = work_key("A/Alb1", "Work One", 1)

    app = _FakeApp(index)
    app.add("work", wk1)
    app.add("track", "A/Alb1/03.flac")

    app._remove_item_selection("album", "A/Alb1")
    assert app._current_selections == []  # no rules left, no stray EXCEPT


def test_remove_container_with_direct_add_and_subselections(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    app = _FakeApp(index)
    app.add("album", "A/Alb1")
    app.add("track", "A/Alb1/01.flac", excluded=True)

    app._remove_item_selection("album", "A/Alb1")
    assert app._current_selections == []


def test_remove_work_still_covered_by_album_records_except(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    wk1 = work_key("A/Alb1", "Work One", 1)

    app = _FakeApp(index)
    app.add("album", "A/Alb1")
    app.add("track", "A/Alb1/01.flac")  # redundant child add

    app._remove_item_selection("work", wk1)
    remaining = {(s["level"], s["key"], s["excluded"])
                 for s in app._current_selections}
    # Child add cleared; the album ADD stays; work is now excepted.
    assert remaining == {("album", "A/Alb1", False), ("work", wk1, True)}


def test_remove_track_covered_by_album_records_except(lib):
    make_album(lib, "A/Alb1", [("Work One", 2)])
    index = load_library_index(lib)

    app = _FakeApp(index)
    app.add("album", "A/Alb1")

    app._remove_item_selection("track", "A/Alb1/02.flac")
    remaining = {(s["level"], s["key"], s["excluded"])
                 for s in app._current_selections}
    assert ("track", "A/Alb1/02.flac", True) in remaining


def test_cascade_remove_children_uses_index(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    wk1 = work_key("A/Alb1", "Work One", 1)

    app = _FakeApp(index)
    app.add("work", wk1)
    app.add("track", "A/Alb1/01.flac", excluded=True)
    app.add("track", "A/Alb1/03.flac")  # belongs to Work Two — must survive

    app._cascade_remove_children("work", wk1)
    remaining = {(s["level"], s["key"]) for s in app._current_selections}
    assert ("track", "A/Alb1/01.flac") not in remaining
    assert ("track", "A/Alb1/03.flac") in remaining


def test_backfill_breadcrumbs_heals_work_rules(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    wk1 = work_key("A/Alb1", "Work One", 1)

    app = _FakeApp(index)
    app.add("work", wk1)                      # no breadcrumbs (Explorer-era)
    app.add("work", work_key("A/Alb1", "Ghost", 9))  # orphan — left alone
    app._backfill_breadcrumbs()

    import json as _json
    healed = next(s for s in app._current_selections if s["key"] == wk1)
    assert _json.loads(healed["track_paths"]) == [
        "A/Alb1/01.flac", "A/Alb1/02.flac"]
    ghost = next(s for s in app._current_selections if "Ghost" in s["key"])
    assert ghost["track_paths"] is None


def test_rules_strip_text(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    app = _FakeApp(index)
    assert app._rules_strip_text() == "Rules: 0 — playlist is empty"

    app.add("album", "A/Alb1")
    app.add("track", "A/Alb1/02.flac")        # redundant
    app.add("album", "Z/Missing")             # orphaned
    text = app._rules_strip_text()
    assert text.startswith("Rules: 3 ")
    assert "1 active" in text
    assert "1 redundant" in text
    assert "1 orphaned ⚠" in text
    assert text.endswith("3 trk")


# ---------------------------------------------------------------------------
# Batched bulk selection (v3.9)
#
# The bulk loops carry a _SelectionView so they stop rebuilding the same
# dicts once per item. The risk that buys is drift: a view that disagrees
# with the list it describes decides the wrong branch, and the damage is
# silent. Every test here pins the batch to the same answer the loop gives
# when it runs one item at a time, which is the un-batched path.
# ---------------------------------------------------------------------------

class _FakeTree:
    def __init__(self):
        self._sel = ()

    def selection(self):
        return self._sel


class _BulkApp(_FakeApp):
    """_FakeApp plus the surface the bulk toggle loops touch."""

    def __init__(self, index):
        super().__init__(index)
        self.builder_lib_tree = _FakeTree()
        self.builder_pl_tree = _FakeTree()
        self._builder_lib_iid_map = {}
        self._builder_pl_iid_map = {}

    # The loops call these purely to redraw; nothing here has widgets.
    def _refresh_rules_display(self):
        pass

    def _save_builder_view_state(self):
        return None

    def _restore_builder_view_state(self, state):
        pass

    def _confirm_bulk_selection(self, count, what="items", parent=None):
        return True

    def _busy(self):
        from contextlib import nullcontext
        return nullcontext()

    def load(self, entries):
        """Register iids for *entries* and return them in order."""
        iids = []
        for i, entry in enumerate(entries):
            iid = f"I{i}"
            self._builder_lib_iid_map[iid] = entry
            iids.append(iid)
        return iids

    def toggle(self, iids):
        self.builder_lib_tree._sel = tuple(iids)
        self._builder_toggle_include()

    def include(self, iids):
        self.builder_lib_tree._sel = tuple(iids)
        self._builder_include_selected()

    def state(self):
        return sorted((s["level"], s["key"], s["excluded"])
                      for s in self._current_selections)


def _entries(lib, index):
    """A mix of levels, so cascades and specificity are all exercised."""
    album = next(iter(index.albums.values()))
    wk1 = work_key("A/Alb1", "Work One", 1)
    wk2 = work_key("A/Alb1", "Work Two", 2)
    return [
        ("album", album.id, "A/Alb1"),
        ("work", index.work_id_by_key[wk1], wk1),
        ("work", index.work_id_by_key[wk2], wk2),
        ("track", index.track_id_by_path["A/Alb1/01.flac"], "A/Alb1/01.flac"),
        ("track", index.track_id_by_path["A/Alb1/03.flac"], "A/Alb1/03.flac"),
    ]


def test_batched_toggle_matches_one_at_a_time(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    entries = _entries(lib, index)

    batched = _BulkApp(index)
    iids = batched.load(entries)
    batched.toggle(iids)

    stepwise = _BulkApp(index)
    step_iids = stepwise.load(entries)
    for iid in step_iids:
        stepwise.toggle([iid])

    assert batched.state() == stepwise.state()


def test_batched_toggle_off_matches_one_at_a_time(lib):
    """The second toggle is the removal path: cascades and exclusions."""
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    entries = _entries(lib, index)

    batched = _BulkApp(index)
    iids = batched.load(entries)
    batched.toggle(iids)
    batched.toggle(iids)

    stepwise = _BulkApp(index)
    step_iids = stepwise.load(entries)
    for iid in step_iids:
        stepwise.toggle([iid])
    for iid in step_iids:
        stepwise.toggle([iid])

    assert batched.state() == stepwise.state()


def test_batched_include_matches_one_at_a_time(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    entries = _entries(lib, index)

    batched = _BulkApp(index)
    iids = batched.load(entries)
    batched.include(iids)

    stepwise = _BulkApp(index)
    step_iids = stepwise.load(entries)
    for iid in step_iids:
        stepwise.include([iid])

    assert batched.state() == stepwise.state()


def test_batched_remove_matches_one_at_a_time(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)
    entries = _entries(lib, index)

    batched = _BulkApp(index)
    iids = batched.load(entries)
    batched.include(iids)
    batched.builder_lib_tree._sel = tuple(iids)
    batched._builder_exclude_selected()

    stepwise = _BulkApp(index)
    step_iids = stepwise.load(entries)
    stepwise.include(step_iids)
    for iid in step_iids:
        stepwise.builder_lib_tree._sel = (iid,)
        stepwise._builder_exclude_selected()

    assert batched.state() == stepwise.state()


def test_bulk_toggle_rebuilds_the_maps_once(lib):
    """The point of the view: one dict build per batch, not one per item."""
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    app = _BulkApp(index)
    iids = app.load(_entries(lib, index))

    calls = []
    original = app._selection_maps
    app._selection_maps = lambda: (calls.append(1), original())[1]
    app.toggle(iids)

    assert calls == []          # the view answers every lookup in the batch


def test_bulk_selection_confirm_threshold(lib):
    """A batch under the threshold must not prompt; over it must."""
    make_album(lib, "A/Alb1", [("Work One", 1)])
    index = load_library_index(lib)

    from music_manager.interfaces.gui.app import App

    app = _FakeApp(index)
    app.root = object()
    asked = []
    app._confirm_bulk_selection = App._confirm_bulk_selection.__get__(app)
    app.BULK_CONFIRM_THRESHOLD = App.BULK_CONFIRM_THRESHOLD

    import music_manager.interfaces.gui.app as app_mod
    original = app_mod.messagebox.askyesno
    app_mod.messagebox.askyesno = lambda *a, **k: (asked.append(a), False)[1]
    try:
        assert app._confirm_bulk_selection(App.BULK_CONFIRM_THRESHOLD) is True
        assert asked == []
        assert app._confirm_bulk_selection(
            App.BULK_CONFIRM_THRESHOLD + 1) is False
        assert len(asked) == 1
    finally:
        app_mod.messagebox.askyesno = original


def test_write_profile_selections_round_trip(lib):
    """Batched inserts must store exactly what per-row creates did.

    Including the two nullable columns, which an insert_many with ragged
    dictionaries would silently drop.
    """
    from music_manager.core.database import PlaylistProfile, ProfileSelection

    make_album(lib, "A/Alb1", [("Work One", 2)])
    index = load_library_index(lib)
    app = _FakeApp(index)

    profile = PlaylistProfile.create(
        library=lib, name="batch-test", shuffle_mode="work",
        work_integrity="respect_selection", length_mode="all")

    selections = [
        {"level": "album", "key": "A/Alb1", "excluded": False,
         "pin_position": 3, "track_paths": '["A/Alb1/01.flac"]'},
        {"level": "track", "key": "A/Alb1/02.flac", "excluded": True,
         "pin_position": None, "track_paths": None},
    ]
    app._write_profile_selections(profile, selections)

    stored = sorted(
        ((s.level, s.key, s.excluded, s.pin_position, s.track_paths)
         for s in ProfileSelection.select().where(
             ProfileSelection.profile == profile)))
    assert stored == [
        ("album", "A/Alb1", False, 3, '["A/Alb1/01.flac"]'),
        ("track", "A/Alb1/02.flac", True, None, None),
    ]


def test_write_profile_selections_batches_past_500(lib):
    """The 500-row chunking must not lose or duplicate the tail."""
    from music_manager.core.database import PlaylistProfile, ProfileSelection

    make_album(lib, "A/Alb1", [("Work One", 1)])
    index = load_library_index(lib)
    app = _FakeApp(index)

    profile = PlaylistProfile.create(
        library=lib, name="chunk-test", shuffle_mode="work",
        work_integrity="respect_selection", length_mode="all")

    selections = [
        {"level": "track", "key": f"A/Alb1/{i:05d}.flac", "excluded": False,
         "pin_position": None, "track_paths": None}
        for i in range(1203)
    ]
    app._write_profile_selections(profile, selections)

    rows = list(ProfileSelection.select().where(
        ProfileSelection.profile == profile))
    assert len(rows) == 1203
    assert len({r.key for r in rows}) == 1203
