#!/usr/bin/env python3
"""vibe-ic#762 — a staged macro's NON-SEQUENTIAL timing requirement must reach
the integration BEFORE post-CTS, and the post-CTS FAIL must name the arc kind.

The measured defect: a vendor hard macro staged under `input/pdk_local/`
declared `non_seq_setup_rising` / `non_seq_hold_falling` arcs (a 9.00 ns
address-stable-around-strobe window). The generated integration drove the
constrained pin straight from a rising-edge flop, and the FIRST report of it
was Step 20's `HOLD_SLACK_NEGATIVE ... -8.68` — a verdict whose own wording
("re-CTS / insert delay cells") names the one repair that provably cannot close
an 8.68 ns DATA-path hold violation.

TWO THINGS ARE ASSERTED, and they are independent:
  * the EARLY finding exists (Step 7, from the macro's own Liberty), names the
    macro, the pin pair, the window and what the integration must do; and
  * the LATE hard failure is NOT suppressed — `hold_closure_check` still FAILs
    with `HOLD_SLACK_NEGATIVE`, only now it names the arc kind.

EXPLICIT NEGATIVE CONTROLS throughout: every FAIL assertion has a sibling that
must PASS/SKIP, because a check that cannot pass and a check that cannot fail
are equally worthless. In particular the std-cell population is pinned: an
open-source std-cell Liberty carries 24 `non_seq_*` arcs (SET/RESET recovery
windows), and a gate that fired on those would fire on every design ever
synthesised.

All fixtures are SYNTHESIZED neutral data — invented cell, pin and net names.
No real design, PDK, vendor or part number appears anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "macro_non_seq_arc_contract_check.py"
HOLD_GATE = PROGRAMS / "hold_closure_check.py"
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))


# --------------------------------------------------------------------------- #
# SYNTHESIZED neutral fixtures
# --------------------------------------------------------------------------- #
def _macro_lib(hold_ns: float = 9.0, setup_ns: float = 8.0,
               cell: str = "NEUTRAL_NVM_1024X8") -> str:
    """A hard-macro Liberty with a non-sequential window between two SIGNAL
    pins, plus an ordinary clocked output arc the parse must not confuse."""
    return f"""library (neutral_ff) {{
  time_unit : "1ns";
  cell ({cell}) {{
    is_macro_cell : true;
    pin (PRD) {{ direction : input; }}
    pin (PCLK) {{ direction : input; clock : true; }}
    bus (PA) {{
      direction : input;
      pin (PA[0]) {{
        direction : input;
        timing () {{
          related_pin : "PRD";
          timing_type : "non_seq_setup_rising";
          rise_constraint (scalar) {{ values("{setup_ns:.6f}"); }}
        }}
        timing () {{
          related_pin : "PRD";
          timing_type : "non_seq_hold_falling";
          rise_constraint (scalar) {{ values("{hold_ns:.6f}"); }}
        }}
      }}
    }}
    pin (PQ) {{
      direction : output;
      timing () {{
        related_pin : "PCLK";
        timing_type : "rising_edge";
        cell_rise (scalar) {{ values("1.2"); }}
      }}
    }}
  }}
}}
"""


_MACRO_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_NVM_1024X8
  CLASS BLOCK ;
  SIZE 120.0 BY 90.0 ;
  PIN PA[0]
    DIRECTION INPUT ;
    USE SIGNAL ;
  END PA[0]
  PIN PRD
    DIRECTION INPUT ;
    USE SIGNAL ;
  END PRD
END NEUTRAL_NVM_1024X8
END LIBRARY
"""

# A std cell that ALSO carries non_seq_* arcs (set/reset recovery windows are
# exactly this shape in real open-source libraries). It must never be judged.
_STDCELL_LIB = """library (neutral_core) {
  time_unit : "1ns";
  cell (NEUTRAL_CORE_DFSR) {
    pin (SET_N) {
      direction : input;
      timing () {
        related_pin : "RESET_N";
        timing_type : "non_seq_hold_rising";
        rise_constraint (scalar) { values("0.401"); }
      }
    }
  }
}
"""

