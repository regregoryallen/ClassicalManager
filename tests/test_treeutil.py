"""v3.2: numeric-aware column sort key (shared by all tree views).

Extracted to a module-level pure function so it can be tested without a
Tk display. Covers the value shapes the trees render, including the
Find Similar results columns (% match, N/M agreement).
"""

import pytest

from music_manager.interfaces.gui.treeutil import numeric_sort_key


@pytest.mark.parametrize("cell, expected", [
    ("42", 42.0),
    ("3.5", 3.5),
    ("12 trk", 12.0),
    ("95%", 95.0),
    ("100%", 100.0),
    ("3:20", 200.0),          # M:SS
    ("1:02:03", 3723.0),      # H:MM:SS
    ("3/5", 0.6),             # agreement ratio
    ("5/5", 1.0),
])
def test_numeric_shapes_parse(cell, expected):
    assert numeric_sort_key(cell) == pytest.approx(expected)


@pytest.mark.parametrize("cell", ["", "Beethoven", "Op. 27", "n/a", "-"])
def test_non_numeric_returns_none(cell):
    assert numeric_sort_key(cell) is None


def test_divide_by_zero_is_none():
    assert numeric_sort_key("3/0") is None


def test_match_percentages_order_correctly():
    """The string-sort bug this guards against: '100%' < '95%' as text."""
    cells = ["95%", "100%", "9%", "40%"]
    ordered = sorted(cells, key=numeric_sort_key)
    assert ordered == ["9%", "40%", "95%", "100%"]


def test_agreement_ratios_order_by_fraction():
    cells = ["1/5", "3/5", "5/5", "2/5"]
    ordered = sorted(cells, key=numeric_sort_key)
    assert ordered == ["1/5", "2/5", "3/5", "5/5"]
