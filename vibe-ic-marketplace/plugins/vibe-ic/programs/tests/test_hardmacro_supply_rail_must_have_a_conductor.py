"""A rail is not a rail without a conductor, and a declaration derived from its
own subject cannot validate that subject.

Synthetic throughout — generic rail names, a generic macro, no design or process
is named.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hardmacro_supply_intent as H  # noqa: E402

BUILT = """SPECIALNETS 3 ;
    - VPWR ( * VPWR ) + USE POWER
      + ROUTED met1 480 + SHAPE FOLLOWPIN ( 0 2720 ) ( 199920 * )
      NEW met4 1600 + SHAPE STRIPE ( 1000 0 ) ( 1000 200000 )
      ;
    - VGND ( * VGND ) + USE GROUND
      + ROUTED met1 480 + SHAPE FOLLOWPIN ( 0 5440 ) ( 199920 * )
      ;
    - VPROG ( * VPROG ) + USE POWER ;
END SPECIALNETS
"""


def _project(tmp: Path, def_text: str) -> Path:
    d = tmp / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "routed.def").write_text(def_text, encoding="utf-8")
    return tmp


def test_a_rail_with_conductor_is_measured(tmp_path):
    assert "VPWR" in H.measured_rails(_project(tmp_path, BUILT))


def test_a_rail_that_is_only_a_name_is_not_measured(tmp_path):
    """`- VPROG ( * VPROG ) + USE POWER ;` — connect-all-by-name, no metal.

    The shape this file exists for: it was counted as a rail the PDN built, so a
    macro pin bound to it read as covered while carrying no current.
    """
    p = _project(tmp_path, BUILT)
    assert H.measured_rails(p) == ["VGND", "VPWR"]
    assert "VPROG" not in H.measured_rails(p)


def test_the_unbuilt_rail_is_returned_as_the_complement(tmp_path):
    """The other half of the same split.

    RENAMED. The previous name was
    `test_the_unbuilt_rail_is_reported_not_silently_dropped`, which asserted
    REPORTING while its body only asserted a RETURN VALUE — the same over-claim
    the function's own docstring carried, pinned by a test that could never
    catch it. What is reported, and where, is asserted by the
    `_macro_supply_preroute_decision` / `step_pnr` tests below.
    """
    assert H.rails_named_but_not_built(_project(tmp_path, BUILT)) == ["VPROG"]


def test_both_halves_come_from_one_scan(tmp_path):
    p = _project(tmp_path, BUILT)
    assert H.specialnets_split(p) == (["VGND", "VPWR"], ["VPROG"])
    assert H.specialnets_split(tmp_path / "nothing-here") == ([], [])


def test_a_rail_built_only_with_fixed_geometry_still_counts(tmp_path):
    """Some flows emit FIXED rather than ROUTED; both are conductor."""
    txt = ("SPECIALNETS 1 ;\n"
           "    - VPWR ( * VPWR ) + USE POWER\n"
           "      + FIXED met1 480 ( 0 2720 ) ( 199920 * )\n      ;\n"
           "END SPECIALNETS\n")
    assert H.measured_rails(_project(tmp_path, txt)) == ["VPWR"]


def test_no_def_measures_nothing(tmp_path):
    assert H.measured_rails(tmp_path) == []
    assert H.rails_named_but_not_built(tmp_path) == []


# ---------------------------------------------------------------- independence

def _l21(entries):
    return {"fields": {"power_domains": entries}}


def test_a_hand_written_declaration_still_counts(tmp_path):
    """No provenance means hand-written. Refusing those would lock the door the
    escape hatch exists to open (#348)."""
    assert H.declared_rails(_l21([{"rail": "VPWR"}])) == ["VPWR"]


def test_a_rail_synthesised_from_the_macro_pins_is_not_a_declaration():
    """The anti-cheat anchor its own docstring names, now enforced.

    A rail derived from the pins it would be used to check matches every one of
    them by construction, so the "pins with no matching rail" count could never
    be non-zero.
    """
    l21 = _l21([{"rail": "VPROG",
                 "derived_by": "l21_macro_supply_rail_synth",
                 "derived_from": {"macro_lef_pin_use": "POWER",
                                  "declared_by_macros": ["GENERIC_HARDMACRO"]}}])
    assert H.declared_rails(l21) == []


def test_provenance_naming_the_macros_is_enough_on_its_own():
    """Keyed on what the synthesiser records, not on a list of its names."""
    l21 = _l21([{"rail": "VPROG",
                 "derived_from": {"declared_by_macros": ["GENERIC_HARDMACRO"]}}])
    assert H.declared_rails(l21) == []


def test_an_unrelated_derivation_is_not_treated_as_self_derived():
    """A rail derived from the PDK or the floorplan is still independent of the
    macro pins, and must not be discarded."""
    l21 = _l21([{"rail": "VPWR", "derived_by": "pdk_default_supply_map",
                 "derived_from": {"pdk": "generic"}}])
    assert H.declared_rails(l21) == ["VPWR"]


def test_a_macro_pin_bound_to_a_nameonly_rail_is_no_longer_covered(tmp_path):
    """End to end: the verdict this whole file is about.

    The mapping points at a rail that exists only as a name, and the design's
    only declaration of it was synthesised from the pin itself.
    """
    l21 = {"fields": {
        "power_domains": [{"rail": "VPROG",
                           "derived_by": "l21_macro_supply_rail_synth",
                           "derived_from": {"macro_lef_pin_use": "POWER"}}],
        "hard_macro_supplies": [{"master": "GENERIC_HARDMACRO", "pin": "VPROG",
                                 "rail": "VPROG"}]}}
    measured = H.measured_rails(_project(tmp_path, BUILT))
    got = H.classify_pin("GENERIC_HARDMACRO", "VPROG", l21, extra_rails=measured)
    assert got["status"] == "rail_undeclared", got


# ─────────── the drop must reach the run's REPORT, not just a return value ────
#
# The defect this section exists for: `rails_named_but_not_built` shipped a
# docstring saying "Reported rather than silently dropped" while having ZERO
# non-test callers. Availability is not reporting — a filter that fires
# silently cannot be told apart from one that never fires (#313 §6).
#
# Every assertion below is BEHAVIOURAL: it runs the real decision / the real
# step and reads the value back. None of them searches the runner's source
# text. A source-substring assertion is satisfied by a COMMENT saying the
# report does not exist, which would reproduce this very defect inside its own
# fix; an AST "every dict-literal return carries the key" assertion is
# satisfied by a branch that hardcodes an empty list.

_LEF_FULL = """
MACRO GENERIC_HARDMACRO
  PIN VPWR
    DIRECTION INOUT ; USE POWER ;
  END VPWR
  PIN VGND
    DIRECTION INOUT ; USE GROUND ;
  END VGND
  PIN VPROG
    DIRECTION INOUT ; USE POWER ;
  END VPROG
END GENERIC_HARDMACRO
"""

# No VPROG pin — every PG pin matches a rail the DEF really built, so the
# decision takes the no-gaps return.
_LEF_ACCOUNTED = """
MACRO GENERIC_HARDMACRO
  PIN VPWR
    DIRECTION INOUT ; USE POWER ;
  END VPWR
  PIN VGND
    DIRECTION INOUT ; USE GROUND ;
  END VGND
END GENERIC_HARDMACRO
"""

# Every SPECIALNETS entry is a bare name: nothing is BUILT, so no rail is
# established from any source and the decision takes the env-blind return.
ALL_BARE = """SPECIALNETS 1 ;
    - VPROG ( * VPROG ) + USE POWER ;
END SPECIALNETS
"""

_NL_TIED = ("module top;\n"
            "GENERIC_HARDMACRO u ( .VPROG(1'b1), .VPWR(VPWR), .VGND(VGND) );\n"
            "endmodule\n")
_NL_UNDRIVEN = ("module top;\n"
                "GENERIC_HARDMACRO u ( .VPWR(VPWR), .VGND(VGND) );\n"
                "endmodule\n")


def _decision_project(tmp: Path, def_text, lef_text: str) -> Path:
    if def_text is not None:
        _project(tmp, def_text)
    (tmp / "macro.lef").write_text(lef_text, encoding="utf-8")
    return tmp


class _Pdk:
    """Only `macro_lefs` — `_design_supply_nets` then finds no PDK cell LEF and
    returns (∅, ∅), so the env-blind witness is decided by the DEF/L21 alone."""

    def __init__(self, lef: Path):
        self.macro_lefs = [str(lef)]


def _p3():
    import phase3_one_shot_runner as p3
    return p3


# --- all five returns taken AFTER the DEF is read carry the real value -------

def test_return_no_gaps_carries_the_bare_rail(tmp_path):
    p = _decision_project(tmp_path, BUILT, _LEF_ACCOUNTED)
    d = _p3()._macro_supply_preroute_decision(p, _Pdk(p / "macro.lef"))
    assert d["blocking"] is False and d["gaps"] == []
    assert d["rails_named_not_built"] == ["VPROG"]


def test_return_env_blind_carries_the_bare_rail(tmp_path):
    p = _decision_project(tmp_path, ALL_BARE, _LEF_FULL)
    d = _p3()._macro_supply_preroute_decision(p, _Pdk(p / "macro.lef"))
    assert d.get("env_blind") is True
    assert d["rails_named_not_built"] == ["VPROG"]


def test_return_benign_gaps_carries_the_bare_rail(tmp_path):
    p = _decision_project(tmp_path, BUILT, _LEF_FULL)
    d = _p3()._macro_supply_preroute_decision(p, _Pdk(p / "macro.lef"),
                                              netlist_text=_NL_UNDRIVEN)
    assert d["blocking"] is False
    assert {g["pin"] for g in d["gaps_reported"]} == {"VPROG"}
    assert d["rails_named_not_built"] == ["VPROG"]


def test_return_fatal_tie_carries_the_bare_rail(tmp_path):
    p = _decision_project(tmp_path, BUILT, _LEF_FULL)
    d = _p3()._macro_supply_preroute_decision(p, _Pdk(p / "macro.lef"),
                                              netlist_text=_NL_TIED)
    assert d["blocking"] is True
    assert {g["pin"] for g in d["gaps"]} == {"VPROG"}
    assert d["rails_named_not_built"] == ["VPROG"]


def test_return_no_netlist_carries_the_bare_rail(tmp_path):
    p = _decision_project(tmp_path, BUILT, _LEF_FULL)
    d = _p3()._macro_supply_preroute_decision(p, _Pdk(p / "macro.lef"))
    assert d["blocking"] is True
    assert d["rails_named_not_built"] == ["VPROG"]


def test_returns_taken_before_the_def_is_read_claim_nothing(tmp_path):
    """The three `return None` paths precede the DEF read. They must stay None:
    a dict carrying `[]` there would be a claim about a file never opened."""
    p = _project(tmp_path, BUILT)
    (p / "empty.lef").write_text("", encoding="utf-8")
    assert _p3()._macro_supply_preroute_decision(
        p, _Pdk(p / "empty.lef")) is None


# --- and it reaches the durable report the run leaves behind -----------------

def _pnr_project(tmp: Path, def_name, def_text: str) -> Path:
    """A tree just complete enough for `step_pnr` to reach its blocking FAIL.

    That return is taken BEFORE any container invocation, so no PnR tree and no
    OpenROAD is needed — MEASURED, and it is why the report is asserted on the
    real StepResult instead of on the runner's source text.

    The L21 declares VPWR/VGND (never VPROG) so that a tree WITHOUT a DEF still
    establishes rails and reaches the BLOCKING return. Without it the gate is
    correctly env-blind and never blocks, and the two tests below would differ
    in their verdict rather than in the one variable under test: the DEF.
    """
    import json as _json
    import _path_layout as _pl
    sd = _pl.synth_dir(tmp)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "chip_top_synth.v").write_text(_NL_TIED, encoding="utf-8")
    gd = tmp / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L21_POWER_INTENT.json").write_text(_json.dumps(
        {"fields": {"power_rails": [{"rail": "VPWR"}, {"rail": "VGND"}]}}),
        encoding="utf-8")
    if def_name is not None:
        pd = _pl.pnr_dir(tmp)
        pd.mkdir(parents=True, exist_ok=True)
        (pd / def_name).write_text(def_text, encoding="utf-8")
    (tmp / "macro.lef").write_text(_LEF_FULL, encoding="utf-8")
    return tmp


