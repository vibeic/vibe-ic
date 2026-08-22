"""A PDK that states a metal-density MINIMUM ONLY could never pass this gate.

MEASURED, gf180mcuD chip path 2026-08-22, on a real die:

    metal_layer_density_check <density.klayout.log> --pdk gf180mcuD
    verdict: FAIL
    metal1 0.4381 window [0.3, null] UNCHECKED
    metal2 0.4157 window [0.3, null] UNCHECKED   ... and so for metal3/4/5
    unchecked_note: "metal layers with a density but no window are NOT a pass"

Every layer is far INSIDE the only rule the foundry wrote (>= 30 %), and every
layer was UNCHECKED, because the status line was

    if lo is None or hi is None:  -> UNCHECKED

and gf180mcuD states a minimum and NO maximum. The program's own
`windows_provenance` explains the null:

    "MEASURED ABSENCE, not an omission: this PDK states a minimum only ...
     Copying another PDK's 0.60/0.70 ceiling here would be inventing a rule
     this foundry does not state."
    corroborated by gf180mcu_fd_sc_mcu9t5v0__nom.tlef:104,155,207,259,314 --
    MINIMUMDENSITY 30.0 on Metal1..Metal5 and NO MAXIMUMDENSITY.

So it correctly refused to invent a maximum and then read its OWN refusal as
"no rule at all".

THE LEAK THIS CHANGE MUST NOT OPEN, and what the guards below are for: a bound
that is None because we FAILED TO READ the foundry's rule must STILL be
UNCHECKED.

The first draft of this fix used `win is not None` as the discriminator, and
that was WRONG and a pre-existing test caught it: a bare `(0.30, None)` handed
in by a caller is byte-identical to a `(0.30, None)` produced by a failed
extraction. The discriminator is `provenance_layers` -- the set of layers whose
window came from the curated registry, which stores the null NEXT TO the deck
lines and tech-LEF lines it read and a note saying the absence is measured. A
layer the operator overrode with `--windows` is removed from that set, so naming
a PDK on the command line cannot launder a hand-supplied one-sided window into a
foundry statement.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import metal_layer_density_check as M  # noqa: E402


def _report(tmp_path, densities, name="density.rpt"):
    """A KLayout-shaped density transcript, in the form the real deck writes."""
    # The `%` is LOAD-BEARING: `_densities_from_rpt` requires it, and a fixture
    # without it parses to {} and returns "no per-layer metal density found" —
    # which looks exactly like the defect under test. Measured, not assumed:
    #   'Metal1 ratio: 43.81\n'    -> {}
    #   'Metal1 ratio: 43.81 %\n'  -> {'metal1': 0.4381}
    # The real deck writes:
    #   '... : Metal1 ratio: 43.811811093445066 %'
    body = "".join(
        f"2026-08-20 08:26:51 +0000: Memory Usage (2018068K) : {k} ratio: {v} %\n"
        for k, v in densities.items())
    p = tmp_path / name
    p.write_text(body)
    return p


_GF180_SHAPE = {"Metal1": 43.81, "Metal2": 41.57, "Metal3": 46.85,
                "Metal4": 51.69, "Metal5": 43.86}


# --------------------------------------------------------------- the fix
def test_a_minimum_only_pdk_PASSES_when_every_layer_clears_the_minimum(tmp_path):
    """THE DEFECT. Windows stated on one side only; all densities well above."""
    rep = _report(tmp_path, _GF180_SHAPE)
    win = {f"metal{i}": (0.30, None) for i in range(1, 6)}
    res = M.check(rep, win, None, None, provenance_layers=set(win))
    assert res["verdict"] == "PASS", res
    for layer, e in res["per_layer"].items():
        assert e["status"] == "PASS", (layer, e)
        assert e["unjudged_bound"] == "maximum", (layer, e)
        assert "recorded absence" in e["unjudged_reason"]


def test_the_stated_minimum_still_BITES(tmp_path):
    """A one-sided window is a real rule on the side it states."""
    rep = _report(tmp_path, {"Metal1": 12.0, "Metal2": 41.57})
    win = {"metal1": (0.30, None), "metal2": (0.30, None)}
    res = M.check(rep, win, None, None, provenance_layers=set(win))
    assert res["verdict"] == "FAIL", res
    assert res["per_layer"]["metal1"]["status"] == "FAIL"
    assert res["per_layer"]["metal2"]["status"] == "PASS"
    assert any("metal1" in f for f in res.get("failures", [])), res


def test_a_maximum_only_pdk_is_judged_symmetrically(tmp_path):
    rep = _report(tmp_path, {"Metal1": 88.0, "Metal2": 41.0})
    win = {"metal1": (None, 0.70), "metal2": (None, 0.70)}
    res = M.check(rep, win, None, None, provenance_layers=set(win))
    assert res["per_layer"]["metal1"]["status"] == "FAIL", res
    assert res["per_layer"]["metal2"]["status"] == "PASS", res
    assert res["per_layer"]["metal2"]["unjudged_bound"] == "minimum"


# ------------------------------------------------------- THE GUARD (no-leak)
def test_GUARD_a_layer_with_NO_window_at_all_is_still_UNCHECKED(tmp_path):
    """THE LEAK THIS CHANGE MUST NOT OPEN.

    A bound missing because NOTHING supplied a window for this layer is
    ignorance, not a recorded absence. If a future edit drops the `win is not
    None` discriminator -- i.e. treats every missing bound as 'the foundry
    states none' -- this layer starts PASSING on a rule nobody ever read, and
    THIS TEST GOES RED. That is the whole point of it.
    """
    rep = _report(tmp_path, {"Metal1": 43.81})
    res = M.check(rep, {}, None, None)          # no windows, no defaults
    assert res["verdict"] == "FAIL", res
    assert res["per_layer"]["metal1"]["status"] == "UNCHECKED", res
    assert "metal1" in res.get("unchecked_layers", []), res


def test_GUARD_a_generic_default_min_with_no_stated_window_is_UNCHECKED(tmp_path):
    """The sharper form of the same leak. A generic `--default-min` gives `lo`
    a value while `hi` stays None and NO source stated a window for this layer.
    Judging it would report a verdict against a ceiling nobody has read.
    """
    rep = _report(tmp_path, {"Metal1": 43.81})
    res = M.check(rep, {}, 0.30, None)          # default-min only, no window
    assert res["verdict"] == "FAIL", res
    assert res["per_layer"]["metal1"]["status"] == "UNCHECKED", res


def test_GUARD_a_one_sided_window_with_NO_PROVENANCE_is_UNCHECKED(tmp_path):
    """★ THE CENTRAL GUARD, and the one a pre-existing test already asserted.

    A `(0.30, None)` handed in WITHOUT provenance is indistinguishable from a
    `(0.30, None)` produced by a failed extraction. It must stay UNCHECKED. If a
    future edit re-derives 'the foundry states none' from the tuple's SHAPE
    instead of from `provenance_layers`, this goes RED -- proved by running,
    not by argument: reintroducing `stated = True` turns this into a PASS.
    """
    rep = _report(tmp_path, {"Metal1": 43.81})
    res = M.check(rep, {"metal1": (0.30, None)}, None, None)   # no provenance
    assert res["verdict"] == "FAIL", res
    assert res["per_layer"]["metal1"]["status"] == "UNCHECKED", res


def test_GUARD_an_operator_override_does_not_inherit_registry_provenance(tmp_path):
    """`--windows` wins over the registry per layer, so an overridden layer is
    NOT registry-backed. Otherwise naming a PDK on the command line would
    launder a hand-supplied one-sided window into a foundry statement."""
    rep = _report(tmp_path, {"Metal1": 43.81, "Metal2": 41.57})
    pdk_windows = {"metal1": (0.30, None), "metal2": (0.30, None)}
    operator = {"metal1": (0.30, None)}                 # operator overrode metal1
    backed = set(pdk_windows) - set(operator)           # == {"metal2"}
    merged = dict(pdk_windows); merged.update(operator)
    res = M.check(rep, merged, None, None, provenance_layers=backed)
    assert res["per_layer"]["metal2"]["status"] == "PASS", res
    assert res["per_layer"]["metal1"]["status"] == "UNCHECKED", res
    assert res["verdict"] == "FAIL", res


def test_GUARD_an_empty_window_tuple_is_UNCHECKED(tmp_path):
    """A supplied window that states NEITHER bound decides nothing."""
    rep = _report(tmp_path, {"Metal1": 43.81})
    res = M.check(rep, {"metal1": (None, None)}, None, None,
                  provenance_layers={"metal1"})
    assert res["verdict"] == "FAIL", res
    assert res["per_layer"]["metal1"]["status"] == "UNCHECKED", res


# --------------------------------------------------------------- controls
def test_CONTROL_a_fully_stated_window_is_unchanged(tmp_path):
    """Two-sided windows must behave exactly as before, in both directions."""
    rep = _report(tmp_path, {"Metal1": 43.81, "Metal2": 9.0, "Metal3": 91.0})
    win = {f"metal{i}": (0.30, 0.70) for i in (1, 2, 3)}
    res = M.check(rep, win, None, None)
    assert res["per_layer"]["metal1"]["status"] == "PASS"
    assert res["per_layer"]["metal2"]["status"] == "FAIL"
    assert res["per_layer"]["metal3"]["status"] == "FAIL"
    assert "unjudged_bound" not in res["per_layer"]["metal1"]


def test_CONTROL_an_empty_report_is_still_a_FAIL(tmp_path):
    """UNMEASURED IS NOT ZERO: a report with no per-layer density never passes."""
    p = tmp_path / "density.rpt"
    p.write_text("nothing useful here\n")
    res = M.check(p, {"metal1": (0.30, None)}, None, None)
    assert res["verdict"] == "FAIL", res
