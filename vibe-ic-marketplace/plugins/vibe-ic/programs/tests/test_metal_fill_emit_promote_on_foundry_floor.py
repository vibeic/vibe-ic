"""metal_fill_emit — promote a PARTIAL fill that still clears the FOUNDRY floor.

WHAT THIS FIXES (measured, organic)
-----------------------------------
`metal_fill_config_gen` parses the sign-off deck's own coverage rule and sets
every layer's fill target to `floor + margin`. Promotion of the filled GDS used
to require `verdict == PASS`, i.e. every layer reaching that MARGINED target.

On an organic spm x gf180mcuD run, metal3 reached 0.3497 against a 0.35 target
— 0.0003 short of this plugin's own headroom and 0.0497 ABOVE the foundry's
0.30 rule. The whole fill was therefore left unpromoted and the sign-off DRC
consumed the UNFILLED GDS:

    spm.gds        (shipped)    -> klayout gf180mcu.drc: FAILURE (6 violations)
                                   M1.4 M2.4 M3.4 M4.4 M5.4 MT.3
    spm.filled.gds (discarded)  -> klayout gf180mcu.drc: SUCCESS (0 violations)

Same deck, same invocation, same design. The flow was manufacturing the exact
violations the fill exists to prevent.

These unit tests pin the DECISION LOGIC. They are not the evidence that the
change works — the organic bidirectional control above is. What they guarantee
is that the fail-closed guards cannot rot away: "the layer has a density
number" must never become the promotion condition.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metal_fill_emit as mfe  # noqa: E402


def _cfg(floor_pct=30.0):
    """A config shaped like metal_fill_config_gen's output."""
    return {
        "layers": [{"name": "metal1", "target": 0.35}],
        "_derivation": {"density_floor_pct": floor_pct,
                        "target_density": 0.35},
    }


def _res(*densities, over_max=False):
    return {"verdict": "PARTIAL",
            "layers": [{"name": "metal%d" % (i + 1),
                        "target": 0.35,
                        "density_after": d,
                        "worst_window_after": d,
                        "reached": d >= 0.35,
                        "over_max": over_max}
                       for i, d in enumerate(densities)]}


# --- the organic case, as numbers -----------------------------------------

def test_POSITIVE_the_organic_case_promotes():
    """metal3 at 0.3497 — under the 0.35 target, over the 0.30 floor."""
    got = mfe._clears_foundry_floor(
        _res(0.3575, 0.3507, 0.3497, 0.4405, 0.4480), _cfg())
    assert got is not None
    assert got["foundry_floor"] == 0.3
    assert got["worst_layer"] == "metal3"
    assert got["worst_layer_density"] == pytest.approx(0.3497)


def test_NEGATIVE_a_layer_below_the_floor_does_not_promote():
    """The organic negative control: metal3 stuck at its unfilled 0.0288."""
    assert mfe._clears_foundry_floor(
        _res(0.3575, 0.3507, 0.0288, 0.4405, 0.4480), _cfg()) is None


def test_NEGATIVE_exactly_at_the_floor_is_not_below_it():
    assert mfe._clears_foundry_floor(_res(0.30), _cfg()) is not None


def test_NEGATIVE_a_hair_under_the_floor_does_not_promote():
    assert mfe._clears_foundry_floor(_res(0.2999), _cfg()) is None


# --- fail-closed guards: "has a field" must not become the pass condition ---

def test_NEGATIVE_no_declared_floor_keeps_strict_behaviour():
    """A hand-written PDK-bridge config declares no floor. An ABSENT floor is
    not evidence that some lower number would pass."""
    cfg = {"layers": [{"name": "metal1", "target": 0.35}]}
    assert mfe._clears_foundry_floor(_res(0.3497), cfg) is None


def test_NEGATIVE_layer_without_a_measured_density_does_not_promote():
    res = {"verdict": "PARTIAL",
           "layers": [{"name": "metal1", "density_after": 0.34},
                      {"name": "metal2"}]}            # no number at all
    assert mfe._clears_foundry_floor(res, _cfg()) is None


def test_NEGATIVE_over_max_never_promotes():
    """Over the max density is its own defect — clearing the floor does not
    excuse it."""
    assert mfe._clears_foundry_floor(_res(0.96, over_max=True), _cfg()) is None


def test_NEGATIVE_empty_layer_list_does_not_promote():
    assert mfe._clears_foundry_floor({"verdict": "PARTIAL", "layers": []},
                                     _cfg()) is None


def test_NEGATIVE_worst_window_below_floor_beats_a_passing_average():
    """The rule is a coverage rule; a layer that clears it on the whole die
    while failing it in a window has not cleared it."""
    res = {"verdict": "PARTIAL",
           "layers": [{"name": "metal1", "density_after": 0.34,
                       "worst_window_after": 0.21}]}
    assert mfe._clears_foundry_floor(res, _cfg()) is None


def test_NEGATIVE_nonsense_floor_is_ignored():
    for bad in (0.0, 100.0, -5, "30", True, None):
        assert mfe._foundry_floor({"_derivation":
                                   {"density_floor_pct": bad}}) is None


# --- exit code + disclosure -------------------------------------------------

def test_partial_above_floor_exits_PASS_and_discloses(tmp_path, capsys,
                                                      monkeypatch):
    """rc must agree with what happened to the GDS: promoted -> PASS, and the
    reason is printed, never silent."""
    rep = _res(0.3497)
    rep["promoted_on_foundry_floor"] = {"foundry_floor": 0.3,
                                        "worst_layer": "metal1",
                                        "worst_layer_density": 0.3497}
    out = tmp_path / "r.json"
    monkeypatch.setattr(mfe, "run", lambda *a, **k: rep)
    rc = mfe.main([str(tmp_path), "--json", str(out)])
    assert rc == mfe.PASS
    assert "PARTIAL-ABOVE-FLOOR" in capsys.readouterr().out
    assert json.loads(out.read_text())["promoted_on_foundry_floor"]


def test_partial_below_floor_still_exits_FAIL(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(mfe, "run", lambda *a, **k: _res(0.0288))
    rc = mfe.main([str(tmp_path)])
    assert rc == mfe.FAIL
    assert "BELOW the foundry floor" in capsys.readouterr().out