_STDCELL_LEF = """VERSION 5.7 ;
MACRO NEUTRAL_CORE_DFSR
  CLASS CORE ;
  SIZE 1.0 BY 2.0 ;
END NEUTRAL_CORE_DFSR
END LIBRARY
"""

_RTL = """module neutral_top (
  input wire clk, input wire rst_n,
  input wire [1:0] addr_in, input wire rd_in, output wire q_out
);
  reg [1:0] addr_q; reg rd_q;
  always @(posedge clk) begin addr_q <= addr_in; rd_q <= rd_in; end
  NEUTRAL_NVM_1024X8 u_nvm (.PA(addr_q), .PRD(rd_q), .PCLK(clk), .PQ(q_out));
endmodule
"""

_RTL_NO_MACRO = """module neutral_top (input wire clk, output reg q_out);
  always @(posedge clk) q_out <= ~q_out;
endmodule
"""


def _project(tmp_path: Path, *, period_ns: float = 10.0,
             hold_ns: float = 9.0, rtl: str = _RTL,
             lib_subdir: str = "input/pdk_local/neutralmem",
             lib_text: str | None = None,
             lef_text: str | None = _MACRO_LEF) -> Path:
    proj = tmp_path / "proj"
    libdir = proj / lib_subdir
    libdir.mkdir(parents=True, exist_ok=True)
    (libdir / "macro.lib").write_text(
        lib_text if lib_text is not None else _macro_lib(hold_ns=hold_ns))
    if lef_text is not None:
        (libdir / "macro.lef").write_text(lef_text)
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "neutral_top.v").write_text(rtl)
    sdc_dir = proj / "phase2" / "stage2" / "constraints"
    sdc_dir.mkdir(parents=True, exist_ok=True)
    (sdc_dir / "neutral_top.sdc").write_text(
        f"create_clock -name clk -period {period_ns:.3f} [get_ports clk]\n")
    (proj / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    return proj


def _record(proj: Path, requirement_ns, pin="PA[0]", related="PRD",
            cell="NEUTRAL_NVM_1024X8") -> None:
    """Write the design's own structured macro-timing record into its L-docs."""
    doc = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    entries = []
    for kind in ("non_seq_setup_rising", "non_seq_hold_falling"):
        e = {"macro": cell, "constrained_pin": pin, "related_pin": related,
             "timing_type": kind}
        if requirement_ns is not None:
            e["requirement_ns"] = requirement_ns
        entries.append(e)
    doc.write_text(json.dumps(
        {"layer": "L9", "fields": {"macro_timing_requirements": entries}},
        indent=2))


def _run(project: Path, out: Path | None = None):
    argv = [sys.executable, str(GATE), str(project)]
    if out is not None:
        argv += ["--json", str(out)]
    # 55s, not 300s: the CI harness runs this file under `pytest --timeout=180`,
    # so a 300s inner bound can never fire — the harness kills the SESSION first
    # and the failure is reported against whatever test happened to be running.
    # MEASURED on this file: the slowest test in it is 0.32s wall, and that one
    # is a pure in-process parse; every `_run` here launches the gate over a
    # tmp_path tree of a few hundred bytes. 55s is the bound the repo already
    # uses for exactly this shape (9 other test modules), and it leaves ~170x
    # headroom over the measured worst case.
    return subprocess.run(argv, capture_output=True, text=True, timeout=55)


# --------------------------------------------------------------------------- #
# 1. The Liberty parse itself
# --------------------------------------------------------------------------- #
def test_liberty_walk_attributes_each_arc_to_its_pin_pair_and_window():
    import macro_non_seq_arc_contract_check as m
    arcs = m.parse_non_seq_arcs(_macro_lib())
    assert len(arcs) == 2, arcs
    by_kind = {a["timing_type"]: a for a in arcs}
    assert set(by_kind) == {"non_seq_setup_rising", "non_seq_hold_falling"}
    hold = by_kind["non_seq_hold_falling"]
    assert hold["cell"] == "NEUTRAL_NVM_1024X8"
    assert hold["constrained_pin"] == "PA[0]"   # the enclosing pin, not the bus
    assert hold["related_pin"] == "PRD"
    assert hold["window_ns"] == pytest.approx(9.0)
    # the ordinary clocked output arc is NOT a non-sequential requirement
    assert all(a["timing_type"] != "rising_edge" for a in arcs)


def test_liberty_walk_ignores_a_non_seq_token_that_is_not_a_timing_type():
    """A grep would fire on the word; a brace-scoped walk must not."""
    import macro_non_seq_arc_contract_check as m
    decoy = """library (d) {
      cell (NEUTRAL_X) {
        pin (A) {
          comment : "characterised with non_seq_hold_falling methodology";
          timing () { related_pin : "B"; timing_type : "setup_rising";
                      rise_constraint (scalar) { values("9.0"); } }
        }
      }
    }
    """
    assert m.parse_non_seq_arcs(decoy) == []


# --------------------------------------------------------------------------- #
# 2. NSQ-1 — the measured defect, and its negative control
# --------------------------------------------------------------------------- #
def test_unrecorded_arc_fails_and_names_macro_pins_window_and_repair(tmp_path):
    proj = _project(tmp_path)
    out = tmp_path / "r.json"
    r = _run(proj, out)
    assert r.returncode == 1, r.stdout + r.stderr
    txt = r.stdout
    assert "NSQ-1" in txt
    for token in ("NEUTRAL_NVM_1024X8", "PA[0]", "PRD", "9.0"):
        assert token in txt, (token, txt)
    # it must say what the INTEGRATION has to do, and say that delay cells
    # cannot do it — the misdirection that cost a round.
    assert "hold the driving register" in txt
    assert "hold-buffer insertion cannot close it" in txt
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert data["contract_entry_count"] == 0
    kinds = {f["rule"] for f in data["findings"]}
    assert kinds == {"NSQ-1"}
    assert {a["timing_type"] for a in data["arcs"]} == {
        "non_seq_setup_rising", "non_seq_hold_falling"}


def test_recorded_arc_passes(tmp_path):
    """NEGATIVE CONTROL: the same design, with the requirement recorded in the
    layer the integration consumes, must PASS."""
    proj = _project(tmp_path)
    _record(proj, 9.0)
    out = tmp_path / "r.json"
    r = _run(proj, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert json.loads(out.read_text())["verdict"] == "PASS"


# --------------------------------------------------------------------------- #
# 3. NSQ-2 — a record that understates the requirement
# --------------------------------------------------------------------------- #
def test_understated_record_fails(tmp_path):
    proj = _project(tmp_path)
    _record(proj, 2.0)                     # macro asks 9.0
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "NSQ-2" in r.stdout
    assert "SMALLER than the 9.0 ns" in r.stdout


def test_record_without_a_number_fails(tmp_path):
    proj = _project(tmp_path)
    _record(proj, None)
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "NSQ-2" in r.stdout
    assert "NO numeric window" in r.stdout


def test_record_that_meets_or_exceeds_the_liberty_passes(tmp_path):
    proj = _project(tmp_path)
    _record(proj, 12.0)
    assert _run(proj).returncode == 0


def test_a_setup_only_record_does_not_satisfy_the_hold_arc(tmp_path):
    """A setup number and a hold number are different requirements. Only one of
    them was the -8.68 ns, so the match must be family-aware."""
    proj = _project(tmp_path)
    doc = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    doc.write_text(json.dumps({"fields": {"macro_timing_requirements": [
        {"macro": "NEUTRAL_NVM_1024X8", "constrained_pin": "PA[0]",
         "related_pin": "PRD", "timing_type": "non_seq_setup_rising",
         "requirement_ns": 8.0}]}}))
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "non_seq_hold_falling" in r.stdout
    assert "non_seq_setup_rising" not in r.stdout   # that one IS recorded


def test_a_record_carrying_both_families_is_read_family_wise(tmp_path):
    """One entry, both numbers. The hold arc must be judged against `hold_ns`,
    not against whichever key the reader happens to list first."""
    proj = _project(tmp_path)
    doc = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    doc.write_text(json.dumps({"fields": {"macro_timing_requirements": [
        {"macro": "NEUTRAL_NVM_1024X8", "constrained_pin": "PA",
         "related_pin": "PRD", "setup_ns": 8.0, "hold_ns": 9.0}]}}))
    assert _run(proj).returncode == 0
    doc.write_text(json.dumps({"fields": {"macro_timing_requirements": [
        {"macro": "NEUTRAL_NVM_1024X8", "constrained_pin": "PA",
         "related_pin": "PRD", "setup_ns": 9.0, "hold_ns": 1.0}]}}))
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "recorded with a window of 1.0 ns" in r.stdout


# --------------------------------------------------------------------------- #
# 4. NSQ-3 — window >= the design's own clock period
# --------------------------------------------------------------------------- #
def test_window_below_the_clock_period_does_not_escalate(tmp_path):
    proj = _project(tmp_path, period_ns=10.0, hold_ns=9.0)
    r = _run(proj)
    assert r.returncode == 1
    assert "NSQ-3" not in r.stdout


def test_window_at_or_above_the_clock_period_escalates(tmp_path):
    proj = _project(tmp_path, period_ns=5.0, hold_ns=9.0)
    r = _run(proj)
    assert r.returncode == 1
    assert "NSQ-3" in r.stdout
    assert "NO single-cycle same-clock integration can satisfy it" in r.stdout


def test_clock_period_comes_from_the_designs_own_sdc(tmp_path):
    import macro_non_seq_arc_contract_check as m
    proj = _project(tmp_path, period_ns=3.5)
    assert m.design_clock_period_ns(proj) == pytest.approx(3.5)


# --------------------------------------------------------------------------- #
# 5. SCOPE — the populations that must never be judged
# --------------------------------------------------------------------------- #
def test_std_cell_class_core_under_a_macro_root_is_not_judged(tmp_path):
    """A std cell's set/reset recovery window is a non_seq arc too. Gating on
    it would fire on every design that ever synthesised."""
    proj = _project(tmp_path, lib_text=_STDCELL_LIB, lef_text=_STDCELL_LEF,
                    rtl=_RTL.replace("NEUTRAL_NVM_1024X8",
                                     "NEUTRAL_CORE_DFSR"))
    r = _run(proj)
    assert r.returncode == 2, r.stdout
    assert "[SKIP]" in r.stdout


#: The SAME abstract, with its `CLASS CORE` denied by its own comment. A LEF is
#: grammar interleaved with English and the annotation can retire the statement
#: under it — vibe-ic#777 measured that on a shipped tech LEF.
_STDCELL_LEF_DENIED = _STDCELL_LEF.replace(
    "  CLASS CORE ;",
    "  # superseded abstract: this master is NOT a core cell\n"
    "  CLASS CORE ;")


def test_a_denied_class_core_cannot_switch_this_gates_audit_off(tmp_path):
    """`CLASS CORE` is SUBTRACTIVE — it removes a master from this gate's
    scope. So a reader that honours a DENIED one hands the audited LEF the
    switch that silences its own audit, which is the shape `_prose_polarity`
    exists for (#712, #706/#711).

    Same tree as the negative control above, one comment added. There the
    undenied `CLASS CORE` skips the gate (rc 2); here the denied one must not
    buy that exclusion, so the master stays in scope and its unrecorded
    non-sequential arc is reported."""
    proj = _project(tmp_path, lib_text=_STDCELL_LIB,
                    lef_text=_STDCELL_LEF_DENIED,
                    rtl=_RTL.replace("NEUTRAL_NVM_1024X8",
                                     "NEUTRAL_CORE_DFSR"))
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NEUTRAL_CORE_DFSR" in r.stdout, r.stdout


def test_both_class_parsers_answer_the_same_thing_denials_included():
    """The stand-alone fallback exists so the gate runs without its sibling —
    not so it can hold a second opinion. If the two disagree, which answer
    `_std_cell_masters` gets depends on whether an import succeeded."""
    import macro_non_seq_arc_contract_check as m
    from l21_macro_supply_rail_declared_check import _macro_classes as sib

    assert m._local_macro_classes(_STDCELL_LEF) == {"NEUTRAL_CORE_DFSR": "CORE"}
    assert sib(_STDCELL_LEF) == {"NEUTRAL_CORE_DFSR": "CORE"}
    # denied -> not published by EITHER, so neither consumer can subtract on it
    assert m._local_macro_classes(_STDCELL_LEF_DENIED) == {}
    assert sib(_STDCELL_LEF_DENIED) == {}
    # and the scope is the CLASS statement's OWN: a comment about a NEIGHBOURING
    # statement is not evidence about the class. 126 of the 244188 MACRO blocks
    # measured on the development host open under a denying lead comment, and
    # every one of them denies a pin, a grid or an obstruction.
    elsewhere = _STDCELL_LEF.replace(
        "  SIZE 1.0 BY 2.0 ;",
        "  # this abstract declares no PIN geometry\n  SIZE 1.0 BY 2.0 ;")
    assert m._local_macro_classes(elsewhere) == {"NEUTRAL_CORE_DFSR": "CORE"}
    assert sib(elsewhere) == {"NEUTRAL_CORE_DFSR": "CORE"}


def test_pdk_standard_cell_library_root_is_out_of_scope(tmp_path):
    """The same macro Liberty staged under the PDK library root, not under a
    DESIGN-staged macro root, is not this gate's population."""
    proj = _project(tmp_path, lib_subdir="input/pdk/liberty", lef_text=None)
    r = _run(proj)
    assert r.returncode == 2, r.stdout
    assert "[SKIP]" in r.stdout


def test_staged_but_uninstantiated_macro_is_out_of_scope(tmp_path):
    proj = _project(tmp_path, rtl=_RTL_NO_MACRO)
    r = _run(proj)
    assert r.returncode == 2, r.stdout
    assert "0/1 staged macro(s)" in r.stdout, r.stdout


def test_design_with_no_staged_macro_liberty_skips(tmp_path):
    proj = tmp_path / "bare"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "t.v").write_text(_RTL_NO_MACRO)
    r = _run(proj)
    # rc alone is NOT the assertion: a MISSING script also exits 2, so an
    # rc-only probe would read "the gate does not exist" as "the gate skipped".
    # The gate's own wording is what proves it ran and decided.
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP] macro_non_seq_arc_contract_check" in r.stdout, r.stdout
    assert "no design-staged macro Liberty" in r.stdout


