"""RESIZER SIZING LIMITS — a chip-AGNOSTIC Phase-3 defect found on a real
multi-supply hard-macro design and invisible to every gate that ran at the time.

`PreChecks::checkSlewLimit` computes the best achievable transition over
`getSwappableCells(buffer_lowest_drive_)`, and `getSwappableCells` drops any
candidate more than `sizing_area_limit_` / `sizing_leakage_limit_` (BOTH
default 4.0) times the current cell's. On a library whose buffer family spans
wider than 4X — which is every library measured here, open or commercial — the
weakest buffer cannot see the strong ones, "best achievable" is computed from a
crippled pool, and `repair_design` ABORTS with [ERROR RSZ-0090] against a
max_transition the library can in fact meet.

The fix does NOT widen the timing constraint. `max_transition` is untouched;
what is restored is the resizer's SWAP POOL, whose 4.0X area/leakage cut-off
(`getSwappableCells`) is a cost heuristic, not a statement about the library's
contents. The VALUE is the library's own measured buffer-family span, so a
library that already fits inside 4X is never touched. The block must be emitted
BEFORE the first timing-driven step, because RSZ-0090 is a fatal error raised
from `global_placement -timing_driven`.

Pins the EMISSION contract; no OpenROAD needed.
"""
import importlib
import math
import re

R = importlib.import_module("phase3_one_shot_runner")


def _stmt_prefix(tcl, statement):
    """Offset of the first line that STARTS with ``statement`` — for commands
    that carry flags (`global_placement -routability_driven ...`). Comment
    lines start with `#`, so the prose that discusses the command is skipped."""
    off = 0
    for line in tcl.splitlines(keepends=True):
        if line.startswith(statement):
            return off
        off += len(line)
    raise AssertionError(f"no line starts with {statement!r}")



# ------------------------------------------------------- B. SIZING LIMITS ---

def _lib(name, cells):
    """Minimal liberty text: ``cells`` is [(cell, area, leakage), ...]."""
    out = [f'library ({name}) {{']
    for cell, area, leak in cells:
        out.append(f"""  cell ("{cell}") {{
    area : {area};
    cell_leakage_power : {leak};
    pin (A) {{ direction : input; capacitance : 0.01; }}
    pin (Z) {{ direction : output; function : "A";
      timing () {{ related_pin : "A"; cell_rise (t) {{ values("1,2"); }} }}
    }}
  }}""")
    out.append("}")
    return "\n".join(out)


_NARROW = _lib("narrow", [("BUFX1", 10.0, 1.0), ("BUFX2", 20.0, 2.0),
                          ("BUFX4", 35.0, 3.5)])            # 3.5X / 3.5X
_WIDE = _lib("wide", [("BUFX1", 10.0, 1.0), ("BUFX8", 80.0, 40.0)])  # 8X / 40X
_WIDER = _lib("wider", [("BUFX1", 10.0, 1.0), ("BUFX16", 160.0, 90.0)])


def test_buffer_family_is_inferred_structurally():
    fam = {c for c, _, _ in R._liberty_buffer_family(_NARROW)}
    assert fam == {"BUFX1", "BUFX2", "BUFX4"}


def test_inverters_and_logic_gates_are_not_counted_as_buffers():
    # an inverter (function "!A") and a 2-input gate must not enter the span,
    # or the measured ratio would be the whole library's, not the family's.
    txt = _lib("mix", [("BUFX1", 10.0, 1.0)]) + """
library (extra) {
  cell ("INVX1") {
    area : 5.0; cell_leakage_power : 0.5;
    pin (A) { direction : input; }
    pin (Z) { direction : output; function : "!A"; }
  }
  cell ("NAND2X1") {
    area : 7.0; cell_leakage_power : 0.7;
    pin (A) { direction : input; }
    pin (B) { direction : input; }
    pin (Z) { direction : output; function : "!(A B)"; }
  }
}"""
    assert {c for c, _, _ in R._liberty_buffer_family(txt)} == {"BUFX1"}


def test_library_within_openroad_default_limits_is_left_alone():
    # A library whose family fits inside 4X needs nothing; emitting anything
    # here would change optimisation for a design that never had the problem.
    assert R._sizing_limits_preamble_tcl([_NARROW]) == ""
    assert R._sizing_limits_preamble_tcl([]) == ""
    assert R._sizing_limits_drv_report_tcl([_NARROW]) == ""


