"""TAPEOUT-SIGNOFF (DRV) parity for a DESIGN-SUPPLIED SDC.

`step_pnr` appends the PDK-liberty-derived DRV block (`set_max_transition` /
`set_max_capacitance`) via `_build_auto_silicon_sdc` — but ONLY on the
else-branch, i.e. only when the project stages NO `constraints/*.sdc`. A design
that ships its own SDC took the staged branch and reached PnR with NO DRV
constraint at all, so `repair_design` had no slew/cap target and left the slews
unrepaired. The more complete the design's own inputs, the WEAKER the constraint
set it was implemented against.

Raw evidence that motivated the fix (a reused-IP CPU core on an open PDK): the
shipped post-route netlist carried a 7.03 ns slew against the same liberty's own
1.49 ns limit, and four min-drive gates on the critical path contributed 13.3 ns
of a 29.3 ns arrival on a 10 ns clock.

`_ensure_staged_sdc_drv` closes the asymmetry. Contract under test:
  1. absent limits are SUPPLIED from the ACTIVE liberty;
  2. a design-DECLARED limit is NEVER overridden or relaxed;
  3. a liberty declaring no limit yields NO fabricated constraint (§4.05);
  4. a fanout cap is supplied only when the DESIGN's OWN L9 declares one;
  5. the design's own clock / exceptions are preserved verbatim.

Every liberty below is SYNTHETIC with DRV numbers matching no real PDK, so a
hardcoded value cannot pass these tests.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# Synthetic ACTIVE liberty declaring both DRV limits (values match no real PDK).
_LIB_WITH_DRV = """\
library(active_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  default_max_transition : 0.37 ;
  default_max_capacitance : 0.23 ;
  cell (INV) { pin (Y) { direction : output ; max_capacitance : 0.23 ; } }
}
"""

# Synthetic liberty with NO library-level defaults but a characterised pin cap:
# the cap ceiling is derivable, the slew limit is NOT.
_LIB_PIN_CAP_ONLY = """\
library(pincap_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  cell (INV) { pin (Y) { direction : output ; max_capacitance : 0.11 ; } }
}
"""

# Synthetic liberty declaring NEITHER limit — nothing real to supply.
_LIB_NO_DRV = """\
library(bare_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  cell (INV) { pin (Y) { direction : output ; } }
}
"""

# The shape of a real hand-authored design SDC: a clock and I/O delays, and
# NO design-rule constraints at all. This is the case that reached PnR unrepaired.
_DESIGN_SDC_NO_DRV = """\
current_design my_core
create_clock -name core_clock -period 10.0 [get_ports clk_i]
set_input_delay  2.0 -clock core_clock [all_inputs -no_clocks]
set_output_delay 2.0 -clock core_clock [all_outputs]
"""

# A design SDC that DECLARES its own DRV limits — must be left alone.
_DESIGN_SDC_WITH_DRV = """\
current_design my_core
create_clock -name core_clock -period 10.0 [get_ports clk_i]
set_max_transition 0.90 [current_design]
set_max_capacitance 0.44 [current_design]
set_max_fanout 12 [current_design]
"""


def _lib(tmp, text, name="active.lib"):
    p = tmp / name
    p.write_text(text)
    return str(p)


# ── 1. the defect: absent limits get supplied from the active liberty ────────
def test_design_sdc_without_drv_gets_active_liberty_limits(tmp_path):
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    out, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib)
    assert "set_max_transition 0.37" in out, out
    assert "set_max_capacitance 0.23" in out, out
    assert info["added_max_transition"] == 0.37
    assert info["added_max_capacitance"] == 0.23
    assert info["design_declared"] == []


def test_supplied_sdc_is_valid_and_preserves_the_design_constraints(tmp_path):
    """The design's own clock/IO constraints survive verbatim — the DRV block is
    APPENDED, never a rewrite (a lost create_clock would silently un-constrain
    the whole design)."""
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    out, _ = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib)
    for line in _DESIGN_SDC_NO_DRV.strip().split("\n"):
        assert line in out, f"design constraint dropped: {line!r}"
    assert out.startswith(_DESIGN_SDC_NO_DRV)


# ── 2. a design-declared limit is never overridden or relaxed ────────────────
def test_design_declared_drv_is_never_overridden(tmp_path):
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    out, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_WITH_DRV, lib)
    assert out == _DESIGN_SDC_WITH_DRV, "byte-identical when design declares all"
    assert info["added_max_transition"] is None
    assert info["added_max_capacitance"] is None
    assert set(info["design_declared"]) == {
        "set_max_transition", "set_max_capacitance", "set_max_fanout"}
    # the liberty's LOOSER-or-different numbers never appear
    assert "0.37" not in out and "0.23" not in out


def test_partial_declaration_supplies_only_the_missing_limit(tmp_path):
    """A design that declares a slew limit but no cap limit keeps ITS slew value
    and gains only the cap ceiling."""
    sdc = (_DESIGN_SDC_NO_DRV
           + "set_max_transition 0.90 [current_design]\n")
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    out, info = R._ensure_staged_sdc_drv(sdc, lib)
    assert "set_max_transition 0.90" in out
    assert "set_max_transition 0.37" not in out, "design slew limit was overridden"
    assert "set_max_capacitance 0.23" in out
    assert info["added_max_transition"] is None
    assert info["added_max_capacitance"] == 0.23


# ── 3. §4.05 — never fabricate a limit the liberty does not declare ──────────
def test_liberty_without_drv_supplies_nothing(tmp_path):
    lib = _lib(tmp_path, _LIB_NO_DRV)
    out, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib)
    assert out == _DESIGN_SDC_NO_DRV, "fabricated a DRV limit from a bare liberty"
    assert info["added_max_transition"] is None
    assert info["added_max_capacitance"] is None
    assert info["note"]


def test_unreadable_liberty_supplies_nothing(tmp_path):
    out, info = R._ensure_staged_sdc_drv(
        _DESIGN_SDC_NO_DRV, str(tmp_path / "does_not_exist.lib"))
    assert out == _DESIGN_SDC_NO_DRV
    assert info["added_max_transition"] is None
    assert info["added_max_capacitance"] is None


def test_pin_cap_only_liberty_supplies_cap_but_not_slew(tmp_path):
    """A liberty with no default_max_transition yields NO slew constraint, but
    its characterised output-pin max_capacitance is a real, PDK-derived ceiling."""
    lib = _lib(tmp_path, _LIB_PIN_CAP_ONLY)
    out, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib)
    assert "set_max_transition" not in out
    assert "set_max_capacitance 0.11" in out
    assert info["added_max_transition"] is None
    assert info["added_max_capacitance"] == 0.11


# ── 4. fanout cap only when the DESIGN declares one ──────────────────────────
def test_no_fanout_cap_when_design_declares_none(tmp_path):
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    project = tmp_path / "proj"
    project.mkdir()
    out, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib,
                                         project=project)
    assert "set_max_fanout" not in out
    assert info["added_max_fanout"] is None


def test_project_arg_is_optional_and_never_raises(tmp_path):
    """`project=None` must not raise — step_pnr's disclosure must never be the
    thing that fails PnR."""
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    out, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib, project=None)
    assert "set_max_transition 0.37" in out
    assert info["added_max_fanout"] is None


# ── 5. regression guards on the surrounding contract ─────────────────────────
def test_idempotent_second_pass_adds_nothing(tmp_path):
    """Running the parity pass on an already-supplied SDC must not stack a
    second DRV block (a doubled constraint is legal SDC but hides provenance)."""
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    once, _ = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib)
    twice, info = R._ensure_staged_sdc_drv(once, lib)
    assert twice == once
    # count real CONSTRAINT LINES (the disclosure comment names the tokens too)
    assert len(R._SDC_MAX_TRANS_RE.findall(once)) == 1
    assert len(R._SDC_MAX_CAP_RE.findall(once)) == 1
    assert info["added_max_transition"] is None


def test_info_is_json_serialisable(tmp_path):
    """step_pnr writes the disclosure to pnr/sdc_drv_parity.json."""
    lib = _lib(tmp_path, _LIB_WITH_DRV)
    _, info = R._ensure_staged_sdc_drv(_DESIGN_SDC_NO_DRV, lib)
    json.loads(json.dumps(info, default=str))


def test_auto_sdc_branch_still_carries_drv(tmp_path):
    """Guard the branch that ALREADY worked: the auto-SDC path must keep
    emitting the DRV block, so this fix cannot regress it into the staged path's
    old behaviour."""
    text = R._build_auto_silicon_sdc(tmp_path, top="my_core",
                                     drv_slew_ns=0.37, drv_cap_pf=0.23,
                                     drv_note="synthetic")
    assert "set_max_transition 0.37" in text
    assert "set_max_capacitance 0.23" in text


def test_step_pnr_wires_the_parity_pass_on_the_staged_branch():
    """The defect was a MISSING CALL, not a bad function — guard the wiring so a
    refactor cannot silently drop it back onto the unconstrained path."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    staged = src.split("project_sdc_silicon and project_sdc_silicon.is_file()")[1]
    staged_branch = staged.split("_auto_die_requested")[0]
    assert "_ensure_staged_sdc_drv(" in staged_branch, (
        "step_pnr's design-supplied-SDC branch no longer applies the DRV "
        "parity pass — a design shipping its own SDC would reach PnR with no "
        "slew/cap target and repair_design would leave the slews unrepaired")
    assert "sdc_drv_parity.json" in staged_branch