# --------------------------------------------------------------------------- #
# 6. Disclosure, not silence
# --------------------------------------------------------------------------- #
def test_named_waiver_discloses_rather_than_hides(tmp_path):
    proj = _project(tmp_path)
    (proj / "waivers.json").write_text(json.dumps({
        "macro_non_seq_arc_requirement_disclosed":
            "This block drives the constrained pin from a held register "
            "controlled outside this netlist; reviewed 2026-08-04.",
    }))
    r = _run(proj)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVERS" in r.stdout
    # the findings are still PRINTED — waived is disclosed, not silent
    assert "NSQ-1" in r.stdout


def test_a_too_short_waiver_does_not_excuse_anything(tmp_path):
    proj = _project(tmp_path)
    (proj / "waivers.json").write_text(json.dumps(
        {"macro_non_seq_arc_requirement_disclosed": "known"}))
    assert _run(proj).returncode == 1


# --------------------------------------------------------------------------- #
# 7. WIRING — an unwired program is a no-op
# --------------------------------------------------------------------------- #
def test_gate_is_wired_into_the_flow_at_constraint_setup():
    import yaml
    doc = yaml.safe_load(FLOW_YAML.read_text())
    step7 = next(s for s in doc["steps"] if str(s.get("id")) == "7")
    cmds = [sub["advisory_program_exit_zero"]
            for sub in step7["gate"]["all_of"]
            if isinstance(sub, dict) and "advisory_program_exit_zero" in sub]
    assert any(c.startswith("macro_non_seq_arc_contract_check ") for c in cmds), \
        ("the gate must be invoked BY THE FLOW at Step 7 (constraint setup) — "
         "an unwired program is a no-op")
    # ...and nowhere later than Step 9 (synthesis), because the repair is an
    # RTL/integration change that has to land before the netlist is built.
    step_ids = [str(s.get("id")) for s in doc["steps"]]
    assert step_ids.index("7") < step_ids.index("9")


