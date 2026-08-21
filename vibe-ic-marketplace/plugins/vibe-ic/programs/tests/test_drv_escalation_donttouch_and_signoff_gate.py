"""ORGANIC (caravel_user_project x sky130A, measured 2026-07-25) — the DRV
wire-length repeater escalation was disabled in v1.5.65 against a comparison
that could not be made, and carried two REAL defects that this test pins.

WHAT WAS MEASURED (one consistent full-enumeration chain, the SAME emitter the
downstream acceptance gate reads — `_emit_mcorner_ocv_sta` over the per-corner
SPEF set, `report_check_types ... -violators -max_count 2000`):

    route                         max_slew   total DRV   setup WNS
    base (no escalation)             421        483       +6.07 ns
    escalation, max_wire_length 973  177        219       +3.71 ns
    escalation, max_wire_length 400  180        260       -7.48 ns

DEFECT 1 — THE DISABLE RATIONALE WAS A NON-COMPARISON.
  v1.5.65 disabled the step citing "the REAL sign-off violator count got far
  WORSE (4->219)". The "4" came from a report emitted WITHOUT `-violators`,
  which makes OpenSTA print only the SINGLE WORST pin per check type — about
  four lines for ANY design, whatever its true population. `-violators` was
  added in the SAME commit that added the escalation, so "before" and "after"
  were two different report SHAPES, not two states of one design. Measured
  consistently the delta is 483->219, a ~55% reduction.

DEFECT 2 — THE PROMOTION GATE WAS CORNER-BLIND (real).
  The gate counted violators inside the escalation's own OpenROAD session,
  which reads ONE liberty (ss) and ONE captable (max-RC). The downstream gate
  reads SETUP@ss+max-RC *and* HOLD@ff+min-RC. Measured on the same route:
  step-local 330 vs downstream 483, and 330 is EXACTLY the setup subset
  (283 max_slew + 47 max_cap); the invisible 153 is EXACTLY the hold subset
  (138 max_slew + 15 max_cap). A change improving setup while wrecking hold
  satisfied `after < before` and got promoted.

DEFECT 3 — DONT_TOUCH WAS SILENTLY LOST ACROSS THE SESSION BOUNDARY (real).
  `set_dont_touch` is OpenROAD SESSION state; it is not a DEF attribute and
  does not survive write_def -> read_def. Every fresh-session optimisation
  therefore started with all spare / tie protection dropped. Placement status
  alone is not a sufficient substitute: measured, the design-for-ECO spares
  were `+ FIXED` but the tie DRIVER feeding their inputs was only `+ PLACED`.

HONEST SCOPE (§4.05): the dont_touch restore was measured NEUTRAL on this
design (byte-identical route with and without it). It is a correctness
hardening for a real, silent loss of protection — this test does NOT claim it
changes any particular DRV or LVS number.

chip-AGNOSTIC throughout: the restore predicates are (a) placement status and
(b) a master with zero signal INPUT terminals and >=1 signal OUTPUT — the
structural definition of a tie/constant cell in ANY library. No design, vendor,
cell or net literal anywhere.
"""
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


def _emit_escalation(tmp_path: Path) -> str:
    return R._ship_wire_length_escalation_tcl(
        top="chip_top",
        tech_lef_c=str(tmp_path / "tech.lef"),
        cell_lef_c=str(tmp_path / "cells.lef"),
        ss_liberty_c=str(tmp_path / "ss.lib"),
        pnr_dir_c=str(tmp_path / "pnr"),
        max_captable_c=str(tmp_path / "rules.magic"),
        metal_prefix="met",
        thread_count=4,
    )


# --------------------------- DEFECT 1: the record, and the REAL blocker ---

def test_promotion_is_off_behind_a_named_reviewable_flag():
    """Promotion stays OFF — but as a named, greppable policy constant with
    its evidence attached, not an anonymous `return None` buried in a
    docstring. Measured end-to-end: the escalated route improves DRV
    (483->219) yet regresses sign-off DRC (1->123) and LVS (MATCH->MISMATCH),
    so an unpromoted (=incumbent) route is the correct outcome."""
    assert R._DRV_ESCALATION_PROMOTION_ENABLED is False
    assert R.step_signoff_drv_wire_length_repair(
        Path("/nonexistent"), "chip_top", object(), "c") is None


