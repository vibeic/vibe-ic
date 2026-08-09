#!/usr/bin/env python3
"""Nothing compared what the plugin PARSES against what the tool can LOAD.

Every other obstruction check in this plugin reads the LEF with the plugin's own
parser and then reasons about what it found. That parser is not the one the flow
runs on. When the two disagree, every downstream verdict is computed over
geometry the tool never had — and each verdict is individually correct, which is
why nothing catches it.

THE MEASURED DEFECT. A macro abstract's `OBS` section opens on a layer the tech
LEF does not declare. A real reader emits one `undefined layer (...) referenced`
warning, **stops reading the section there, and returns success**. The
three-point control below was measured against an actual reader, on the same
synthetic LEFs this file builds:

    variant                                  tool loads    diagnostic
    as shipped (OBS's first entry undeclared)         0    undefined layer (…)
    that one OBS entry removed                       63    none
    tech LEF given the layer declaration             64    none

The cost is TRUNCATION FROM THAT ENTRY ONWARD, so the position decides how much
it is — separately verified at three positions and pinned by
`test_the_cost_is_truncation_from_the_offending_entry`:

    entry position      rects the reader kept
    first                                   0
    after 30 of 63                         30
    last                                   63

"the section is discarded" over-reports whenever the entry is not first; "only
that entry is dropped" under-reports whenever it is not last. Both directions
are asserted. The FIRST position is the common one, because the layer stating a
macro's own extent is conventionally declared before the metal layers — which is
why the row above loses everything.

The trigger is routine: the LEF spec defines layer TYPEs a tech LEF is NOT
REQUIRED to declare, and an abstract may legitimately open its OBS on one.

GENERALITY. The rule under test is "referenced but not declared". No layer name
is detection logic — the fixture's undeclared layer is whatever the input names,
and `test_the_rule_is_referenced_but_not_declared_not_a_layer_name` re-runs the
whole comparison with the layer renamed to prove the verdict does not depend on
which name it was.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
_GATE = os.path.join(_PROGRAMS, "macro_obs_load_parity_check.py")


def _gate():
    spec = importlib.util.spec_from_file_location("_macro_obs_parity", _GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_macro_obs_parity"] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ fixtures
_TECH_CORE = """VERSION 5.8 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MANUFACTURINGGRID 0.005 ;

LAYER metalA
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
END metalA

LAYER cutA
  TYPE CUT ;