def _limits(tcl):
    m = re.search(r"-limit_sizing_area ([\d.]+) -limit_sizing_leakage "
                  r"([\d.]+)", tcl)
    return (float(m.group(1)), float(m.group(2)))


def _expect(span, margin=1.1):
    """The limit is the measured span x margin, rounded UP to 2dp — rounding
    DOWN could land back under the span it was measured from."""
    return math.ceil(span * margin * 100.0) / 100.0


def test_limits_are_measured_from_the_library_not_a_constant():
    # THE defect-present test. A blanket relaxation — any fixed pair of
    # numbers — passes "the violation disappeared" and fails THIS: two
    # libraries with different spans must produce different limits, each
    # traceable to its own measured span.
    a = _limits(R._sizing_limits_preamble_tcl([_WIDE]))
    b = _limits(R._sizing_limits_preamble_tcl([_WIDER]))
    assert a != b
    assert a[0] == _expect(8.0)      # 80/10 area span, x1.1 margin
    assert a[1] == _expect(40.0)     # 40/1  leakage span
    assert b[0] == _expect(16.0)
    assert b[1] == _expect(90.0)
    # and never below the span it was measured from
    assert a[0] >= 8.0 and a[1] >= 40.0
    assert b[0] >= 16.0 and b[1] >= 90.0


def test_span_is_the_widest_across_every_signoff_corner():
    # leakage span is corner-dependent; the limit has to cover the worst one,
    # or the escalation helps at tt and still aborts at the ss sign-off corner.
    both = _limits(R._sizing_limits_preamble_tcl([_WIDE, _WIDER]))
    assert both == _limits(R._sizing_limits_preamble_tcl([_WIDER]))


def test_only_the_cell_pool_is_widened_never_the_slew_target():
    # The one thing that must never happen: the fix must not touch
    # max_transition / max_capacitance. It restores the swap pool; the timing
    # constraint is left exactly as the liberty and the SDC declare it.
    tcl = R._sizing_limits_preamble_tcl([_WIDE])
    assert "set_opt_config" in tcl
    assert "set_max_transition" not in tcl
    assert "set_max_capacitance" not in tcl
    assert "set_max_fanout" not in tcl
    assert "SIZING_LIMITS_APPLIED" in tcl
    # a failure to apply is surfaced, never swallowed
    assert "SIZING_LIMITS_NONFATAL" in tcl


def _pnr(**kw):
    base = dict(
        tech_lef_c="/x/tech.lef", cell_lef_c="/x/cell.lef",
        macro_lefs_tcl="", liberty_c="/x/c.lib", macro_libs_tcl="",
        netlist_c="/x/d.v", top="d", sdc_c="/x/d.sdc", dont_use_block="",
        metal_prefix="met", die_w=100, die_h=100, core_pad=10,
        core_w=90, core_h=90, site="unit", out_dir_c="/out",
        tapcell_block="", pdn_block="", util=0.3,
        spare_protection_tcl="", spare_postfix_tcl="",
        clk_buf="BUF", clk_buf_root="BUF", routing_constraint_tcl="",
        pg_cleanup_block="", spef_repair_block="",
        antenna_repair_block="", filler_block="")
    base.update(kw)
    return R._build_pnr_tcl_text(**base)


def test_sizing_limits_precede_the_first_timing_driven_step():
    """THE defect-present test for the placement of this fix.

    RSZ-0090 is raised by PreChecks::checkSlewLimit, which is reached from
    `global_placement -timing_driven` (gpl/nesterovPlace.cpp:460 ->
    timingBase.cpp:128 findResizeSlacks -> RepairDesign -> checkSlewLimit) —
    NOT only from the explicit `repair_design` further down. It is a
    logger_->error, so it ABORTS the script. A sizing-limit block emitted after
    `repair_design` therefore never executes: measured on a real run, the abort
    was at the `global_placement` line while the block sat 262 lines below it.

    So the invariant is positional: set_opt_config must precede
    `global_placement`, and `global_placement` must precede `repair_design`
    (asserted too, so this test cannot silently pass by the template being
    reordered underneath it).
    """
    tcl = _pnr(sizing_limits_block=R._sizing_limits_preamble_tcl([_WIDE]),
               sizing_drv_report_block=R._sizing_limits_drv_report_tcl([_WIDE]))
    cfg = tcl.index("set_opt_config")
    gp = _stmt_prefix(tcl, "global_placement")
    rd = tcl.index("{repair_design}")
    assert cfg < gp, (
        "set_opt_config is emitted after global_placement; RSZ-0090 aborts "
        "there, so the restored pool would never be seen")
    assert gp < rd          # the template really does place gp first
    # the DRV evidence, by contrast, belongs AFTER repair_design
    assert rd < tcl.index("SIZING_LIMITS_DRV_AFTER_REPAIR")