def test_disable_rationale_records_the_non_comparison_and_the_real_blocker():
    """The docstring must carry (a) why the OLD rationale was unusable and
    (b) the REAL, measured blocker — so the step is neither re-enabled on the
    old bad number nor left disabled for an unexamined reason."""
    doc = R.step_signoff_drv_wire_length_repair.__doc__ or ""
    # (a) the old rationale was a report-SHAPE artefact
    assert "-violators" in doc
    assert "483" in doc and "219" in doc
    # (b) the real blocker is named, with both regressed sign-off axes
    assert "123" in doc, "the measured sign-off DRC regression must be recorded"
    assert "LVS_MISMATCH" in doc or "MISMATCH" in doc
    # (c) and the exit criterion for re-enabling is stated
    assert "RE-ENABLE" in doc.upper()


def test_policy_constant_documents_both_regressed_signoff_axes():
    """A future reader must be able to grep the constant and learn why."""
    import inspect
    src = inspect.getsource(R)
    i = src.index("_DRV_ESCALATION_PROMOTION_ENABLED")
    ctx = src[max(0, i - 1400):i + 200]
    assert "DRC" in ctx and "LVS" in ctx
    assert "detailed_route" in ctx, (
        "the note must say WHICH weak evidence the old gate used")


# ----------------------------------- DEFECT 2: gate reads the REAL report ---

def test_promotion_measures_the_downstream_signoff_population():
    """REGRESSION GUARD: the step must decide promotion from
    `_measure_signoff_drv_population` (which runs the SAME emitter over the
    SAME per-corner SPEF set the acceptance gate reads), never from the
    corner-blind in-session count parsed out of its own transcript."""
    import inspect
    body = inspect.getsource(R.step_signoff_drv_wire_length_repair)
    assert "_measure_signoff_drv_population" in body
    # the ss-only counts must NOT be what feeds the promote predicate
    m = re.search(r"_ship_escalation_should_promote\((.*?)\)\s*$",
                  body, re.S | re.M)
    assert m, "promote predicate call not found"
    call = m.group(1)
    assert "sg_before" in call and "sg_after" in call, (
        "the promote predicate is being fed the step-local ss-only counts "
        "again; it must receive the downstream sign-off population")


def test_measure_signoff_population_counts_both_corners(tmp_path, monkeypatch):
    """The counter must count EVERY VIOLATED line in the multi-corner report —
    setup and hold — not just the section it happens to read first. Uses the
    measured caravel shape: 283+47 setup, 138+15 hold => 483."""
    rpt_body = ["=== SETUP corner: process=SS ===", "max slew"]
    rpt_body += [f"pin{i}/A 1.50 9.0 -7.5 (VIOLATED)" for i in range(283)]
    rpt_body += ["max capacitance"]
    rpt_body += [f"pin{i}/A 1.02 3.0 -2.0 (VIOLATED)" for i in range(47)]
    rpt_body += ["=== HOLD corner: process=FF ===", "max slew"]
    rpt_body += [f"h{i}/A 1.50 9.0 -7.5 (VIOLATED)" for i in range(138)]
    rpt_body += ["max capacitance"]
    rpt_body += [f"h{i}/A 1.02 3.0 -2.0 (VIOLATED)" for i in range(15)]

    proj = tmp_path / "proj"
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    monkeypatch.setattr(R._pl, "pnr_dir", lambda p: pnr)
    monkeypatch.setattr(R, "_emit_spef_corners",
                        lambda *a, **k: {"nom": pnr / "n.spef"})
    monkeypatch.setattr(R, "_resolve_signoff_corner_libs",
                        lambda *a, **k: {"SS": "ss.lib", "FF": "ff.lib"})

    def _fake_emit(project, top, pdk, container, corner_libs, corner_spefs,
                   nom_spef, rpt_out, notes, netlist_override=None):
        rpt_out.parent.mkdir(parents=True, exist_ok=True)
        rpt_out.write_text("\n".join(rpt_body))
        return True

    monkeypatch.setattr(R, "_emit_mcorner_ocv_sta", _fake_emit)
    n = R._measure_signoff_drv_population(proj, "chip_top", object(),
                                          "c", "t", [])
    assert n == 483, f"expected the full both-corner population, got {n}"
    # and the setup-only subset (the old, blind number) must NOT be the answer
    assert n != 330


