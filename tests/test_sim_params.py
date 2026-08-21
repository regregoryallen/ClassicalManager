"""Remembered Find Similar parameters (v3.11).

The window's settings are stored in gui_prefs.json, which is hand-edited
and shared between the Linux and Windows sides through Z:. These cover
the reading end: a bad value must cost only its own field, never the
rest of the settings and never a traceback on open.
"""

import pytest

from music_manager.interfaces.gui.similarity_ui import (
    _SIM_PREFS_KEY, sim_param_defaults, sim_params_from_prefs,
    sim_params_to_prefs,
)


def _saved(**overrides):
    """A prefs dict holding a full, valid saved-parameter block."""
    params = sim_params_to_prefs(sim_param_defaults())
    params.update(overrides)
    return {_SIM_PREFS_KEY: params}


# ---------------------------------------------------------------------------
# Defaults and round-tripping
# ---------------------------------------------------------------------------

def test_no_saved_block_yields_defaults():
    assert sim_params_from_prefs({}) == sim_param_defaults()


def test_round_trip_preserves_settings():
    params = sim_param_defaults()
    params["limit"] = 120
    params["blend"] = 0.25
    params["dyn_range"] = {"on": True, "value": 12.0}
    params["weights_shown"] = True

    restored = sim_params_from_prefs({_SIM_PREFS_KEY:
                                      sim_params_to_prefs(params)})
    assert restored["limit"] == 120
    assert restored["blend"] == 0.25
    assert restored["dyn_range"] == {"on": True, "value": 12.0}
    assert restored["weights_shown"] is True


# ---------------------------------------------------------------------------
# Hostile prefs files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("garbage", ["nonsense", 42, None, []])
def test_a_non_dict_block_falls_back_to_defaults(garbage):
    assert sim_params_from_prefs({_SIM_PREFS_KEY: garbage}) \
        == sim_param_defaults()


def test_one_bad_field_does_not_discard_the_others():
    prefs = _saved(limit="not a number", blend=0.75)
    restored = sim_params_from_prefs(prefs)

    assert restored["limit"] == sim_param_defaults()["limit"]
    assert restored["blend"] == 0.75


def test_out_of_range_values_are_clamped_not_rejected():
    prefs = _saved(limit=10 ** 9, blend=17.0)
    restored = sim_params_from_prefs(prefs)

    assert restored["limit"] == 5000
    assert restored["blend"] == 1.0


def test_a_malformed_slider_entry_keeps_that_slider_default():
    prefs = _saved(startle="off please")
    restored = sim_params_from_prefs(prefs)

    assert restored["startle"] == sim_param_defaults()["startle"]


def test_nan_is_not_a_value():
    prefs = _saved(blend=float("nan"))
    assert sim_params_from_prefs(prefs)["blend"] == 0.5


# ---------------------------------------------------------------------------
# Weights, and the config.json interaction
# ---------------------------------------------------------------------------

def test_saved_weights_are_restored():
    params = sim_param_defaults()
    params["weights"] = dict(params["weights"], timbre=0.0, harmony=2.0)
    prefs = {_SIM_PREFS_KEY: sim_params_to_prefs(params)}

    restored = sim_params_from_prefs(prefs)
    assert restored["weights"]["timbre"] == 0.0
    assert restored["weights"]["harmony"] == 2.0


def test_saved_weights_are_dropped_when_config_weights_change():
    """Otherwise a config.json edit would silently never take effect.

    The saved copy records what config resolved to when it was written;
    a mismatch on load means the config has moved on and should win.
    """
    params = sim_param_defaults()
    params["weights"] = dict(params["weights"], timbre=0.0)
    stored = sim_params_to_prefs(params)
    # Simulate config.json having changed since the save.
    stored["weights_baseline"] = dict(stored["weights_baseline"], timbre=1.7)

    restored = sim_params_from_prefs({_SIM_PREFS_KEY: stored})
    assert restored["weights"] == sim_param_defaults()["weights"]


def test_weights_outside_the_slider_range_are_clamped():
    params = sim_param_defaults()
    stored = sim_params_to_prefs(params)
    stored["weights"] = dict(stored["weights"], timbre=99.0, tempo=-5.0)

    restored = sim_params_from_prefs({_SIM_PREFS_KEY: stored})
    assert restored["weights"]["timbre"] == 2.0
    assert restored["weights"]["tempo"] == 0.0


def test_the_text_filter_is_not_persisted():
    """Deliberate: see the module comment in similarity_ui.

    A restored text filter hides rows with nothing on screen saying why.
    """
    stored = sim_params_to_prefs(sim_param_defaults())
    assert "filter" not in stored
    assert "filter_var" not in stored
