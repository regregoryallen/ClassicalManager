"""Tests for the V3 effective-state machinery (selection.py additions).

The critical property: `resolve_effective_state` must agree with
`resolve_selections` on every scenario — they share the per-track
decision function, and these tests hold them to it (F1/F2 fix).
"""

from music_manager.core.selection import (
    Rule, classify_selections, load_library_index,
    resolve_effective_state, resolve_selections, rules_from_profile,
)

from tests.conftest import (
    make_album, make_profile, add_sel, work_key, track_ids,
)


def _scenario(lib, selections):
    """Build a profile + Rule list from (level, key, excluded) triples."""
    p = make_profile(lib)
    for level, key, excluded in selections:
        add_sel(p, level, key, excluded=excluded)
    return p, [Rule(level=lv, key=k, excluded=exc)
               for lv, k, exc in selections]


SCENARIOS = [
    [],
    [("album", "A/Alb1", False)],
    [("album", "A/Alb1", False),
     ("work", "\x1f".join(["A/Alb1", "Work Two", "2"]), True)],
    [("album", "A/Alb1", False), ("track", "A/Alb1/02.flac", True)],
    [("album", "A/Alb1", True), ("track", "A/Alb1/03.flac", False)],
    [("album", "A/Alb1", True),
     ("work", "\x1f".join(["A/Alb1", "Work Two", "2"]), False)],
    [("work", "\x1f".join(["A/Alb1", "Work One", "1"]), True),
     ("track", "A/Alb1/02.flac", False),
     ("album", "A/Alb1", False)],
    [("album", "Z/Missing", False), ("track", "A/Alb1/99.flac", False)],
]


def test_effective_state_agrees_with_resolver_on_matrix(lib):
    make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    make_album(lib, "A/Alb2", [("Work Three", 2)])
    index = load_library_index(lib)

    for i, sels in enumerate(SCENARIOS):
        p = make_profile(lib, name=f"P{i}")
        for level, key, excluded in sels:
            add_sel(p, level, key, excluded=excluded)
        rules = rules_from_profile(p)

        engine_ids = resolve_selections(p).track_ids
        state = resolve_effective_state(index, rules)
        assert state.included_track_ids == engine_ids, \
            f"scenario {i}: display would disagree with engine"


def test_index_structure(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 1)],
                       year=1963)
    index = load_library_index(lib)

    assert set(index.albums) == {album.id}
    info = index.albums[album.id]
    assert info.year == 1963
    assert len(info.work_ids) == 2
    assert len(info.track_ids) == 3
    assert index.album_id_by_key["A/Alb1"] == album.id
    assert index.track_id_by_path["A/Alb1/01.flac"] in info.track_ids
    wid = index.work_id_by_key[work_key("A/Alb1", "Work One", 1)]
    assert index.works[wid].track_ids == sorted(
        index.works[wid].track_ids,
        key=lambda tid: index.tracks[tid].track_number)


def test_container_states(lib):
    album = make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    # Album added, one track excluded from Work One → album partial,
    # Work One partial, Work Two included.
    rules = [
        Rule("album", "A/Alb1"),
        Rule("track", "A/Alb1/01.flac", excluded=True),
    ]
    state = resolve_effective_state(index, rules)
    assert state.album_states[album.id] == "partial"
    w1 = index.work_id_by_key[work_key("A/Alb1", "Work One", 1)]
    w2 = index.work_id_by_key[work_key("A/Alb1", "Work Two", 2)]
    assert state.work_states[w1] == "partial"
    assert state.work_states[w2] == "included"
    t1 = index.track_id_by_path["A/Alb1/01.flac"]
    assert state.track_states[t1] == "excluded"

    # Every track individually added → containers show fully included
    # (the V2 "fully-covered container" fix, now structural).
    rules = [Rule("track", f"A/Alb1/{n:02d}.flac") for n in (1, 2, 3, 4)]
    state = resolve_effective_state(index, rules)
    assert state.album_states[album.id] == "included"
    assert state.work_states[w1] == "included"

    # Work excluded with nothing else → excluded; untouched album → none.
    rules = [Rule("work", work_key("A/Alb1", "Work One", 1), excluded=True)]
    state = resolve_effective_state(index, rules)
    assert state.work_states[w1] == "excluded"
    assert state.album_states[album.id] == "none"


# ---------------------------------------------------------------------------
# Rule classification
# ---------------------------------------------------------------------------

def test_classify_active_and_redundant(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    rules = [
        Rule("album", "A/Alb1"),
        Rule("track", "A/Alb1/02.flac"),  # covered by the album ADD
    ]
    by_key = {r.rule.key: r for r in classify_selections(index, rules)}
    assert by_key["A/Alb1"].status == "active"
    assert by_key["A/Alb1"].governs == 2  # tracks 1 and 3
    assert by_key["A/Alb1/02.flac"].status == "redundant"
    assert by_key["A/Alb1/02.flac"].governs == 1  # governs but changes nothing


def test_classify_noop_and_effective_excepts(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    # Album EXCEPT with no covering ADD → no_op (F5).
    only_except = [Rule("album", "A/Alb1", excluded=True)]
    (rs,) = classify_selections(index, only_except)
    assert rs.status == "no_op"

    # Track EXCEPT inside an added album → active (it removes a track).
    rules = [
        Rule("album", "A/Alb1"),
        Rule("track", "A/Alb1/02.flac", excluded=True),
    ]
    by_key = {r.rule.key: r for r in classify_selections(index, rules)}
    assert by_key["A/Alb1/02.flac"].status == "active"


def test_classify_orphaned_and_breadcrumbs(lib):
    make_album(lib, "A/Alb1", [("Work One", 3)])
    index = load_library_index(lib)

    rules = [
        Rule("album", "Z/Missing"),
        Rule("work", work_key("A/Alb1", "Work One", 1)),  # no track_paths
        Rule("work", work_key("A/Alb1", "Work One", 1),
             track_paths='["A/Alb1/01.flac"]'),
    ]
    results = classify_selections(index, rules)
    assert results[0].status == "orphaned"
    assert results[1].needs_breadcrumbs is True
    assert results[2].needs_breadcrumbs is False


def test_classify_pin_keeps_rule_active(lib):
    make_album(lib, "A/Alb1", [("Work One", 2), ("Work Two", 2)])
    index = load_library_index(lib)

    # The work ADD is membership-redundant under the album ADD, but its
    # pin still affects ordering → active.
    rules = [
        Rule("album", "A/Alb1"),
        Rule("work", work_key("A/Alb1", "Work One", 1), pin_position=1,
             track_paths="[]"),
    ]
    by_key = {r.rule.key: r for r in classify_selections(index, rules)}
    assert by_key[work_key("A/Alb1", "Work One", 1)].status == "active"


def test_classify_preserves_input_order_and_counts(lib):
    make_album(lib, "A/Alb1", [("Work One", 3), ("Work Two", 2)])
    index = load_library_index(lib)

    rules = [
        Rule("work", work_key("A/Alb1", "Work Two", 2), track_paths="[]"),
        Rule("album", "A/Alb1"),
    ]
    results = classify_selections(index, rules)
    assert [r.rule.level for r in results] == ["work", "album"]
    assert results[0].covers == 2
    assert results[1].covers == 5
