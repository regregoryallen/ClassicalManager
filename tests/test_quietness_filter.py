"""v3.8: the Find Similar quietness filters, and what Match % means.

The filters run in the tree rather than in the query, so a slider drag is
instant. That is a real change in where filtering happens, and it has two
consequences worth pinning: Match % has to be restated over the survivors
or it silently answers a question the user is no longer asking, and an
unmeasured track must be excluded rather than admitted.
"""

import pytest

from music_manager.core.quietness import (
    MAX_LEVEL_OFFSET_DB,
    MAX_STARTLE_LU,
    MIN_LEVEL_OFFSET_DB,
)
from music_manager.core.similarity import (
    filter_by_quietness,
    recompute_match_percentiles,
)


def result(track_id, score, startle=None, offset=None):
    """One scored candidate, shaped as find_similar returns it."""
    return {
        "track_id": track_id,
        "score": score,
        "startle_local": startle,
        "playback_offset": offset,
        "match_pct": None,
        "rank": None,
        "candidate_count": None,
    }


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_startle_filter_keeps_what_is_below_the_threshold():
    results = [result(1, 0.1, startle=4.0),
               result(2, 0.2, startle=12.0),
               result(3, 0.3, startle=22.0)]
    survivors, dropped = filter_by_quietness(results, startle_max=15.0)

    assert [r["track_id"] for r in survivors] == [1, 2]
    assert dropped["startle"] == 1
    assert dropped["startle_unmeasured"] == 0


def test_level_filter_uses_the_offset_not_the_file_loudness():
    """The axis is where a track plays relative to its work."""
    results = [result(1, 0.1, offset=-6.0),
               result(2, 0.2, offset=0.0),
               result(3, 0.3, offset=+4.0)]
    survivors, dropped = filter_by_quietness(results, level_max=0.0)

    assert [r["track_id"] for r in survivors] == [1, 2]
    assert dropped["level"] == 1


def test_a_zero_offset_passes_a_zero_threshold():
    """68.8% of the library scores exactly 0.0, so this is not an edge case.

    A standalone work plays at exactly the reference level. `<= 0.0` has
    to admit it, or the filter drops two thirds of the library one step
    earlier than the user asked.
    """
    survivors, _ = filter_by_quietness([result(1, 0.1, offset=0.0)],
                                       level_max=0.0)
    assert len(survivors) == 1


def test_unmeasured_tracks_are_excluded_and_counted_separately():
    """Not admitted — but not conflated with "too loud" either.

    An unmeasured track cannot be shown to be quiet, and the point of the
    pool is that everything in it has been checked. But "measure these"
    and "these are loud" are different problems and the status line has
    to be able to tell them apart.
    """
    results = [result(1, 0.1, startle=4.0),
               result(2, 0.2, startle=None),
               result(3, 0.3, startle=30.0)]
    survivors, dropped = filter_by_quietness(results, startle_max=15.0)

    assert [r["track_id"] for r in survivors] == [1]
    assert dropped["startle"] == 1
    assert dropped["startle_unmeasured"] == 1


def test_an_untagged_track_is_excluded_by_the_level_filter():
    """No ReplayGain means MA applies no gain, so it is not on this axis."""
    results = [result(1, 0.1, offset=0.0), result(2, 0.2, offset=None)]
    survivors, dropped = filter_by_quietness(results, level_max=0.0)

    assert [r["track_id"] for r in survivors] == [1]
    assert dropped["level_unmeasured"] == 1


def test_no_filter_keeps_everything_including_the_unmeasured():
    """With both sliders off, nothing is excluded for lack of data.

    Turning a filter on is what opts into needing the measurement.
    """
    results = [result(1, 0.1), result(2, 0.2, startle=99.0, offset=99.0)]
    survivors, dropped = filter_by_quietness(results)

    assert len(survivors) == 2
    assert not any(dropped.values())


def test_the_two_filters_compose():
    results = [result(1, 0.1, startle=4.0, offset=-3.0),
               result(2, 0.2, startle=4.0, offset=+4.0),
               result(3, 0.3, startle=30.0, offset=-3.0)]
    survivors, _ = filter_by_quietness(results, startle_max=15.0,
                                       level_max=0.0)
    assert [r["track_id"] for r in survivors] == [1]


# ---------------------------------------------------------------------------
# Match %
# ---------------------------------------------------------------------------

def test_match_percent_is_restated_over_the_survivors():
    """Filtering after scoring must not leave a stale percentile.

    Before: 5 candidates, so the third is at 50%. After a filter removes
    two, the survivors are the whole candidate set and the numbers have
    to say so, spanning 100 down to 0 again.
    """
    results = [result(i, score=i / 10.0) for i in range(1, 6)]
    recompute_match_percentiles(results)
    assert [r["match_pct"] for r in results] == [100.0, 75.0, 50.0, 25.0, 0.0]

    survivors = [results[0], results[2], results[4]]
    recompute_match_percentiles(survivors)
    assert [r["match_pct"] for r in survivors] == [100.0, 50.0, 0.0]
    assert [r["rank"] for r in survivors] == [1, 2, 3]
    assert all(r["candidate_count"] == 3 for r in survivors)


