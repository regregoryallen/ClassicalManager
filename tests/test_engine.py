"""Characterization tests for the playlist engine (V3-PLAN Phase 0).

Pins CURRENT behavior, including:
  - F3: work_integrity=enforce re-adds tracks carrying an explicit
    track-level EXCEPT (expansion only checks membership, not exclusions).
    This assertion is expected to FLIP in Phase 1 if decision D1 lands as
    recommended — update the test deliberately at that point.
"""

from music_manager.core.engine import (
    generate_playlist, _find_work_boundary_index, ResolvedTrack,
)

from tests.conftest import (
    make_album, make_composer, make_profile, add_sel, work_key, track_ids,
)


def _rt(track_id, work_id, n):
    """Minimal ResolvedTrack for boundary-index unit tests."""
    return ResolvedTrack(
        track_id=track_id, title=f"t{n}", relative_path=f"p/{n}.flac",
        disc_number=1, track_number=n, movement_number=None,
        duration_ms=60_000, mb_recording_id=None,
        album_id=1, album_title="A", album_key="A",
        work_id=work_id, work_name=f"w{work_id}", work_source="work_tag",
        composer_id=None, composer_name=None,
        genre=None, performer=None, conductor=None, ensemble=None,
        folder_id=1, folder_root_path="/music")


# ---------------------------------------------------------------------------
# Work integrity
# ---------------------------------------------------------------------------

def test_enforce_expands_partial_work_to_full(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 4)])
    p = make_profile(lib, work_integrity="enforce")
    add_sel(p, "track", "A/Alb1/02.flac")

    result = generate_playlist(p)
    assert {rt.track_id for rt in result.playlist} == track_ids(album)
    reasons = {rt.track_id: rt.admitted_by for rt in result.playlist}
    assert sum(1 for r in reasons.values()
               if r.startswith("work_integrity:enforce")) == 3


def test_enforce_does_not_expand_explicitly_excluded_work(lib):
    make_album(lib, "A/Alb1", [("Work One", 4)])
    p = make_profile(lib, work_integrity="enforce")
    add_sel(p, "album", "A/Alb1")
    add_sel(p, "work", work_key("A/Alb1", "Work One", 1), excluded=True)
    add_sel(p, "track", "A/Alb1/02.flac")

    result = generate_playlist(p)
    # Track-level ADD survives; the excluded work is not pulled back in.
    assert len(result.playlist) == 1


def test_enforce_readds_track_level_excepts_F3(lib):
    """F3 characterization (CURRENT behavior — flips with D1 in Phase 1).

    A track EXCEPT inside an included work is silently re-added by
    enforce-mode expansion.
    """
    album = make_album(lib, "A/Alb1", [("Work One", 4)])
    p = make_profile(lib, work_integrity="enforce")
    add_sel(p, "album", "A/Alb1")
    add_sel(p, "track", "A/Alb1/02.flac", excluded=True)

    result = generate_playlist(p)
    assert {rt.track_id for rt in result.playlist} == track_ids(album)


def test_respect_selection_emits_exactly_what_was_selected(lib):
    make_album(lib, "A/Alb1", [("Work One", 4)])
    p = make_profile(lib, work_integrity="respect_selection")
    add_sel(p, "track", "A/Alb1/02.flac")

    result = generate_playlist(p)
    assert len(result.playlist) == 1


# ---------------------------------------------------------------------------
# Stop conditions
# ---------------------------------------------------------------------------

def test_stop_condition_count(lib):
    make_album(lib, "A/Alb1", [("Work One", 5)])
    p = make_profile(lib, length_mode="count", length_value=2)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    assert result.track_count == 2


def test_stop_condition_duration_overshoots_by_one_track(lib):
    """Duration mode includes the track that crosses the target."""
    make_album(lib, "A/Alb1", [("Work One", 5)])  # 60s tracks
    p = make_profile(lib, length_mode="duration", length_value=150)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    assert result.track_count == 3
    assert result.total_duration_ms == 180_000


def test_stop_condition_all(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 5)])
    p = make_profile(lib, length_mode="all")
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    assert {rt.track_id for rt in result.playlist} == track_ids(album)


