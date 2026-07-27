"""The PnR program the flow emits must DECLARE the resizer's sizing pool from
the library it actually loaded, instead of inheriting OpenROAD's default.

Why this is a correctness property and not a tuning knob
--------------------------------------------------------
OpenROAD decides whether a `max_transition` is achievable at all in
`rsz::PreChecks::checkSlewLimit` (`[ERROR RSZ-0090]`, a hard error raised from
inside `global_placement -timing_driven`, long before the router). The "best
achievable transition time" in that message is the minimum output slew over
`getSwappableCells(buffer_lowest_drive_)` — the equivalence class of the
WEAKEST buffer, filtered by `sizing_area_limit_` / `sizing_leakage_limit_`,
both defaulting to 4.0X *relative to that weakest buffer*. The weakest buffer
is by construction the library's lowest-leakage buffer, so in any library whose
buffer family spans more than 4X in leakage the check cannot see the strong
buffers the library ships: a pin `max_transition` the library meets with room
to spare is declared impossible and the run aborts.

Measured instance of the shape (0.18 um BCD library, hard-macro input pin
declaring 1.0 ns at its own 0.30 pF pin capacitance): the tool reported
"best achievable 1.205 ns" — the slew of the strongest buffer inside the 4X
leakage pool — while four stronger buffers in the SAME library produce
0.62 / 0.42 / 0.33 / 0.27 ns at that load and slow corner. With the pool
declared from the library, `repair_design` found and fixed 17 slew violations
instead of aborting.

These tests therefore assert the PROPERTY "the declared pool spans the loaded
library's own buffer family, and is never narrower than the tool default",
driving the ACTUAL emitted Tcl through tclsh against a synthetic library.
No design, PDK or vendor literal appears anywhere.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

# The tool's own defaults, which the declaration must never undercut.
TOOL_DEFAULT_LIMIT = 4.0


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="fixture_tapcell",
        antenna_diode_cell="fixture_diode",
        pnr_exclude_cell_file=None,
    )


def _emit_pnr_tcl(tmp_path: Path) -> str:
    """The COMPLETE pnr.tcl exactly as step_pnr builds it."""
    pdk = _pdk()
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    plan = R._build_spare_cells_plan(
        2000, 0.02, (10, 10, 290, 290), liberty_path="", container="")
    return R._build_pnr_tcl_text(
        tech_lef_c="/pdk/tech.lef", cell_lef_c="/pdk/cells.lef",
        macro_lefs_tcl="", liberty_c="/pdk/lib.lib",
        macro_libs_tcl="", netlist_c="/work/netlist.v", top="chip_top",
        sdc_c="/work/chip_top.sdc",
        dont_use_block=R._dont_use_family_fallback_tcl(),
        metal_prefix="met", die_w=300, die_h=300, core_pad=10,
        core_w=290, core_h=290, site="unithd", out_dir_c=str(out),
        tapcell_block="", pdn_block="", util=0.4,
        spare_protection_tcl=R._build_spare_protection_tcl(plan, str(out)),
        spare_postfix_tcl=R._build_spare_postfix_tcl(
            plan, tie_lo_cell="fixture_tielo", tie_lo_pin="LO"),
        clk_buf="fixture_clkbuf", clk_buf_root="fixture_clkbuf",
        routing_constraint_tcl="", pg_cleanup_block="",
        spef_repair_block="", antenna_repair_block="", filler_block="")


# ── the synthetic library the stub presents to the emitted program ───────────
# name -> (area, leakage). A family that spans 5.0X in area and 12.0X in
# leakage: wider than the tool's 4.0X default in BOTH dimensions.
WIDE_FAMILY = {"BUFA": (10.0, 1.0e-10),
               "BUFB": (20.0, 3.0e-10),
               "BUFC": (50.0, 12.0e-10)}
# A family that fits inside the tool default.
NARROW_FAMILY = {"BUFA": (10.0, 1.0e-10),
                 "BUFB": (10.0, 1.0e-10)}


def _stub_tcl(family: dict, set_opt_config_body: str) -> str:
    rows = "\n".join(
        "  set FAM({n}) [list {a} {l}]".format(n=n, a=a, l=l)
        for n, (a, l) in family.items())
    names = " ".join(family)
    return f"""
# ── stub of the OpenROAD/OpenSTA surface the emitted program talks to ────────
proc unknown {{args}} {{ return "" }}
array set FAM {{}}
{rows}
set BUFFERS [list {names}]
set CALLS {{}}