def test_recompute_orders_by_score_not_by_input_order():
    results = [result(1, 0.9), result(2, 0.1), result(3, 0.5)]
    ordered = recompute_match_percentiles(results)

    assert [r["track_id"] for r in ordered] == [2, 3, 1]
    assert ordered[0]["match_pct"] == 100.0
    assert ordered[-1]["match_pct"] == 0.0


def test_recompute_mutates_in_place_so_the_result_map_stays_valid():
    """The UI keeps iid -> result dict. Replacing the dicts would break it."""
    original = result(1, 0.1)
    ordered = recompute_match_percentiles([original])
    assert ordered[0] is original
    assert original["match_pct"] == 100.0


def test_a_single_survivor_does_not_divide_by_zero():
    survivors = recompute_match_percentiles([result(1, 0.4)])
    assert survivors[0]["match_pct"] == 100.0
    assert survivors[0]["candidate_count"] == 1


def test_an_empty_result_set_is_not_an_error():
    assert recompute_match_percentiles([]) == []
    survivors, dropped = filter_by_quietness([], startle_max=5.0)
    assert survivors == []
    assert not any(dropped.values())


# ---------------------------------------------------------------------------
# Slider ranges
# ---------------------------------------------------------------------------

def test_slider_ranges_cover_the_measured_distribution():
    """A3's 300-track sample, so the endpoints are evidence not taste.

    startle_local reached p99 +23.7 and max +30.8; the offset ran
    p5..p95 of -9.3..+2.9 with a max of +7.3.
    """
    assert MAX_STARTLE_LU >= 23.7
    assert MIN_LEVEL_OFFSET_DB <= -9.3
    assert MAX_LEVEL_OFFSET_DB >= 2.9
    # A max-level filter's useful travel is mostly below zero.
    assert MIN_LEVEL_OFFSET_DB < 0 < MAX_LEVEL_OFFSET_DB


def test_the_default_thresholds_filter_nothing():
    """Both sliders start at their maximum, so a fresh search is unchanged.

    The controls are opt-in; a user who has never touched them must see
    exactly the results v3.7 gave.
    """
    loudest = result(1, 0.1, startle=MAX_STARTLE_LU,
                     offset=MAX_LEVEL_OFFSET_DB)
    survivors, _ = filter_by_quietness([loudest],
                                       startle_max=MAX_STARTLE_LU,
                                       level_max=MAX_LEVEL_OFFSET_DB)
    assert len(survivors) == 1


# ---------------------------------------------------------------------------
# The unmeasured marker, and sorting
# ---------------------------------------------------------------------------

def test_unmeasured_cells_do_not_cost_a_column_its_numeric_sort():
    """An em dash must be held out of the sort the way a blank is.

    v3.8 renders "not measured" as "—" rather than an empty cell, so the
    absence is stated rather than merely blank. But the sort decides
    numeric-vs-alphabetical by whether every non-blank cell parses as a
    number, so one unmeasured row would have sent Startle and Level to a
    string sort — the exact fault that was already fixed for blanks.
    """
    from music_manager.interfaces.gui.treeutil import (
        UNMEASURED, _is_unsortable, numeric_sort_key,
    )

    assert _is_unsortable(UNMEASURED)
    assert _is_unsortable("")
    assert _is_unsortable("   ")
    assert not _is_unsortable("12.3")
    assert not _is_unsortable("+1.5")

    # The dash itself is not a number, which is why holding it out is
    # what keeps the rest of the column numeric.
    assert numeric_sort_key(UNMEASURED) is None
    assert numeric_sort_key("12.3") == pytest.approx(12.3)
    assert numeric_sort_key("+1.5") == pytest.approx(1.5)
    assert numeric_sort_key("-6.2") == pytest.approx(-6.2)


def test_the_level_column_format_parses_back_as_a_number():
    """The Level cell is rendered with an explicit sign; sorting must cope."""
    from music_manager.interfaces.gui.treeutil import numeric_sort_key

    for offset in (-9.3, -0.1, 0.0, 2.9, 7.3):
        assert numeric_sort_key(f"{offset:+.1f}") == pytest.approx(offset)


# ---------------------------------------------------------------------------
# The help link
# ---------------------------------------------------------------------------

