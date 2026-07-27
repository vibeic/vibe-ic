"""`[ERROR RSZ-0090]` blames the wrong producer, and the flow must correct it.

The message OpenROAD prints is

    Max transition time from SDC is 1.000ns. Best achievable transition time
    is 1.205ns with a load of 0.30pF

Both halves mislead an operator:

* "**from SDC**" is false whenever a liberty pin declares a tighter
  `max_transition` than the design SDC. OpenSTA merges a library/pin limit into
  the same constraint the SDC feeds and the resizer reports the merged number
  under the SDC's label — so an engineer reads the SDC, finds a much looser
  limit there, and concludes the tool is broken or the number must be relaxed.
* "**best achievable**" is not a process capability. It is the minimum output
  slew over the resizer's SIZING POOL — `getSwappableCells(weakest buffer)`
  filtered by `sizing_area_limit` / `sizing_leakage_limit`. A library whose
  buffer family spans more than those ratios has stronger buffers the check
  never considers.

Getting this wrong has a specific, expensive failure mode: relaxing the
`max_transition` in the vendor liberty to make the abort go away. These tests
pin the PROPERTY that the flow names the file that actually declared the limit,
in the right units, and never fires when there is no abort.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

ABORT_LOG = """
Iteration |   Area    | Resized | Buffers | Nets repaired | Remaining
        0 |     +0.0% |       0 |       0 |             0 |      3128