END cutA
"""

_TECH_TAIL = "\nEND LIBRARY\n"


def tech_lef(extra_layer: str = "") -> str:
    block = ""
    if extra_layer:
        block = f"\nLAYER {extra_layer}\n  TYPE OVERLAP ;\nEND {extra_layer}\n"
    return _TECH_CORE + block + _TECH_TAIL


def macro_lef(extent_layer: str = "OVERLAP", n_metal: int = 63,
              at: str = "first") -> str:
    """An abstract whose OBS optionally names `extent_layer`.

    `at` places that entry FIRST, LAST, or in the MIDDLE of the metal rects, so
    the truncation position can be varied while the geometry stays fixed."""
    def _rects(lo, hi):
        out = []
        for i in range(lo, hi):
            y = 0.5 + i * 0.6
            out.append(f"      RECT 0.500 {y:.3f} 39.500 {y + 0.30:.3f} ;")
        return out

    extent = ([f"    LAYER {extent_layer} ;",
               "      RECT 0.000 0.000 40.000 40.000 ;"] if extent_layer else [])
    lines = ["  OBS"]
    if at == "first":
        lines += extent + ["    LAYER metalA ;"] + _rects(0, n_metal)
    elif at == "last":
        lines += ["    LAYER metalA ;"] + _rects(0, n_metal) + extent
    else:
        half = n_metal // 2
        lines += (["    LAYER metalA ;"] + _rects(0, half) + extent
                  + ["    LAYER metalA ;"] + _rects(half, n_metal))
    lines.append("  END")
    obs = "\n".join(lines)
    return ("VERSION 5.8 ;\n\nMACRO block_a\n  CLASS BLOCK ;\n"
            "  SIZE 40.000 BY 40.000 ;\n" + obs +
            "\nEND block_a\n\nEND LIBRARY\n")


# The reader's own announcement, as a real tool writes it.
TOOL_LOG = ("[INFO ODB-0000] reading LEF\n"
            "[WARNING ODB-0176] error: undefined layer (OVERLAP) referenced\n"
            "[INFO ODB-0000] done\n")


# -------------------------------------------------------------- the defect
def test_as_shipped_the_whole_obs_section_is_unloadable():
    """REGRESSION. This is the measured `tool loads 0` row."""
    M = _gate()
    rep = M.audit([tech_lef(), macro_lef()], ["tech.lef", "macro.lef"])
    assert len(rep["findings"]) == 1, rep
    f = rep["findings"][0]
    assert f["master"] == "block_a"
    assert f["parsed_obs_rects"] == 63, "the plugin's own reading"
    assert f["loadable_obs_rects"] == 0, "what a reader would keep"
    assert f["unresolvable_layers"] == ["OVERLAP"]
    assert rep["obs_rects_lost_total"] == 63


def test_removing_that_one_entry_restores_parity():
    """CONTROL — the measured `tool loads 63` row."""
    M = _gate()
    rep = M.audit([tech_lef(), macro_lef(extent_layer="")],
                  ["tech.lef", "macro.lef"])
    assert rep["findings"] == [], rep["findings"]
    assert rep["obs_rects_parsed_total"] == 63


def test_declaring_the_layer_restores_parity():
    """CONTROL — the measured `tool loads 64` row. Same abstract, unchanged;
    only the tech LEF gained the declaration."""
    M = _gate()
    rep = M.audit([tech_lef(extra_layer="OVERLAP"), macro_lef()],
                  ["tech.lef", "macro.lef"])
    assert rep["findings"] == [], rep["findings"]
    assert "overlap" in rep["layers_declared_by_lef_set"]


# ------------------------------------------------------------- generality
def test_the_rule_is_referenced_but_not_declared_not_a_layer_name():
    """GENERALITY. Rename the layer to something with no LEF-spec meaning and
    the verdict must be identical — the detector keys on the RELATION, never on
    which name appeared."""
    M = _gate()
    undeclared = M.audit([tech_lef(), macro_lef(extent_layer="zzTopExtent")],
                         ["tech.lef", "macro.lef"])
    assert len(undeclared["findings"]) == 1
    assert undeclared["findings"][0]["unresolvable_layers"] == ["zzTopExtent"]

    declared = M.audit(
        [tech_lef(extra_layer="zzTopExtent"), macro_lef(extent_layer="zzTopExtent")],
        ["tech.lef", "macro.lef"])
    assert declared["findings"] == []


def test_a_macro_pin_cannot_vouch_for_a_layer():
    """A macro's PIN/OBS bodies are full of `LAYER <name> ;` REFERENCES. If one
    of those counted as a declaration, the macro would vouch for the very layer
    whose absence is the defect and this gate would never fire."""
    M = _gate()
    assert M.declared_layers(macro_lef()) == set()
    assert "metala" in M.declared_layers(tech_lef())


# ------------------------------------------------------- the tool-log leg
def test_the_tool_log_corroborates():
    """The static leg infers; the log MEASURES. When both are present the
    finding says so."""
    M = _gate()
    rep = M.audit([tech_lef(), macro_lef()], ["tech.lef", "macro.lef"],
                  [TOOL_LOG])
    assert rep["undefined_layers_in_tool_log"] == ["overlap"]
    assert rep["findings"][0]["corroborated_by_tool_log"] == ["OVERLAP"]


def test_the_log_can_report_a_layer_the_static_leg_cleared():
    """A run may have read a file the project no longer holds. The logged name
    is unioned in, so the loss is still reported rather than cleared by the
    absence of its cause."""
    M = _gate()
    rep = M.audit([tech_lef(extra_layer="OVERLAP"), macro_lef()],
                  ["tech.lef", "macro.lef"], [TOOL_LOG])
    assert len(rep["findings"]) == 1, rep
    assert rep["findings"][0]["corroborated_by_tool_log"] == ["OVERLAP"]


# ----------------------------------------------------------- refusals
def test_no_lef_is_not_a_pass(tmp_path):
    r = subprocess.run([sys.executable, _GATE, str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "CANNOT DETERMINE" in r.stderr


def test_no_obs_is_not_a_pass(tmp_path):
    (tmp_path / "tech.lef").write_text(tech_lef())
    (tmp_path / "macro.lef").write_text(
        "MACRO block_a\n  SIZE 40.0 BY 40.0 ;\nEND block_a\n")
    r = subprocess.run([sys.executable, _GATE, str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "nothing was compared" in r.stderr


# ------------------------------------------------------------- end to end
def _run(tmp_path, tech, macro, log=None):
    (tmp_path / "tech.lef").write_text(tech)
    (tmp_path / "macro.lef").write_text(macro)
    if log is not None:
        (tmp_path / "tool.log").write_text(log)
    out = tmp_path / "rep.json"
    r = subprocess.run(
        [sys.executable, _GATE, str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    return r, json.loads(out.read_text())


def test_cli_blocks_on_the_as_shipped_variant(tmp_path):
    r, rep = _run(tmp_path, tech_lef(), macro_lef(), TOOL_LOG)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CANNOT LOAD" in r.stdout
    assert "63 of 63 parsed OBS rect(s) would be discarded" in r.stdout, r.stdout
    assert rep["obs_rects_lost_total"] == 63


def test_cli_passes_when_the_layer_is_declared(tmp_path):
    r, rep = _run(tmp_path, tech_lef(extra_layer="OVERLAP"), macro_lef())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert rep["findings"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))


# ------------------------------------------------------- truncation position
# VERIFIED against the reader by moving one unresolvable entry within an
# otherwise identical 63-rect section:
#
#     entry position      rects the reader kept
#     first                                   0
#     after 30 of 63                         30
#     last                                   63
#
# "the section is discarded" over-reports whenever the entry is not first;
# "only that entry is dropped" under-reports whenever it is not last. The gate
# must model the WALK, and these pin all three positions.
@pytest.mark.parametrize("at,kept,lost", [
    ("first", 0, 63),
    ("middle", 31, 32),
    ("last", 63, 0),
])
def test_the_cost_is_truncation_from_the_offending_entry(at, kept, lost):
    M = _gate()
    rep = M.audit([tech_lef(), macro_lef(at=at)], ["tech.lef", "macro.lef"])
    assert len(rep["findings"]) == 1, rep
    f = rep["findings"][0]
    assert f["loadable_obs_rects"] == kept, f
    assert f["obs_rects_lost"] == lost, f


def test_an_entry_placed_last_loses_nothing_but_is_still_reported():
    """The layer IS unresolvable and the run WILL warn, so the disagreement is
    real and must be visible — but the loss is 0 and must not be inflated to
    the section size."""
    M = _gate()
    rep = M.audit([tech_lef(), macro_lef(at="last")], ["tech.lef", "macro.lef"])
    assert rep["obs_rects_lost_total"] == 0
    assert rep["findings"][0]["unresolvable_layers"] == ["OVERLAP"]