def test_empty_profile_produces_empty_playlist_F4(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib)

    result = generate_playlist(p)
    assert result.playlist == []
    assert result.track_count == 0


# ---------------------------------------------------------------------------
# Shuffle modes
# ---------------------------------------------------------------------------

def test_seeded_shuffle_is_deterministic_per_mode(lib):
    make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    make_album(lib, "A/Alb2", [("Work Three", 2), ("Work Four", 4)])

    for mode in ("track", "work", "album"):
        p = make_profile(lib, name=f"P-{mode}", shuffle_mode=mode, seed=42)
        add_sel(p, "album", "A/Alb1")
        add_sel(p, "album", "A/Alb2")

        first = [rt.track_id for rt in generate_playlist(p).playlist]
        second = [rt.track_id for rt in generate_playlist(p).playlist]
        assert first == second, f"mode={mode} not deterministic"
        assert len(first) == 11


def test_work_mode_keeps_movements_contiguous_and_ordered(lib):
    make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    p = make_profile(lib, shuffle_mode="work", seed=7)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    runs = []  # (work_id, [track_numbers]) in emission order
    for rt in result.playlist:
        if runs and runs[-1][0] == rt.work_id:
            runs[-1][1].append(rt.track_number)
        else:
            runs.append((rt.work_id, [rt.track_number]))
    assert len(runs) == 2  # each work appears exactly once, contiguously
    for _, numbers in runs:
        assert numbers == sorted(numbers)


def test_album_mode_keeps_album_in_natural_order(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    p = make_profile(lib, shuffle_mode="album", seed=7)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    assert [rt.track_number for rt in result.playlist] == [1, 2, 3, 4, 5]


def test_no_repeat_dedup_assigns_sequential_order_keys(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    p = make_profile(lib, no_repeat_tracks=True)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    assert [rt.order_key for rt in result.playlist] == [1, 2, 3]
    assert len({rt.track_id for rt in result.playlist}) == 3


# ---------------------------------------------------------------------------
# Separation constraints (smoke)
# ---------------------------------------------------------------------------

def test_separate_composers_avoids_adjacency_when_possible(lib):
    bach = make_composer(lib, "Bach")
    liszt = make_composer(lib, "Liszt")
    make_album(lib, "A/Bach", [("Bach W1", 1), ("Bach W2", 1)],
               composer=bach)
    make_album(lib, "A/Liszt", [("Liszt W1", 1), ("Liszt W2", 1)],
               composer=liszt)
    p = make_profile(lib, shuffle_mode="work", seed=3,
                     separate_composers=True)
    add_sel(p, "album", "A/Bach")
    add_sel(p, "album", "A/Liszt")

    result = generate_playlist(p)
    composers = [rt.composer_id for rt in result.playlist]
    assert len(composers) == 4
    # 2v2 with separation on: perfect alternation is always achievable.
    for a, b in zip(composers, composers[1:]):
        assert a != b


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

def test_pinned_work_lands_at_position_one(lib):
    album = make_album(lib, "A/Alb1",
                       [("Work One", 2), ("Work Two", 2), ("Work Three", 2)])
    p = make_profile(lib, shuffle_mode="work", seed=99)
    add_sel(p, "album", "A/Alb1")
    add_sel(p, "work", work_key("A/Alb1", "Work Three", 3), pin_position=1)

    result = generate_playlist(p)
    first_two = [rt.work_name for rt in result.playlist[:2]]
    assert first_two == ["Work Three", "Work Three"]
    assert len(result.playlist) == 6


def test_find_work_boundary_index():
    tracks = [_rt(1, 10, 1), _rt(2, 10, 2), _rt(3, 20, 3), _rt(4, 30, 4)]
    assert _find_work_boundary_index(tracks, 0) == 0
    assert _find_work_boundary_index(tracks, 1) == 2  # after work 10
    assert _find_work_boundary_index(tracks, 2) == 3  # after work 20
    assert _find_work_boundary_index(tracks, 99) == 4  # fewer works than asked