def test_drv_report_is_evidence_only_and_changes_nothing():
    # The post-repair block exists to show what the restored pool bought. If it
    # ever starts acting (another repair_design, another set_opt_config) the
    # before/after number stops being an independent measurement.
    rep = R._sizing_limits_drv_report_tcl([_WIDE])
    assert "sta::max_slew_violation_count" in rep
    assert "sta::max_capacitance_violation_count" in rep
    assert "set_opt_config" not in rep
    # no EXECUTABLE optimisation command — the word may appear in the comment
    # and in the printed message, which is prose, not an action.
    for line in rep.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("puts "):
            continue
        assert "repair_design" not in s, f"report block acts: {s!r}"
        assert "repair_timing" not in s, f"report block acts: {s!r}"
    assert "SIZING_LIMITS_DRV_UNMEASURED" in rep   # counters absent != 0


def test_sizing_escalation_is_absent_when_not_supplied():
    tcl = _pnr()
    assert "SIZING_LIMITS" not in tcl
    assert "set_opt_config" not in tcl


# ── the liberty is parsed ONCE, not once per consumer ─────────────────────
def test_measured_spans_are_reused_instead_of_reparsed(monkeypatch):
    """THE COST DEFECT, pinned by COUNTING the parses rather than timing them.

    Three consumers need the same span: the preamble, the DRV-report companion,
    and `step_pnr`'s own disclosure. The parse is O(liberty bytes) over a whole
    sign-off corner set, so asking each consumer to measure for itself is not a
    small inefficiency. Measured on the real 3-corner sky130_fd_sc_hd set
    (96.9 MB): one pass 26.6 s, three passes 81.5 s — 54.9 s per PnR spent
    recomputing a value already in hand.

    A timing assertion would be flaky and would not say WHY. The parse COUNT is
    the actual property: given a measured span, a consumer must not parse at
    all. Delete the `spans` forwarding and the count goes to 2 and this fails.
    """
    calls = {"n": 0}
    real = R._buffer_family_sizing_spans

    def counting(lib_texts):
        calls["n"] += 1
        return real(lib_texts)

    monkeypatch.setattr(R, "_buffer_family_sizing_spans", counting)

    # the caller measures once...
    spans = real([_WIDE])
    calls["n"] = 0
    # ...and neither emitter may measure again.
    pre = R._sizing_limits_preamble_tcl([_WIDE], spans=spans)
    rep = R._sizing_limits_drv_report_tcl([_WIDE], spans=spans)
    assert calls["n"] == 0, (
        f"a pre-measured span was handed in and the emitters parsed the "
        f"liberty {calls['n']} more time(s) anyway")

    # and the answer must be IDENTICAL to the self-measuring path — a fast
    # wrong number is worse than a slow right one.
    calls["n"] = 0
    assert pre == R._sizing_limits_preamble_tcl([_WIDE])
    assert rep == R._sizing_limits_drv_report_tcl([_WIDE])
    assert calls["n"] == 2, "the no-spans path must still measure for itself"


def test_step_pnr_measures_the_corner_set_once(monkeypatch):
    """The wiring half: `step_pnr` must hand its measured spans to BOTH
    emitters. Asserted on the call site because driving the whole step needs a
    container and a PDK; the mechanism itself is pinned behaviourally above."""
    import inspect
    src = inspect.getsource(R.step_pnr)
    i = src.index("_sl_spans = ")
    window = src[i:i + 700]
    assert "_sizing_limits_preamble_tcl(_sl_texts, spans=_sl_spans)" in window
    assert "spans=_sl_spans)" in window.split("drv_report_tcl", 1)[1], (
        "the DRV-report emitter re-parses instead of reusing the measurement")
    # the disclosure reuses the same tuple rather than measuring a fourth time
    assert "_sl_a, _sl_l, _sl_n = _sl_spans" in window
    assert window.count("_buffer_family_sizing_spans(") == 1, (
        "step_pnr measures the corner set more than once")