proc get_lib_cells {{args}} {{
  global BUFFERS FAM
  set pat [lindex $args end]
  if {{$pat eq "*"}} {{ return [concat $BUFFERS [list NOTABUFFER]] }}
  if {{[info exists FAM($pat)]}} {{ return [list $pat] }}
  return {{}}
}}
proc get_property {{obj prop}} {{
  global BUFFERS
  switch -exact -- $prop {{
    is_buffer {{ return [expr {{[lsearch -exact $BUFFERS $obj] >= 0 ? 1 : 0}}] }}
    dont_use  {{ return 0 }}
    name      {{ return $obj }}
  }}
  return ""
}}
namespace eval sta {{
  proc redirect_string_begin {{}} {{ set ::CAP "" ; set ::REDIR 1 }}
  proc redirect_string_end {{}} {{ set ::REDIR 0 ; return $::CAP }}
}}
proc report_equiv_cells {{args}} {{
  global FAM BUFFERS
  set base [lindex $args end]
  set b $FAM($base)
  set out "The following [llength $BUFFERS] cells are equivalent to $base:\\n"
  append out "=====================================================\\n"
  append out "          Cell        Area   Area Leakage  Leakage  VT\\n"
  append out "                     (um^2)  Ratio  (W)     Ratio  Type\\n"
  append out "=====================================================\\n"
  foreach c $BUFFERS {{
    set f $FAM($c)
    set ar [expr {{[lindex $f 0] / [lindex $b 0]}}]
    set lr [expr {{[lindex $f 1] / [lindex $b 1]}}]
    append out [format "%-20s %7.3f %5.2f %8.2e %5.2f   -\\n" \\
                 $c [lindex $f 0] $ar [lindex $f 1] $lr]
  }}
  set ::CAP $out
}}
{set_opt_config_body}
"""


# The call is recorded the moment it happens: the emitted PnR program may end
# in `exit`, so anything appended after it would never run.
_RECORDER = """
proc set_opt_config {args} {
  set fh [open $::env(RESULT) a] ; puts $fh $args ; close $fh
}
"""
_UNSUPPORTED = """
proc set_opt_config {args} { error "invalid command name \\"set_opt_config\\"" }
"""

_EPILOGUE = ""


def _run(tmp_path: Path, family: dict, body: str):
    script = tmp_path / "drv_pool_probe.tcl"
    result = tmp_path / "calls.txt"
    script.write_text(_stub_tcl(family, body) + _emit_pnr_tcl(tmp_path)
                      + _EPILOGUE)
    cp = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                        timeout=120, env={"RESULT": str(result),
                                          "PATH": "/usr/bin:/bin"})
    calls = result.read_text().strip() if result.is_file() else ""
    return cp, calls


def _limits(calls: str):
    """(area_limit, leakage_limit) as the emitted program declared them."""
    area = leak = None
    for key, setter in (("-sizing_area_limit", "area"),
                        ("-sizing_leakage_limit", "leak")):
        m = re.search(re.escape(key) + r"\s+([0-9.eE+-]+)", calls)
        if m:
            if setter == "area":
                area = float(m.group(1))
            else:
                leak = float(m.group(1))
    return area, leak


@needs_tclsh
def test_declared_pool_spans_the_librarys_own_buffer_family(tmp_path):
    """PROPERTY: for a library whose buffer family spans 5.0X in area and
    12.0X in leakage, the emitted program must declare a pool that reaches the
    whole family. Inheriting the tool's 4.0X default hides the strong buffers
    from the RSZ-0090 feasibility check and aborts a meetable constraint."""
    cp, calls = _run(tmp_path, WIDE_FAMILY, _RECORDER)
    assert cp.returncode == 0, cp.stderr
    area, leak = _limits(calls)
    assert area is not None and leak is not None, (
        "the emitted PnR program never declared a sizing pool "
        f"(set_opt_config calls: {calls!r}); it therefore inherits OpenROAD's "
        "4.0X default and cannot see this library's strong buffers")
    assert area >= 5.0, (
        f"declared area pool {area}X does not span the family's 5.0X spread")
    assert leak >= 12.0, (
        f"declared leakage pool {leak}X does not span the family's 12.0X "
        "spread — the buffers that meet a tight max_transition stay invisible")


@needs_tclsh
def test_declared_pool_is_never_narrower_than_the_tool_default(tmp_path):
    """PROPERTY: a compact library must not be given a POOL TIGHTER than the
    tool's own default. The declaration may only ADD reachable cells."""
    cp, calls = _run(tmp_path, NARROW_FAMILY, _RECORDER)
    assert cp.returncode == 0, cp.stderr
    area, leak = _limits(calls)
    assert area is not None and leak is not None, (
        f"no sizing pool declared for a compact library: {calls!r}")
    assert area >= TOOL_DEFAULT_LIMIT, area
    assert leak >= TOOL_DEFAULT_LIMIT, leak


@needs_tclsh
def test_pool_declaration_is_never_fatal_when_the_tool_cannot_take_it(tmp_path):
    """PROPERTY: an OpenROAD build without `set_opt_config` must still run the
    PnR program to completion. A disclosure knob may never become a new way to
    kill the flow. Direction-1 guard: it holds before AND after the fix."""
    cp, _ = _run(tmp_path, WIDE_FAMILY, _UNSUPPORTED)
    assert cp.returncode == 0, (
        "the emitted PnR program died because the sizing pool could not be "
        f"declared:\n{cp.stderr}")


@needs_tclsh
def test_pool_is_declared_before_the_first_optimization_command(tmp_path):
    """PROPERTY: the pool must be declared after the design is linked and
    constrained but BEFORE the first optimization — `global_placement
    -timing_driven` runs repair_design, and therefore the RSZ-0090 check,
    internally. A declaration after global_placement is too late."""
    text = _emit_pnr_tcl(tmp_path)
    i_sdc = text.index("read_sdc")
    i_gp = text.index("global_placement")
    i_pool = text.find("set_opt_config")
    assert i_pool != -1, "no sizing-pool declaration in the emitted PnR program"
    assert i_sdc < i_pool < i_gp, (
        f"sizing pool declared at {i_pool}, outside "
        f"(read_sdc={i_sdc}, global_placement={i_gp})")