def test_declared_enforcement_agrees_with_the_slot_it_is_wired_to():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "flow_gate_enforcement_audit",
        PROGRAMS / "flow_gate_enforcement_audit.py")
    fga = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fga)
    assert fga.declared_intent(
        PROGRAMS, "macro_non_seq_arc_contract_check") == "advisory", (
        "wired to the advisory slot, so it must not declare blocking (#306)")


def test_the_flow_gate_evaluator_actually_runs_it(tmp_path):
    """Not 'is it in the yaml' — does `_evaluate_gate` invoke it and carry the
    finding up. Position matters: it sits after a blocking sub-gate, and
    advisories after a failure are re-run precisely so the disclosure survives
    a red step."""
    import importlib.util
    import yaml
    spec = importlib.util.spec_from_file_location(
        "flow_compliance_check", PROGRAMS / "flow_compliance_check.py")
    fcc = importlib.util.module_from_spec(spec)
    sys.modules["flow_compliance_check"] = fcc
    spec.loader.exec_module(fcc)
    doc = yaml.safe_load(FLOW_YAML.read_text())
    step7 = next(s for s in doc["steps"] if str(s.get("id")) == "7")
    proj = _project(tmp_path)
    ok, reasons = fcc._evaluate_gate(proj, step7["gate"])
    hints = [r for r in reasons
             if "macro_non_seq_arc_contract_check" in r]
    assert hints, reasons
    assert any("FINDING" in h for h in hints), hints


