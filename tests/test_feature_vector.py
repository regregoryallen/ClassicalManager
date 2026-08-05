"""v3.6: the grouped, weighted feature vector.

The v2 vector's group influence was an accident of column count — timbre
and register drove 74% of every comparison and loudness plus
percussiveness drove 6%, because MFCC had 13 columns and loudness had 1.
Groups are now normalised before weighting, so influence is chosen.
"""

import numpy as np
import pytest

from music_manager.core.similarity import (
    DEFAULT_GROUP_WEIGHTS, FEATURE_DIMS, FEATURE_GROUPS, FEATURE_VERSION,
    _loudness_and_range, apply_group_weights, resolve_group_weights,
)


def test_groups_tile_the_vector_exactly():
    """A gap or overlap would silently mis-weight or drop a feature."""
    covered = []
    for span in FEATURE_GROUPS.values():
        covered.extend(range(span.start, span.stop))
    assert sorted(covered) == list(range(FEATURE_DIMS))


def test_version_was_bumped_for_the_new_layout():
    """Old vectors are a different length; reusing the version would mix
    30-dim and 31-dim rows in one distance computation."""
    assert FEATURE_VERSION >= 3


# ---------------------------------------------------------------------------
# Group normalisation
# ---------------------------------------------------------------------------

def test_equal_weights_give_groups_equal_influence():
    """The bug this fixes: a 15-column group outvoting a 2-column group
    purely on column count."""
    rng = np.random.default_rng(0)
    data = rng.normal(size=(4000, FEATURE_DIMS))
    weighted = apply_group_weights(data, {g: 1.0 for g in FEATURE_GROUPS})

    a, b = weighted[::2], weighted[1::2]
    diff2 = (a - b) ** 2
    shares = {g: diff2[:, s].sum(axis=1).mean() for g, s in FEATURE_GROUPS.items()}
    total = sum(shares.values())
    for group, share in shares.items():
        assert abs(share / total - 1 / len(FEATURE_GROUPS)) < 0.05, (
            f"{group} takes {100*share/total:.0f}% of the distance")


def test_unweighted_vector_is_dominated_by_the_largest_group():
    """Characterises the old behaviour, so the fix cannot regress silently."""
    rng = np.random.default_rng(0)
    data = rng.normal(size=(4000, FEATURE_DIMS))
    diff2 = (data[::2] - data[1::2]) ** 2
    timbre = diff2[:, FEATURE_GROUPS["timbre"]].sum(axis=1).mean()
    dynamics = diff2[:, FEATURE_GROUPS["dynamics"]].sum(axis=1).mean()
    assert timbre > 5 * dynamics       # 15 columns against 2


def test_a_zero_weight_removes_a_group_entirely():
    rng = np.random.default_rng(1)
    data = rng.normal(size=(200, FEATURE_DIMS))
    weights = {g: 1.0 for g in FEATURE_GROUPS}
    weights["register"] = 0.0
    out = apply_group_weights(data, weights)
    assert np.allclose(out[:, FEATURE_GROUPS["register"]], 0.0)
    assert not np.allclose(out[:, FEATURE_GROUPS["timbre"]], 0.0)


def test_weighting_does_not_mutate_the_input():
    data = np.ones((10, FEATURE_DIMS))
    apply_group_weights(data, {g: 2.0 for g in FEATURE_GROUPS})
    assert np.all(data == 1.0)


def test_register_is_adjustable_and_defaults_below_timbre():
    """Solo cello and solo violin are close musically but not if you want
    violin specifically — so this is a dial, not a constant."""
    assert 0.0 < DEFAULT_GROUP_WEIGHTS["register"] < DEFAULT_GROUP_WEIGHTS["timbre"]
    assert resolve_group_weights({"register": 0.1})["register"] == 0.1


def test_caller_weights_win_over_config(tmp_path, monkeypatch):
    import json
    import music_manager.core.config as cfg
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_library": 1, "targets": {},
                                "similarity_weights": {"harmony": 0.9}}))
    monkeypatch.setattr(cfg, "_config_path_override", path)
    assert resolve_group_weights()["harmony"] == 0.9
    assert resolve_group_weights({"harmony": 0.2})["harmony"] == 0.2


def test_unknown_weight_group_is_rejected_by_validation(tmp_path):
    """A typo or a group renamed out from under a config must be reported,
    not silently ignored — "loudness" sounds plausible but is part of
    dynamics."""
    import json
    from music_manager.core.config import ConfigError, load_config, set_config_path
    import music_manager.core.config as cfg
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_library": 1, "targets": {},
                                "similarity_weights": {"loudness": 1.0}}))
    set_config_path(path)
    try:
        with pytest.raises(ConfigError, match="unknown similarity group"):
            load_config()
    finally:
        cfg._config_path_override = None