def test_measure_signoff_population_refuses_when_unmeasurable(tmp_path,
                                                             monkeypatch):
    """§4.05 — an unmeasurable quantity must return None (=> refuse to
    promote), never a guess that could green-light a regression."""
    proj = tmp_path / "proj"
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    monkeypatch.setattr(R._pl, "pnr_dir", lambda p: pnr)
    monkeypatch.setattr(R, "_emit_spef_corners", lambda *a, **k: {})
    monkeypatch.setattr(R, "_resolve_signoff_corner_libs", lambda *a, **k: {})
    assert R._measure_signoff_drv_population(
        proj, "chip_top", object(), "c", "t", []) is None


@pytest.mark.parametrize("before,after,expect", [
    (483, 219, True),     # the measured improvement
    (483, 483, False),    # no improvement => never promote
    (219, 260, False),    # the L=400 measured regression
    (None, 219, False),   # unmeasurable incumbent => refuse
    (483, None, False),   # unmeasurable candidate => refuse
])
def test_promote_predicate_on_downstream_counts(before, after, expect):
    assert R._ship_escalation_should_promote(
        {"route_violations": 0, "wns_after": 3.71,
         "before_count": before, "after_count": after},
        True, True) is expect


def test_promote_refuses_when_setup_went_negative():
    """The measured L=400 variant drove setup WNS to -7.48 ns; even had its
    count improved, a negative-setup route must never be promoted."""
    assert R._ship_escalation_should_promote(
        {"route_violations": 0, "wns_after": -7.48,
         "before_count": 483, "after_count": 219}, True, True) is False


# ------------------------------- DEFECT 3: dont_touch restored in-session ---

def test_escalation_restores_dont_touch_before_first_repair(tmp_path):
    """`set_dont_touch` is SESSION state and cannot survive write_def/read_def,
    so this fresh session must re-assert it BEFORE the first repair_design."""
    tcl = _emit_escalation(tmp_path)
    assert "set_dont_touch" in tcl
    assert tcl.index("set_dont_touch") < tcl.index("repair_design"), (
        "dont_touch must be restored before the first netlist-mutating pass")
    assert "SHIP_ESC_DONT_TOUCH_RESTORED" in tcl


def test_dont_touch_restore_is_chip_agnostic():
    """No design / vendor / cell / net literal may appear — protection is
    derived from placement status and MTerm directions only."""
    tcl = R._build_dont_touch_restore_tcl()
    low = tcl.lower()
    for banned in ("sky130", "gf180", "asap7", "ihp", "conb", "tielo",
                   "tiehi", "caravel", "user_project", "spare_"):
        assert banned not in low, f"chip/PDK literal leaked: {banned}"
    # the two structural predicates must both be present
    assert "getPlacementStatus" in tcl
    assert "getIoType" in tcl and "getMTerms" in tcl


