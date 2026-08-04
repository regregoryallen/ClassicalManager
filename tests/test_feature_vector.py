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
    import json
    from music_manager.core.config import ConfigError, load_config, set_config_path
    import music_manager.core.config as cfg
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_library": 1, "targets": {},
                                "similarity_weights": {"tempo": 1.0}}))
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
