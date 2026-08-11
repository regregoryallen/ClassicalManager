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
    ("12.3 dB", 12.3),        # Find Similar dynamic range
    ("0.0 dB", 0.0),
    ("1 of 500", 1.0),        # Find Similar rank within the candidate pool
    ("250 of 500", 250.0),
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


def test_rank_orders_by_rank_not_as_text():
    """v3.6.3: '1 of 500' sorted as text gave 1, 10, 11, ... 2, 20."""
    cells = ["11 of 500", "1 of 500", "2 of 500", "10 of 500"]
    ordered = sorted(cells, key=numeric_sort_key)
    assert ordered == ["1 of 500", "2 of 500", "10 of 500", "11 of 500"]


def test_dynamic_range_orders_numerically():
    cells = ["9.5 dB", "12.3 dB", "10.0 dB", "8.0 dB"]
    ordered = sorted(cells, key=numeric_sort_key)
    assert ordered == ["8.0 dB", "9.5 dB", "10.0 dB", "12.3 dB"]


@pytest.mark.parametrize("cell", ["Symphony of Psalms", "1 of many", "of 5"])
def test_prose_containing_of_is_not_numeric(cell):
    assert numeric_sort_key(cell) is None