def test_the_bare_rail_reaches_the_pnr_fail_rows_extras(tmp_path):
    """THE assertion the docstring's "Reported" claim now rests on.

    `extras` is serialized into `reports/phase3/phase3_one_shot.json`, so this
    survives the terminal. The DEF is `post_cts.def`: the one band where the
    fact is non-empty AND `pg_rail_geometry_check` (which reads `routed.def`
    only) is SKIP — i.e. where nothing else says it.
    """
    p = _pnr_project(tmp_path, "post_cts.def", BUILT)
    r = _p3().step_pnr(p, "chip_top", _Pdk(p / "macro.lef"),
                       "no-such-container", "200x200", 0.4)
    assert r.status == "FAIL"
    assert r.extras["macro_supply_gaps"]
    assert r.extras["rails_named_not_built"] == ["VPROG"]


def test_no_def_publishes_no_key_rather_than_an_empty_all_clear(tmp_path):
    """On a FIRST run `phase3/stage3/pnr/` is empty at the gate — every DEF is
    written by this step's own TCL, further down. An empty list here would read
    as "the built rails were examined and none was a bare name". Nothing was
    examined, so the key is ABSENT: no claim, rather than a false clean one."""
    p = _pnr_project(tmp_path, None, "")
    r = _p3().step_pnr(p, "chip_top", _Pdk(p / "macro.lef"),
                       "no-such-container", "200x200", 0.4)
    assert r.status == "FAIL"
    assert "rails_named_not_built" not in (r.extras or {})


# --- complementarity with the post-route gate, asserted rather than assumed --

def test_the_two_gates_are_complements_not_duplicates(tmp_path):
    """Pins the band claim the docstring makes.

    HONEST LABEL: this test passes both BEFORE and AFTER this change. It is not
    evidence of the fix — it pins the PREMISE the fix is scoped on, so that
    widening `pg_rail_geometry_check._find_def` to accept `post_cts.def` (which
    would turn the runner-side report into a duplicate) fails here and forces
    the docstring to be revisited rather than silently rotting.
    """
    import pg_rail_geometry_check as PG

    routed = _project(tmp_path / "routed", BUILT)
    assert H.rails_named_but_not_built(routed) == ["VPROG"]
    res = PG.check(routed)
    assert res["verdict"] == "FAIL"
    assert "VPROG" in {f["rail"] for f in res["findings"]}

    pre = tmp_path / "prects"
    d = pre / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "post_cts.def").write_text(BUILT, encoding="utf-8")
    assert H.rails_named_but_not_built(pre) == ["VPROG"]
    assert PG.check(pre)["verdict"] == "SKIP"