# ---------------------------------------------------------------------------
# Dynamic range replaces the scale-relative volatility
# ---------------------------------------------------------------------------

def test_dynamic_range_is_independent_of_level():
    """The whole point. The old CV divided by the mean, so the same music
    at a lower level scored as more dynamic — measured r = -0.39 against
    loudness on a real library."""
    rng = np.random.default_rng(2)
    rms = np.abs(rng.normal(0.2, 0.05, size=500)) + 0.01
    loud_mean, loud_range = _loudness_and_range(rms)
    quiet_mean, quiet_range = _loudness_and_range(rms / 100.0)

    assert abs(loud_range - quiet_range) < 0.01     # same shape, same range
    assert quiet_mean < loud_mean - 30              # but clearly quieter


def test_a_wider_swing_reads_as_a_wider_range():
    even = np.full(500, 0.1)
    swelling = np.concatenate([np.full(250, 0.01), np.full(250, 0.5)])
    assert _loudness_and_range(swelling)[1] > _loudness_and_range(even)[1] + 20


def test_range_ignores_a_single_outlier_frame():
    """Percentiles, not min/max: one silent frame or one crash should not
    define a track's dynamic range."""
    steady = np.full(500, 0.1)
    spiked = steady.copy(); spiked[0] = 1e-6
    assert abs(_loudness_and_range(spiked)[1] - _loudness_and_range(steady)[1]) < 1.0


def test_empty_or_silent_input_does_not_explode():
    assert _loudness_and_range(np.array([])) == (-80.0, 0.0)
    mean, rng_db = _loudness_and_range(np.zeros(100))
    assert rng_db == 0.0 and mean < -100


def test_the_filter_range_covers_real_dynamic_ranges():
    """Regression: the UI slider ran 0-1 for the old unitless ratio. Left
    at that range it would have excluded every track, since even very even
    music spans more than 1 dB — a filter that silently returns nothing."""
    from music_manager.core.similarity import MAX_DYNAMIC_RANGE_DB

    # Real tracks measured 9.8 dB (an even Dixieland number) to 23.9 dB
    # (Rhapsody in Blue). The slider has to reach past that.
    assert MAX_DYNAMIC_RANGE_DB >= 30

    # A wide but realistic swing — roughly 26 dB — must sit inside it.
    swelling = np.concatenate([np.full(250, 0.025), np.full(250, 0.5)])
    measured = _loudness_and_range(swelling)[1]
    assert 20 < measured < MAX_DYNAMIC_RANGE_DB


def test_per_track_cost_estimate_matches_the_current_extractor():
    """The estimate is shown before a long job; a stale constant from the
    previous vector would over-promise by 3x."""
    from music_manager.core.similarity import SECONDS_PER_TRACK
    assert 1.0 < SECONDS_PER_TRACK < 6.0


# ---------------------------------------------------------------------------
# Scoring: match % and blend
# ---------------------------------------------------------------------------

def test_tempo_is_its_own_group():
    """You tune pace directly, so it is not buried in a rhythm group. A
    one-column group is fine because groups are normalised by size."""
    from music_manager.core.similarity import FEATURE_GROUPS
    assert "tempo" in FEATURE_GROUPS
    span = FEATURE_GROUPS["tempo"]
    assert span.stop - span.start == 1
    assert "rhythm" not in FEATURE_GROUPS


def test_every_group_has_a_description():
    """The sliders are labelled from this; a missing entry is a blank UI."""
    from music_manager.core.similarity import (
        DEFAULT_GROUP_WEIGHTS, GROUP_DESCRIPTIONS)
    assert set(GROUP_DESCRIPTIONS) == set(DEFAULT_GROUP_WEIGHTS)
    assert all(GROUP_DESCRIPTIONS.values())