[ERROR RSZ-0090] Max transition time from SDC is 1.000ns. Best achievable \
transition time is 1.205ns with a load of 0.30pF
"""

SDC = """
create_clock -name clk -period 20.0 [get_ports clk]
set_max_transition 3.0 [current_design]
set_max_capacitance 6.23 [current_design]
"""

STD_LIB = """
library (fixture_stdcells) {
    time_unit : "1ns";
    capacitive_load_unit(1.000000,  pf);
    default_max_transition : 3.000000;
    cell (BUFA) { area : 10.0 ; }
}
"""

MACRO_LIB = """
library (fixture_macro) {
    time_unit                     : "1ns" ;
    capacitive_load_unit            (1,pf) ;
    default_max_transition        : 1 ;
    cell (FIXTURE_MACRO) {
      pin (D) {
        direction : input ;
        capacitance : 0.3 ;
        max_transition : 1 ;
      }
    }
}
"""

# Same physical declaration (1.0 ns) written in a different liberty time unit.
MACRO_LIB_PS = """
library (fixture_macro_ps) {
    time_unit                     : "10ps" ;
    default_max_transition        : 100 ;
    cell (FIXTURE_MACRO) { pin (D) { direction : input ; max_transition : 100 ; } }
}
"""


def _write(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_abort_is_attributed_to_the_liberty_that_declared_the_limit(tmp_path):
    """PROPERTY: with an SDC at 3.0 ns and a macro liberty at 1.0 ns, the
    1.000 ns the tool reported must be traced to the LIBERTY, and the liberty
    file must be named. Reporting it as an SDC limit sends the engineer to a
    file that does not contain the number."""
    std = _write(tmp_path, "std.lib", STD_LIB)
    macro = _write(tmp_path, "macro.lib", MACRO_LIB)
    got = R._attribute_max_transition_abort(ABORT_LOG, [std, macro], SDC)
    assert got is not None, "an RSZ-0090 abort in the log was not attributed"
    assert got["source"] == "liberty", got
    named = [d["path"] for d in got["declaring_liberties"]]
    assert macro in named, (
        f"the liberty that declares the reported 1.000 ns is not named: {got}")
    assert std not in named, (
        "a liberty whose loosest declaration is 3.0 ns was named as the "
        f"producer of a 1.0 ns limit: {got}")
    # The contrast an operator needs: what the SDC actually says.
    assert got["sdc_max_transition_ns"] == 3.0, got
    assert abs(got["limit_ns"] - 1.0) < 1e-9, got
    assert abs(got["best_achievable_ns"] - 1.205) < 1e-9, got
    assert abs(got["load_pf"] - 0.30) < 1e-9, got


def test_liberty_time_unit_is_honoured(tmp_path):
    """PROPERTY: a liberty declaring the SAME 1.0 ns limit in a 10 ps time unit
    must still be recognised. Comparing raw liberty numbers against the tool's
    nanoseconds silently misses the producer on any non-ns library."""
    macro_ps = _write(tmp_path, "macro_ps.lib", MACRO_LIB_PS)
    got = R._attribute_max_transition_abort(ABORT_LOG, [macro_ps], SDC)
    assert got is not None
    assert got["source"] == "liberty", got
    assert [d["path"] for d in got["declaring_liberties"]] == [macro_ps], got
    assert abs(got["declaring_liberties"][0]["min_max_transition_ns"]
               - 1.0) < 1e-6, got


def test_sdc_is_named_when_the_sdc_really_is_the_tightest(tmp_path):
    """PROPERTY: no over-correction. When only the SDC declares the reported
    limit, the SDC must be named — the fix must not blame liberties reflexively."""
    log = ABORT_LOG.replace("is 1.000ns", "is 3.000ns")
    std = _write(tmp_path, "std.lib", STD_LIB)
    got = R._attribute_max_transition_abort(log, [std], SDC)
    assert got is not None
    assert got["source"] == "sdc", got


def test_no_abort_means_no_attribution(tmp_path):
    """PROPERTY: no false fire. A clean PnR log must produce nothing."""
    clean = "[INFO RSZ-0034] Found 17 slew violations.\n[INFO DRT-0198] Complete detail routing.\n"
    std = _write(tmp_path, "std.lib", STD_LIB)
    assert R._attribute_max_transition_abort(clean, [std], SDC) is None


def test_declared_sizing_pool_is_carried_into_the_attribution(tmp_path):
    """PROPERTY: "best achievable" is a property of the search pool, so the
    pool the run declared must travel with the abort. Without it the operator
    cannot tell an unmeetable constraint from an under-declared pool."""
    log = ("DRV_SIZING_POOL: buffers=21 rows=441 area_span=4.25 leak_span=15.82"
           " area_limit=6 leak_limit=20\n" + ABORT_LOG)
    macro = _write(tmp_path, "macro.lib", MACRO_LIB)
    got = R._attribute_max_transition_abort(log, [macro], SDC)
    assert got is not None
    assert got["declared_sizing_pool"] is not None, got
    assert "leak_limit=20" in got["declared_sizing_pool"], got


def test_unreadable_liberty_is_disclosed_not_swallowed(tmp_path):
    """PROPERTY: a liberty the attribution could not open must be reported as
    unreadable. Silently dropping it would turn "I could not look" into
    "it is not there"."""
    got = R._attribute_max_transition_abort(
        ABORT_LOG, [str(tmp_path / "does_not_exist.lib")], SDC)
    assert got is not None
    assert got["unreadable_liberties"] == [str(tmp_path / "does_not_exist.lib")]
    assert got["source"] != "liberty", got


def test_liberty_paths_are_recovered_from_the_emitted_pnr_program():
    """PROPERTY: the attribution's inputs come from the PnR program the flow
    actually emitted, so it stays correct when the corner/liberty set changes."""
    tcl = ("read_lef /pdk/tech.lef\n"
           "define_corners ss tt ff\n"
           "read_liberty -corner ss /pdk/slow.lib\n"
           "read_liberty -corner tt /pdk/typ.lib\n"
           "read_liberty -corner ss /macros/hardmacro.lib\n"
           "read_liberty -corner tt /macros/hardmacro.lib\n"
           "read_verilog /work/n.v\n"
           "read_sdc /work/c.sdc\n")
    assert R._read_liberty_paths_from_tcl(tcl) == [
        "/pdk/slow.lib", "/pdk/typ.lib", "/macros/hardmacro.lib"]
    assert R._read_sdc_path_from_tcl(tcl) == "/work/c.sdc"
