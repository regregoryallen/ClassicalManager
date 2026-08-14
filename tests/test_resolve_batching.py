"""Selection resolution must not scale its query count with the profile.

`resolve_selections` expanded each selection with its own SELECT, so a
profile holding the library opened one round trip per track. Against a
local SQLite file that is invisible; against the MariaDB server this runs
on in practice it was minutes of latency, paid by Preview, Find Similar,
Measure quietness, the CLI, cron and the webhook alike.

The count is asserted rather than the wall time: timing is what made this
invisible in testing in the first place.
"""

import pytest

from music_manager.core.database import database
from music_manager.core.selection import (
    resolve_key_to_track_ids, resolve_selections,
)

from tests.conftest import add_sel, make_album, make_profile, work_key


class _CountQueries:
    """Counts statements executed inside the block."""

    def __enter__(self):
        self.count = 0
        # `database` is a DatabaseProxy and rejects attribute assignment;
        # the real connection object is what executes anything.
        self._target = getattr(database, "obj", database)
        self._original = self._target.execute_sql

        def counting(*args, **kwargs):
            self.count += 1
            return self._original(*args, **kwargs)

        self._target.execute_sql = counting
        return self

    def __exit__(self, *exc):
        self._target.execute_sql = self._original
        return False


def _album_of(lib, n_works, tracks_per_work, key="A/Alb1"):
    return make_album(lib, key,
                      [(f"Work {i}", tracks_per_work) for i in range(n_works)])


def test_track_selections_do_not_cost_a_query_each(lib):
    """The case that hurt: thousands of track-level rules."""
    _album_of(lib, n_works=1, tracks_per_work=60)

    small = make_profile(lib, name="small")
    for i in range(1, 6):
        add_sel(small, "track", f"A/Alb1/{i:02d}.flac")

    large = make_profile(lib, name="large")
    for i in range(1, 61):
        add_sel(large, "track", f"A/Alb1/{i:02d}.flac")

    with _CountQueries() as small_run:
        small_result = resolve_selections(small)
    with _CountQueries() as large_run:
        large_result = resolve_selections(large)

    assert len(small_result.track_ids) == 5
    assert len(large_result.track_ids) == 60
    # Twelve times the selections must not mean twelve times the queries.
    assert large_run.count == small_run.count


def test_work_selections_do_not_cost_a_query_each(lib):
    _album_of(lib, n_works=12, tracks_per_work=3)

    small = make_profile(lib, name="small")
    for i in range(2):
        add_sel(small, "work", work_key("A/Alb1", f"Work {i}", i + 1))

    large = make_profile(lib, name="large")
    for i in range(12):
        add_sel(large, "work", work_key("A/Alb1", f"Work {i}", i + 1))

    with _CountQueries() as small_run:
        small_result = resolve_selections(small)
    with _CountQueries() as large_run:
        large_result = resolve_selections(large)

    assert len(small_result.track_ids) == 6
    assert len(large_result.track_ids) == 36
    assert large_run.count == small_run.count


def test_album_selections_do_not_cost_a_query_each(lib):
    for n in range(6):
        make_album(lib, f"A/Alb{n}", [("Work One", 2)])

    small = make_profile(lib, name="small")
    add_sel(small, "album", "A/Alb0")

    large = make_profile(lib, name="large")
    for n in range(6):
        add_sel(large, "album", f"A/Alb{n}")

    with _CountQueries() as small_run:
        small_result = resolve_selections(small)
    with _CountQueries() as large_run:
        large_result = resolve_selections(large)

    assert len(small_result.track_ids) == 2
    assert len(large_result.track_ids) == 12
    assert large_run.count == small_run.count


# ---------------------------------------------------------------------------
# Same answers as before the batching
# ---------------------------------------------------------------------------

def test_work_key_without_a_sequence_still_matches_on_name(lib):
    """The single-key form omits the sequence filter when there is none;
    the batched form has to agree, or such rules silently expand empty.

    Compared at the expansion helpers rather than through
    `resolve_selections`, because the two genuinely differ further down:
    expansion finds the tracks, then `_decide_track` looks the selection
    up by each track's *canonical* work key — which carries a sequence —
    and a sequence-less rule matches nothing there. That predates the
    batching and is untouched by it; no rule the app writes lacks a
    sequence, since they all come from the library index.
    """
    from music_manager.core.selection import (
        COMPOSITE_SEP, _tracks_for_work_key, _tracks_for_work_keys,
    )

    _album_of(lib, n_works=2, tracks_per_work=2)
    # Three parts with the sequence left empty — parse_work_key requires
    # three, and reads an empty third as "any sequence".
    key = COMPOSITE_SEP.join(["A/Alb1", "Work 0", ""])

    single = _tracks_for_work_key(lib, key)
    assert len(single) == 2
    assert _tracks_for_work_keys(lib, [key]) == single


@pytest.mark.parametrize("level,key", [
    ("album", "Z/Nope"),
    ("work", "Z/NopeGhost1"),
    ("track", "Z/Nope/01.flac"),
])
def test_keys_that_match_nothing_resolve_empty(lib, level, key):
    _album_of(lib, n_works=1, tracks_per_work=2)
    profile = make_profile(lib)
    add_sel(profile, level, key)
    assert resolve_selections(profile).track_ids == set()


def test_batched_and_single_key_expansion_agree(lib):
    """Every level, against the helper that resolve_key_to_track_ids uses."""
    _album_of(lib, n_works=3, tracks_per_work=2)

    cases = [
        ("album", "A/Alb1"),
        ("work", work_key("A/Alb1", "Work 1", 2)),
        ("track", "A/Alb1/03.flac"),
    ]
    for level, key in cases:
        profile = make_profile(lib, name=f"p-{level}")
        add_sel(profile, level, key)
        assert (resolve_selections(profile).track_ids
                == resolve_key_to_track_ids(lib, level, key)), level


def test_chunking_boundary_is_crossed_correctly(lib):
    """More selections than one statement can carry."""
    from music_manager.core import selection as sel_mod

    _album_of(lib, n_works=1, tracks_per_work=40)
    profile = make_profile(lib)
    for i in range(1, 41):
        add_sel(profile, "track", f"A/Alb1/{i:02d}.flac")

    original = sel_mod._KEY_CHUNK
    sel_mod._KEY_CHUNK = 7          # forces six chunks with a short tail
    try:
        resolved = resolve_selections(profile).track_ids
    finally:
        sel_mod._KEY_CHUNK = original

    assert len(resolved) == 40