@needs_tclsh
def test_dont_touch_restore_protects_tie_driver_and_locked_insts(tmp_path):
    """Execute the restore fragment against a stubbed ODB holding the MEASURED
    shape: a FIXED spare, a PLACED tie driver (zero signal inputs, one signal
    output), and an ordinary PLACED logic cell. It must protect the first two
    and the tie net — and must NOT protect ordinary logic (that would freeze
    the very cells the escalation needs to rebuffer)."""
    stub = (
        "set ::touched {}\n"
        "set ::touched_nets {}\n"
        "proc set_dont_touch {obj} {\n"
        "  if {[string match net:* $obj]} { lappend ::touched_nets $obj } "
        "else { lappend ::touched $obj }\n"
        "}\n"
        "proc get_nets {n} { return net:$n }\n"
        # --- stub ODB --------------------------------------------------
        # inst: name status mterms(dir,sig) iterms(net)
        "proc _mt {dir sig} { return [list $dir $sig] }\n"
        "proc _inst_spare {cmd args} {\n"
        "  switch $cmd {\n"
        "    getName {return spare_lock}\n"
        "    getMaster {return _m_logic}\n"
        "    getPlacementStatus {return FIRM}\n"
        "    getITerms {return {_it_a}}\n"
        "  }\n}\n"
        "proc _inst_tie {cmd args} {\n"
        "  switch $cmd {\n"
        "    getName {return tie_drv}\n"
        "    getMaster {return _m_tie}\n"
        "    getPlacementStatus {return PLACED}\n"
        "    getITerms {return {_it_tie}}\n"
        "  }\n}\n"
        "proc _inst_logic {cmd args} {\n"
        "  switch $cmd {\n"
        "    getName {return u_logic}\n"
        "    getMaster {return _m_logic}\n"
        "    getPlacementStatus {return PLACED}\n"
        "    getITerms {return {_it_b}}\n"
        "  }\n}\n"
        "proc _inst_fill {cmd args} {\n"
        "  switch $cmd {\n"
        "    getName {return fill0}\n"
        "    getMaster {return _m_fill}\n"
        "    getPlacementStatus {return FIRM}\n"
        "    getITerms {return {}}\n"
        "  }\n}\n"
        "proc _m_logic {cmd} { if {$cmd eq \"getMTerms\"} "
        "{ return {_mt_in _mt_out} } }\n"
        "proc _m_tie   {cmd} { if {$cmd eq \"getMTerms\"} "
        "{ return {_mt_out} } }\n"
        "proc _m_fill  {cmd} { if {$cmd eq \"getMTerms\"} "
        "{ return {_mt_pwr} } }\n"
        "proc _mt_in  {cmd} { if {$cmd eq \"getSigType\"} { return SIGNAL } "
        "elseif {$cmd eq \"getIoType\"} { return INPUT } }\n"
        "proc _mt_out {cmd} { if {$cmd eq \"getSigType\"} { return SIGNAL } "
        "elseif {$cmd eq \"getIoType\"} { return OUTPUT } }\n"
        "proc _mt_pwr {cmd} { if {$cmd eq \"getSigType\"} { return POWER } "
        "elseif {$cmd eq \"getIoType\"} { return INPUT } }\n"
        "proc _it_a   {cmd} { if {$cmd eq \"getNet\"} { return _net_a } }\n"
        "proc _it_b   {cmd} { if {$cmd eq \"getNet\"} { return _net_b } }\n"
        "proc _it_tie {cmd} { if {$cmd eq \"getNet\"} { return _net_tie } }\n"
        "proc _net_a   {cmd} { if {$cmd eq \"getName\"} { return na } "
        "elseif {$cmd eq \"getSigType\"} { return SIGNAL } }\n"
        "proc _net_b   {cmd} { if {$cmd eq \"getName\"} { return nb } "
        "elseif {$cmd eq \"getSigType\"} { return SIGNAL } }\n"
        "proc _net_tie {cmd} { if {$cmd eq \"getName\"} { return tie_net } "
        "elseif {$cmd eq \"getSigType\"} { return SIGNAL } }\n"
        "proc _block {cmd args} { if {$cmd eq \"getInsts\"} "
        "{ return {_inst_spare _inst_tie _inst_logic _inst_fill} } }\n"
        "namespace eval ord { proc get_db_block {} { return _block } }\n"
    )
    script = tmp_path / "dt.tcl"
    script.write_text(stub + R._build_dont_touch_restore_tcl() +
                      "\nputs \"INSTS: $::touched\"\n"
                      "puts \"NETS: $::touched_nets\"\n")
    r = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    insts = re.search(r"INSTS: (.*)", r.stdout).group(1)
    nets = re.search(r"NETS: (.*)", r.stdout).group(1)
    # (a) the flow-LOCKED spare is protected
    assert "spare_lock" in insts
    # (b) the tie DRIVER is protected even though it is only PLACED — the
    #     measured case a placement-status-only rule would have missed
    assert "tie_drv" in insts
    #     ...and so is the tie net, so it can never be merged/rebuffered
    assert "tie_net" in nets
    # ordinary PLACED logic stays TOUCHABLE (else nothing could be repaired)
    assert "u_logic" not in insts
    assert "nb" not in nets
    # physical-only cells are skipped entirely (cheap on big dies)
    assert "fill0" not in insts
    assert "SHIP_ESC_DONT_TOUCH_RESTORED" in r.stdout


@needs_tclsh
def test_restore_fragment_is_valid_tcl_standalone(tmp_path):
    """The fragment must parse even with nothing bound (every ODB call is
    inside the guarded catch), so it can never abort a real session."""
    script = tmp_path / "parse.tcl"
    script.write_text("proc unknown {args} { return {} }\n"
                      + R._build_dont_touch_restore_tcl())
    r = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert "SHIP_ESC_DONT_TOUCH_RESTORED" in r.stdout