# --------------------------------------------------------------------------- #
# 8. The LATE failure is NOT suppressed — it is only named correctly
# --------------------------------------------------------------------------- #
_NON_SEQ_RPT = """Startpoint: _2607_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_nvm (rising edge-triggered flip-flop clocked by clk)
Path Type: min
Corner: ff

  Delay    Time   Description
---------------------------------------------------------
   0.66    0.66 v _2607_/Q (DFF_X1)
   0.00    0.66 v u_nvm/PA[0] (NEUTRAL_NVM_1024X8)
           0.66   data arrival time

   0.00  100.34 v u_nvm/PRD (NEUTRAL_NVM_1024X8)
   0.00    0.34   clock reconvergence pessimism
   9.00    9.34   library non-sequential hold time
           9.34   data required time
---------------------------------------------------------
          -8.68   slack (VIOLATED)
"""

_ORDINARY_RPT = """Startpoint: _2611_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _2650_ (rising edge-triggered flip-flop clocked by clk)
Path Type: min
Corner: ff

  Delay    Time   Description
---------------------------------------------------------
   0.10    0.10 v _2611_/Q (DFF_X1)
   0.00    0.10 v _2650_/D (DFF_X1)
           0.10   data arrival time

   0.02    0.02   library hold time
           0.02   data required time
---------------------------------------------------------
          -0.08   slack (VIOLATED)
"""