def _fake_library(monkeypatch, n=400):
    """A synthetic analysis set, so scoring is testable without audio."""
    import json
    from datetime import datetime, timezone
    from music_manager.core.database import (
        Album, Library, SourceFolder, Track)
    from music_manager.core.similarity import (
        FEATURE_DIMS, FEATURE_VERSION, TrackAnalysis, ensure_table)

    ensure_table()
    lib = Library.create(name="S")
    sf = SourceFolder.create(library=lib, root_path="/m")
    album = Album.create(library=lib, folder=sf, album_key="A", title="A")
    rng = np.random.default_rng(7)
    ids = []
    for i in range(n):
        t = Track.create(library=lib, folder=sf, album=album, title=f"t{i}",
                         relative_path=f"A/{i:04d}.flac", disc_number=1,
                         track_number=i + 1, duration_ms=1000)
        TrackAnalysis.create(
            track=t, features=json.dumps(rng.normal(size=FEATURE_DIMS).tolist()),
            volatility=10.0, analyzed_at=datetime.now(timezone.utc),
            feature_version=FEATURE_VERSION)
        ids.append(t.id)
    return ids


def test_match_percent_spans_the_range_instead_of_saturating(lib, monkeypatch):
    """The old match % compared a candidate to how tightly the seeds
    clustered. Once the seeds were more spread out than the cluster they
    were hunting, every one of 2,000 real results read 100%."""
    from music_manager.core.similarity import find_similar
    ids = _fake_library(monkeypatch)
    results = find_similar(ids[:5], limit=len(ids))

    pcts = [r["match_pct"] for r in results]
    assert max(pcts) == pytest.approx(100.0, abs=0.1)
    assert min(pcts) < 5.0, f"lowest match was {min(pcts)}; it should reach ~0"
    assert pcts == sorted(pcts, reverse=True)


def test_results_carry_their_rank(lib):
    from music_manager.core.similarity import find_similar
    ids = _fake_library(None)
    results = find_similar(ids[:5], limit=20)
    assert [r["rank"] for r in results] == list(range(1, 21))
    assert results[0]["candidate_count"] == len(ids) - 5


def test_blend_moves_between_nearest_and_all_seeds(lib):
    """blend replaces an agreement count that saturated at 0/4 in one real
    search and 464/546 in another. It now names two real aggregations."""
    from music_manager.core.similarity import find_similar
    ids = _fake_library(None)
    near = find_similar(ids[:8], limit=30, blend=0.0)
    allof = find_similar(ids[:8], limit=30, blend=1.0)

    assert near[0]["distance"] <= allof[0]["distance"]
    assert allof[0]["mean_distance"] <= near[0]["mean_distance"]
    assert [r["track_id"] for r in near] != [r["track_id"] for r in allof]


def test_weights_change_the_ranking(lib):
    from music_manager.core.similarity import find_similar
    ids = _fake_library(None)
    base = find_similar(ids[:5], limit=25)
    tuned = find_similar(ids[:5], limit=25,
                         weights={"timbre": 0.0, "tempo": 2.0})
    assert [r["track_id"] for r in base] != [r["track_id"] for r in tuned]


def test_a_zero_weight_everywhere_does_not_crash(lib):
    """A user can drag every slider to zero; that must degrade, not raise."""
    from music_manager.core.similarity import (
        DEFAULT_GROUP_WEIGHTS, find_similar)
    ids = _fake_library(None)
    results = find_similar(ids[:5], limit=10,
                           weights={g: 0.0 for g in DEFAULT_GROUP_WEIGHTS})
    assert len(results) == 10
    assert all(r["distance"] == 0.0 for r in results)


def test_silence_does_not_inflate_dynamic_range():
    """A track with a long silent passage must not report an impossible
    range. Six tracks in a real library read 150-186 dB — a ratio of 1e9 —
    because the 10th percentile landed in the digital-silence floor."""
    from music_manager.core.similarity import MAX_DYNAMIC_RANGE_DB

    music = np.abs(np.random.default_rng(3).normal(0.15, 0.04, size=400)) + 0.02
    with_silence = np.concatenate([np.zeros(120), music])

    plain = _loudness_and_range(music)[1]
    gated = _loudness_and_range(with_silence)[1]

    assert gated < MAX_DYNAMIC_RANGE_DB, f"{gated:.0f} dB is not physical"
    assert abs(gated - plain) < 3.0, (
        "silence should be ignored, not treated as the quiet end")


def test_quiet_music_is_not_mistaken_for_silence():
    """The gate is relative to the track's own peak, so a uniformly quiet
    recording keeps all of its frames."""
    quiet = np.abs(np.random.default_rng(4).normal(0.002, 0.0005, size=400)) + 1e-4
    loud = quiet * 200.0
    assert abs(_loudness_and_range(quiet)[1]
               - _loudness_and_range(loud)[1]) < 1.0


def test_an_entirely_silent_track_is_handled():
    mean, rng_db = _loudness_and_range(np.zeros(200))
    assert rng_db == 0.0 and mean < -100
