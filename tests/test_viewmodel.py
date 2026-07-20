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
    assert album_row.values[2] == "4 trk"
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
    assert album_row.values[2] == "1 trk"


def test_playlist_rows_respect_excepts_and_counts(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    rules = [Rule("album", "A/Alb1"),
             Rule("track", "A/Alb1/02.flac", excluded=True)]
    (album_row,) = _rows(index, rules, fn=playlist_tree_rows)
    (work_row,) = album_row.children
    assert len(work_row.children) == 2
    assert album_row.values[2] == "2 trk"


def test_playlist_rows_empty_rules_yield_no_rows_D2(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)
    assert _rows(index, [], fn=playlist_tree_rows) == []


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