_CLEAN_RPT = _ORDINARY_RPT.replace("          -0.08   slack (VIOLATED)",
                                   "           0.08   slack (MET)")

_DEF = """VERSION 5.8 ;
DESIGN neutral_top ;
COMPONENTS 2 ;
- a DFF_X1 + PLACED ( 1 1 ) N ;
- b DFF_X1 + PLACED ( 2 1 ) N ;
END COMPONENTS
END DESIGN
"""


def _pnr_project(tmp_path: Path, rpt: str) -> Path:
    proj = tmp_path / "p"
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "post_cts.def").write_text(_DEF)
    (pnr / "post_hold.def").write_text(_DEF.replace("COMPONENTS 2",
                                                    "COMPONENTS 2"))
    (pnr / "post_hold_timing.rpt").write_text(rpt)
    return proj


def _run_hold(proj: Path, out: Path | None = None):
    argv = [sys.executable, str(HOLD_GATE), str(proj)]
    if out is not None:
        argv += ["--json", str(out)]
    # 55s for the same reason as `_run` above: an inner bound over the 60s
    # per-call ceiling (180s harness / 3) cannot fire before the harness does.
    return subprocess.run(argv, capture_output=True, text=True, timeout=55)


def test_post_cts_hold_still_fails_and_now_names_the_non_sequential_arc(
        tmp_path):
    proj = _pnr_project(tmp_path, _NON_SEQ_RPT)
    out = tmp_path / "h.json"
    r = _run_hold(proj, out)
    assert r.returncode == 1, r.stdout          # the hard failure is INTACT
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    fails = [f for f in data["findings"] if f["severity"] == "FAIL"]
    assert [f["rule"] for f in fails] == ["HOLD_SLACK_NEGATIVE"]
    assert data["summary"]["worst_hold_slack"] == pytest.approx(-8.68)
    # ...and the arc kind is NAMED, with the value and the right repair
    assert data["summary"]["worst_hold_arc_kind"] == \
        "library_non_sequential_hold"
    assert data["summary"]["worst_hold_non_seq_ns"] == pytest.approx(9.0)
    msg = fails[0]["message"]
    assert "NON-SEQUENTIAL" in msg
    assert "INTEGRATION requirement" in msg
    assert "cannot close it" in msg
    assert "macro_non_seq_arc_contract_check" in msg


