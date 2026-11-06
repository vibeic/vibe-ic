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
  4. a fanout cap is supplied from, in order: the DESIGN's OWN L9 declaration,
     else the RTL replication bound, else the ACTIVE liberty's own
     `default_max_fanout` — added 2026-08-07 (spm x ihp-sg13g2) after
     `default_max_transition`/`default_max_capacitance` above turned out to
     already read the liberty unconditionally while `max_fanout` did not, so
     a PDK whose library declares a real `default_max_fanout` but whose L9
     declares no cap (and which librelane's own shipped pdk_compat.py has no
     default for either — that table only covers sky130*/gf180mcu*) silently
     let CTS build a leaf buffer past the library's own characterised limit;
     post-route sign-off then measured a REAL DRV violation nothing upstream
     had a target to prevent. Reading the library's own declared ceiling is
     not fabricating one (§4.05 distinguishes "invented" from "measured");
  5. the design's own clock / exceptions are preserved verbatim.

Every liberty below is SYNTHETIC with DRV numbers matching no real PDK, so a
hardcoded value cannot pass these tests.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


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




# ── 1. the defect: absent limits get supplied from the active liberty ────────




# ── 2. a design-declared limit is never overridden or relaxed ────────────────




# ── 3. §4.05 — never fabricate a limit the liberty does not declare ──────────






# ── 4. fanout cap: design declaration wins, liberty default is the fallback ──












# ── 5. regression guards on the surrounding contract ─────────────────────────








def test_step_pnr_wires_the_fanout_cap_into_cts_clustering():
    """spm x ihp-sg13g2, 2026-08-07: `set_max_fanout` reaching the SDC is NOT
    enough — MEASURED live (real PnR, real container): a staged SDC carrying
    `set_max_fanout 8` still let `clock_tree_synthesis` build a leaf buffer
    fanning out to 16, because CTS's own sink clustering is governed only by
    `-sink_clustering_size` passed to the command, not by the loaded SDC. The
    defect this guards is the same shape as the one above — a missing call —
    one level further down the same flow. `cts_cluster_size=` must consult
    `_cts_fanout_target`, and both the staged and auto-SDC branches must set
    it; a refactor that silently drops either regresses to "the SDC number
    exists but nothing acts on it for CTS.\""""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    step_pnr_src = src.split("def step_pnr(", 1)[1].split("\ndef _decap_route_short_guard(", 1)[0]

    assert "cts_cluster_size=(_rf_map.get(\"cts_cluster_size\")\n" in step_pnr_src \
        or "_rf_map.get(\"cts_cluster_size\")\n                          or _cts_fanout_target)" in step_pnr_src, (
        "step_pnr no longer falls back to _cts_fanout_target for "
        "cts_cluster_size — a design/liberty fanout cap would stop reaching "
        "clock_tree_synthesis's -sink_clustering_size")

    # FX_STEP7_ASIC_SDC: the author now lives in step 7's producer
    # (`_ppa.timing.author_asic_sdc`); `step_pnr` takes `_cts_fanout_target`
    # from what that author resolved. Same property, asserted where it lives.
    assert ('_cts_fanout_target: Optional[int] = _asic.get("cts_fanout_target")'
            in step_pnr_src), (
        "step_pnr no longer takes _cts_fanout_target from step 7's authored SDC")
    author_src = (PROGRAMS / "_ppa" / "timing.py").read_text()
    author = author_src.split("def author_asic_sdc(", 1)[1].split("\ndef ", 1)[0]
    staged_branch = author.split('if out["design_staged"]:', 1)[1].split(
        "\n    else:", 1)[0]
    assert 'out["cts_fanout_target"]' in staged_branch, (
        "the staged-SDC branch no longer sets _cts_fanout_target")

    assert "_build_auto_silicon_sdc(" in author
    auto_region = author.split("_build_auto_silicon_sdc(", 1)[1][:2000]
    assert 'out["cts_fanout_target"]' in auto_region, (
        "the auto-SDC branch no longer sets _cts_fanout_target — a design "
        "with no staged constraints/*.sdc would get a liberty-derived slew/"
        "cap DRV but silently lose the equivalent fanout cap for CTS")