def test_the_quietness_help_mark_exists_and_lands_on_the_glossary():
    """Find Similar's ? buttons jump here; a renamed section would break it.

    `_help_jump` swallows a missing mark rather than raising — sensible
    for a help window, and it means a broken link would silently do
    nothing at all. Hence a test.
    """
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:                             # pragma: no cover
        pytest.skip("no display")
    root.withdraw()
    try:
        widget = tk.Text(root)
        for tag in ("title", "h1", "h2", "bold", "body", "code", "sep"):
            widget.tag_configure(tag)
        from music_manager.interfaces.help_content import build_help_content
        build_help_content(widget)

        index = widget.index("quietness")
        line = int(index.split(".")[0])
        assert "Quietness measures" in widget.get(f"{line}.0", f"{line + 2}.0")

        # And the section really does explain the terms the UI shows.
        rest = widget.get(index, "end")
        for term in ("vs work", "Startle", "Loudest moment",
                     "Head level", "Loudness range", "Integrated loudness"):
            assert term in rest, f"help does not cover {term!r}"
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# The freeze
# ---------------------------------------------------------------------------

def test_every_dialog_raised_over_find_similar_has_a_parent():
    """A parentless messagebox froze the app after Measure quietness.

    The Find Similar popup calls grab_set(). A messagebox with no
    `parent` is parented to the root window instead, so it opens *behind*
    the grabbing Toplevel and takes the input grab for itself — invisible,
    unreachable, and holding every keystroke and click. The application
    does not crash; it simply stops responding, which is a far worse
    failure than an error dialog.

    `_accept_sim_tracks` already passed `parent=`; the v3.8 additions did
    not, and the measure-complete summary is where it bit.

    Source-level because reproducing it needs a display, a grab and a
    modal dialog nobody can dismiss — a test that would hang exactly the
    way the bug does.
    """
    import pathlib
    import re

    source = pathlib.Path(
        "music_manager/interfaces/gui/similarity_ui.py").read_text()
    # Everything from the grabbing popup onward.
    start = source.index("def _show_sim_results")

    offenders = []
    for match in re.finditer(r"messagebox\.(?:show\w+|askyesno)\(.*?\)\)?\n",
                             source[start:], re.S):
        if "parent=" not in match.group(0):
            line = source[:start + match.start()].count("\n") + 1
            offenders.append(f"line {line}: {match.group(0).strip()[:60]}")
    assert not offenders, (
        "messagebox without parent= below the grabbing popup:\n  "
        + "\n  ".join(offenders))


def test_restore_grab_tolerates_a_destroyed_window():
    """Called on teardown paths, where the owner may already be gone."""
    from music_manager.interfaces.gui.similarity_ui import SimilarityUIMixin

    # None is the no-owner case and must not raise.
    SimilarityUIMixin._restore_grab(None)

    class Gone:
        def winfo_exists(self):
            return False

        def grab_set(self):                          # pragma: no cover
            raise AssertionError("must not grab a destroyed window")

    SimilarityUIMixin._restore_grab(Gone())


def test_help_is_usable_when_opened_from_a_grabbing_window():
    """The help window is non-modal, which fails under a grab.

    Find Similar calls grab_set(). A non-modal window opened underneath a
    grab receives no events at all — the help text appeared and then
    would not scroll, and none of its navigation buttons responded.

    Unlike the messagebox freeze, this one is reproducible headlessly
    enough to assert directly: grab_current() tells us who owns input,
    and that is exactly the thing that was wrong.
    """
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:                             # pragma: no cover
        pytest.skip("no display")
    root.withdraw()
    try:
        popup = tk.Toplevel(root)
        popup.wait_visibility()
        popup.grab_set()
        assert root.grab_current() is popup

        # What _show_help now does on the way in.
        grabbed = root.grab_current()
        if grabbed is not None:
            grabbed.grab_release()

        helpwin = tk.Toplevel(root)
        helpwin.wait_visibility()
        # Nothing holds the grab, so the help window can take input.
        assert root.grab_current() in (None, "")

        # And on the way out the owner gets it back.
        helpwin.destroy()
        if grabbed is not None and grabbed.winfo_exists() \
                and grabbed.winfo_viewable():
            grabbed.grab_set()
        assert root.grab_current() is popup
    finally:
        root.destroy()


def test_closing_help_does_not_grab_a_window_that_has_gone():
    """The owner can be closed while help is still open."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:                             # pragma: no cover
        pytest.skip("no display")
    root.withdraw()
    try:
        popup = tk.Toplevel(root)
        popup.wait_visibility()
        popup.grab_set()
        grabbed = root.grab_current()
        grabbed.grab_release()

        popup.destroy()          # owner closes first
        # The restore must notice and do nothing, not raise.
        if grabbed is not None and grabbed.winfo_exists() \
                and grabbed.winfo_viewable():       # pragma: no cover
            grabbed.grab_set()
        assert root.grab_current() in (None, "")
    finally:
        root.destroy()