def test_an_ordinary_hold_violation_keeps_the_original_verdict(tmp_path):
    """NEGATIVE CONTROL: no non-sequential arc in the report means no
    non-sequential claim in the verdict."""
    proj = _pnr_project(tmp_path, _ORDINARY_RPT)
    out = tmp_path / "h.json"
    r = _run_hold(proj, out)
    assert r.returncode == 1
    data = json.loads(out.read_text())
    assert "worst_hold_arc_kind" not in data["summary"]
    msg = next(f["message"] for f in data["findings"]
               if f["rule"] == "HOLD_SLACK_NEGATIVE")
    assert "re-CTS / insert delay cells" in msg
    assert "non-sequential" not in msg.lower()


def test_a_clean_hold_report_still_passes(tmp_path):
    proj = _pnr_project(tmp_path, _CLEAN_RPT)
    r = _run_hold(proj)
    assert r.returncode == 0, r.stdout


def test_a_non_seq_arc_on_a_path_that_is_not_the_worst_is_still_disclosed(
        tmp_path):
    """The worst path is an ordinary hold violation and a DIFFERENT path is
    constrained by a non-sequential arc. The verdict must stay accurate about
    the worst path and still disclose the other."""
    rpt = _ORDINARY_RPT.replace("          -0.08   slack (VIOLATED)",
                                "         -20.00   slack (VIOLATED)") \
        + "\n" + _NON_SEQ_RPT
    proj = _pnr_project(tmp_path, rpt)
    out = tmp_path / "h.json"
    r = _run_hold(proj, out)
    assert r.returncode == 1
    data = json.loads(out.read_text())
    assert data["summary"]["worst_hold_slack"] == pytest.approx(-20.0)
    assert data["summary"]["worst_hold_arc_kind"] == "sequential"
    msg = next(f["message"] for f in data["findings"]
               if f["rule"] == "HOLD_SLACK_NEGATIVE")
    assert "OTHER path(s)" in msg
