"""test_matrix_d2_falsifiable.py — DIMENSION 2 of the 63x8 coverage matrix.

THE QUESTION
------------
    "CAN this gate ever FAIL?"

Not "does the gate exist", not "is it wired", not "did the audit say OK" —
**is there an input that drives this step's gate to a genuine FAIL verdict?**
A gate that can only ever reach PASS is the disease this whole campaign was
opened to find: a check that measures nothing and reports a green.

HOW IT IS ANSWERED — MEASURED, NEVER READ
-----------------------------------------
Every cell is decided by *running the real thing*:

  * the fixture is a deliberately-broken project tree built in a pytest
    ``tmp_path`` (never in the repo, never in /tmp by hand);
  * the evaluator is ``flow_compliance_check`` itself — the module the flow
    actually uses — via ``_check_program_exit_zero`` / ``_check_files_exist`` /
    ``_check_json_field_true``. No re-implementation of the gate semantics
    lives here, so this file cannot drift away from the consumer;
  * the program is invoked exactly as the yaml spells it, through
    ``_resolve_program_cmd``, which is the codebase's own dynamic dispatch.
    Nothing here greps program source for a ``sys.exit(1)``: PR #460 shipped a
    broken change precisely because a grep could not see this codebase's
    dispatch, and a static scan would also happily "prove" an unreachable
    branch falsifiable.

**Nothing in this module reads ``.audit_63x8.json`` to decide anything.**
``cells_for(2)`` is used only to enumerate which 63 cells exist;
``cell.audit_verdict`` is history for humans and is never asserted on.

WHAT COUNTS AS A FAILURE SIGNAL — AND WHAT DOES NOT
---------------------------------------------------
``flow_compliance_check`` grades a gate program on FIVE tiers, and only one of
them is a real FAIL:

    rc 0                      PASS
    rc 0 + ``VACUOUS_PASS:``  disclosed skip  (``_stdout_signals_vacuous``)
    rc 2                      disclosed skip  (``__VACUOUS_HINT__``)
    rc 3 + PASS_WITH_WAIVERS  waived          (``__WAIVER_HINT__``)
    rc 1 / anything else      FAIL

A gate that can only ever reach rc 0 or rc 2 IS the disease, so ``VACUOUS`` is
counted here as a NON-demonstration, exactly like ``PASS``. Three further
outcomes are also refused as demonstrations, because each would let an
environment problem masquerade as a working gate:

    CRASH     the consumer DISCLOSED an unhandled exception, via
              ``flow_compliance_check._CRASH_HINT_PREFIX``. An unhandled
              exception exits non-zero, so the exit code alone cannot tell it
              from a verdict — but "the program blew up" is not "the check
              found a defect". Measured for real while building this file:
              ``rtl_hygiene_lint`` exits 1 with a ``FileNotFoundError`` when
              ``reports/phase2/lint/`` does not exist, which would have
              certified it falsifiable without the linter ever running.
              (Hence ``_prepare_report_dirs``: the gate's own ``--json``
              parent directories are created before the run, which is
              environment setup, not a weakening of the check.)
              The consumer decides this against the UNTRUNCATED streams and
              hands the answer over as a sentinel. It used to be re-derived
              HERE by pattern-matching the evidence snippet, which is a
              fixed-width tail — and since both a traceback frame line and a
              FileNotFoundError message carry ABSOLUTE paths, the answer was
              a function of how deep the checkout lived: measured on this
              tree, a crashing gate graded CRASH at a 107-character project
              path and FAIL at 108. Pattern-matching the snippet survives as
              a FALLBACK for strings that did not come from the live
              consumer; it is no longer what decides a real run.
    TIMEOUT   ``_check_program_exit_zero`` returns ``passed=False`` on a
              killed subprocess and says so in the snippet — its own docstring
              calls a timeout INCONCLUSIVE, not a verdict.
    UNWIRED   "program not found". That is a dimension-1 wiring defect; a
              missing program is not a falsifiable gate.

THE PREDICATE, PER STEP
-----------------------
1. Every **blocking** clause of the step's gate is run against its assigned
   broken fixture. (``advisory_program_exit_zero`` clauses are excluded: they
   run, they report, and they CANNOT fail the step — grading an advisory
   clause as enforcement is measuring something adjacent.)
2. At least one blocking clause must reach a genuine ``FAIL`` — the gate as a
   whole is falsifiable.
3. **Every** blocking clause must reach ``FAIL``, except the ones named in
   :data:`UNREDDENED` — the honest, per-clause register of what this file
   could not break. Without (3), a step could hide an unfailable program
   behind one trivially-failing sibling clause, which is the "at least one
   green light is on" fallacy in miniature.
4. Anti-rot, both directions:
     * an :data:`UNREDDENED` entry whose command no longer appears in the live
       gate is STALE and fails the test — the register cannot outlive the
       clause it excuses;
     * an :data:`UNREDDENED` entry that DOES redden fails the test — the gap
       closed and the entry must be deleted. This is the same mechanism as
       ``xfail(strict=True)``, applied at clause granularity instead of cell
       granularity (a cell-level xfail cannot express "5 of this step's 6
       clauses are proven and the 6th is not").

NA
--
``P0`` is the only step with no ``gate`` key at all — it is a synthetic
pre-flight whose verdict is emitted directly by
``flow_compliance_check._run_structural_rtl_gates``. There is no gate to
falsify, so its cell is NA — and the NA is *live*: the test asserts the
precondition (no ``gate`` key, no clauses) still holds. The day someone gives
P0 a gate, this test fails and forces the cell to be re-decided. An NA that
merely ``pytest.skip()``s is silent absence wearing a hat and is not used here.

RUN
---
    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
        python3 -m pytest programs/tests/test_matrix_d2_falsifiable.py -q

``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` is mandatory in this tree (a stray
``pytest_ethereum`` plugin otherwise breaks collection).

Measured on 2026-07-27: 150 blocking clauses over the 62 gated steps, 120 of
them driven to a real FAIL, 30 registered in :data:`UNREDDENED`. Re-measured
2026-07-28: 121 reddened, 29 registered — the
``fmeda_fault_injection_coverage`` entry de-registered because it now reaches
a real FAIL. **WHICH arm reddens it matters, and the first attempt got this
wrong.** The entry first de-registered itself on the bare ``EMPTY`` fixture,
through a brand-new ``--rtl-dir does not exist`` argument-validation exit —
so the register recorded the clause as falsifiable while the DIAGNOSTIC-
COVERAGE verdict it exists to police stayed unfalsified by the whole suite.
It is now assigned :data:`FMEDA_RTL_BLIND`: real RTL declaring an ECC
mechanism whose detector is tied off, which reaches the measured
DC-vs-ASIL-floor comparison and fails it. The suite
shells out once per exec clause and completes in ~5s (the fixtures are a
handful of stub files, so each gate returns in ~30ms — plus one iverilog
injection run for ``FMEDA_RTL_BLIND``, which is the price of measuring the
verdict instead of the argument parser); ``VIBE_IC_GATE_TIMEOUT_S``
is pinned low by :func:`_gate_timeout` so one hung gate cannot hang the suite.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import traceback
from pathlib import Path
from typing import Callable, Dict, Tuple

import pytest

import flow_compliance_check as FCC

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W
from matrix_63x8.cells import cells_for

DIM = 2

# ─────────────────────────────────────────────────────────────────────
# Outcome tiers
# ─────────────────────────────────────────────────────────────────────
RED = "FAIL"          # the one outcome that demonstrates falsifiability
PASS = "PASS"
VACUOUS = "VACUOUS_PASS"
WAIVED_TIER = "PASS_WITH_WAIVERS"
CRASH = "CRASH"
TIMEOUT = "TIMEOUT"
UNWIRED = "PROGRAM_NOT_FOUND"
SKIPPED_COND = "SKIPPED_CONDITION"

#: The steps whose dimension-2 cell is NA because they declare no ``gate`` at
#: all. Exactly one at time of writing: ``P0`` is a synthetic pre-flight whose
#: verdict is emitted directly by
#: ``flow_compliance_check._run_structural_rtl_gates`` and surfaced in
#: ``reports/audit/phase23_completion_audit.json`` — see the step's own
#: ``notes:`` in the flow yaml. There is no gate expression to falsify.
#:
#: Declared rather than derived on purpose. Deriving it (``every step with no
#: gate is NA``) would make a step that LOSES its gate silently reclassify
#: itself as an accepted NA — the disease, one level up. Declared, both
#: directions redden.
NA_STEPS: Tuple[str, ...] = ("P0",)

#: Per-gate subprocess cap for this suite. The production default is 900s
#: (``_path_layout.gate_timeout_s``), sized for a real 7.5MB post-PnR netlist.
#: Every fixture here is a handful of stub files, so 120s is generous — and it
#: bounds the whole suite instead of letting one wedged gate hang it.
GATE_TIMEOUT_S = "120"

#: ``verilator_coverage_measure``'s capability probe, PINNED.
#:
#: 2026-07-28. That gate answers "missing coverage artefact: defect, or
#: capability gap?" with ``shutil.which(args.verilator_bin)`` — present -> rc 1
#: (a real FAIL), absent -> rc 3 + ``PASS_WITH_WAIVERS``. Left to the ambient
#: PATH, the SAME clause of step 4's gate therefore grades FAIL on a host that
#: has Verilator and PASS_WITH_WAIVERS on one that does not, so whether this
#: module counts the clause as reddened is a property of the machine rather
#: than of the gate. It was registered in :data:`UNREDDENED` from a host
#: without Verilator and reddened on the next host that had it.
#:
#: Pinning removes the lottery in the direction that can only make this module
#: STRICTER: it selects the branch where the capability exists, which is the
#: one that has to reach a real FAIL. The program itself exposes the variable
#: for exactly this ("Made overridable so a test harness ... can PIN the
#: decision rather than inherit whatever the host happens to have",
#: programs/verilator_coverage_measure.py:422-427), and its ``check``
#: subcommand only asks whether the path RESOLVES — it never executes it — so
#: any always-present executable states the precondition without pretending a
#: measurement was taken. ``sys.executable`` is used because it is the one
#: absolute path guaranteed to exist wherever this suite can run at all.
VERILATOR_BIN_ENV = "VIBE_IC_VERILATOR_BIN"


# ─────────────────────────────────────────────────────────────────────
# The broken-fixture library
# ─────────────────────────────────────────────────────────────────────
# Each builder writes a project tree that is deliberately WRONG in a way the
# gates below are supposed to notice. They are inputs, never edits to the
# programs under test: mutating the program would prove nothing about the
# program's own falsifiability.

_BAD_RTL = """\
// Deliberately broken RTL (D2 fixture). Four planted defects:
//   * `dangling` is declared and never driven      -> rtl_hygiene_lint
//   * `in_async` is read in always @(posedge) with
//     no 2-flop synchroniser                       -> cdc_async_input_check
//   * `core_rstn` combines `sub_done`, produced by
//     an instance reset BY `core_rstn`             -> reset_dependency_check
//   * clk_a -> clk_b capture with no handshake     -> cdc_crossing_check
module sub (
    input  wire clk,
    input  wire rstn,
    output reg  sub_done
);
  always @(posedge clk or negedge rstn) begin
    if (!rstn) sub_done <= 1'b0;
    else       sub_done <= 1'b1;
  end
endmodule

module top (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst_n,
    input  wire in_async,
    input  wire [7:0] din,
    output wire [7:0] dout,
    output reg  q_b,
    output reg  y_async_use
);
  wire dangling;
  wire sub_done;
  wire core_rstn;
  reg  a_flop;

  assign dout = {7'b0, dangling};
  assign core_rstn = rst_n & sub_done;

  sub u_sub (.clk(clk_a), .rstn(core_rstn), .sub_done(sub_done));

  always @(posedge clk_a) begin
    a_flop      <= din[0];
    y_async_use <= din[1] & in_async;
  end
  always @(posedge clk_b) begin
    q_b <= a_flop;
  end
endmodule
"""

# A synth script missing `hilomap` (and `-flatten` / `-sv`) — CLAUDE.md rule 4.
_BAD_YS = "read_verilog top.v\nsynth -top top\nwrite_verilog netlist.v\n"

# `create_clock -period` with no value; a false path off a port that does not
# exist.
_BAD_SDC = ("create_clock -name clk -period\n"
            "set_false_path -from [get_ports nonexistent_port]\n")

_VACUOUS_TB = (
    "module case_1;\n"
    "  initial begin\n"
    '    $display("PASS_PLACEHOLDER - replace with real stimulus");\n'
    "    // top u_dut (.clk(clk), .rst_n(rst_n));\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n"
)


def _w(root: Path, rel: str, content) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, indent=1)
    p.write_text(content, encoding="utf-8")
    return p


def _f_empty(p: Path) -> None:
    """Nothing was produced at all. The commonest real failure."""


def _f_rtl_bad(p: Path) -> None:
    _w(p, "phase2/stage1/rtl/top.v", _BAD_RTL)


def _analog_partial(p: Path, root: str) -> None:
    """Two blocks declared; only ONE carries any A-step artefact, and every
    artefact it carries is a stub.

    Reaches both A-track FAIL arms at once: ``emit_incomplete`` (some blocks
    covered, some not) and the per-artefact substance floors (a 78-byte
    topology.md, a 68-byte netlist, a spec with no recognised spec keys).
    Absence alone is NOT enough — the A gates answer VACUOUS_PASS to an empty
    project by design, which is exactly why this fixture has to declare work
    and then under-deliver it.
    """
    _w(p, f"{root}/analog_block_list.json",
       {"blocks": [{"name": "bandgap"}, {"name": "ldo"}]})
    b = f"{root}/bandgap/"
    _w(p, b + "spec.json",
       {"name": "bandgap", "specs": {"vout": 1.2}, "confidence": "high"})
    _w(p, b + "topology.md", "# bandgap\nBrokaw bandgap reference topology.\n")
    _w(p, b + "bandgap.sp", ".subckt bandgap vdd vss out\n.ends\n")
    _w(p, b + "corner_results.json", {"corners": [{"name": "tt"}]})
    _w(p, b + "layout.mag", "magic\ntech sky130A\n<< end >>\n")
    _w(p, b + "bandgap.gds", "GDSII" * 20)
    _w(p, b + "pre_vs_post.json",
       {"pre": {"vout": 1.2}, "post": {"vout": 1.1}})
    _w(p, b + "hw_measurements.json", {"measurements": []})


def _f_analog_p3(p: Path) -> None:
    _analog_partial(p, "phase3/analog")


def _f_a0_skipped(p: Path) -> None:
    """The forbidden artefact, encoding the forbidden verdict.

    `analog_a0_skip_forbidden_check` was wired into D1 by vibe-ic#700, and this
    gate then had a blocking clause whose FAIL nothing proved reachable. On the
    bare EMPTY fixture it answers PASS — correctly, because absence of the
    artefact IS the pass — so the falsifiability question could not be answered
    from EMPTY by construction.

    Absence is not enough and neither is mere presence: the gate reads the
    named decision fields and FAILs only on a verdict that actually encodes a
    top-level analog skip, which is what makes it a rule rather than a
    file-existence test. So the fixture has to state the skip."""
    _w(p, "phase1/analog/A0_skip_decision.json",
       {"decision": "skip", "reason": "no analog content identified"})


def _f_synth_bad(p: Path) -> None:
    _w(p, "phase2/stage2/synth/synth.ys", _BAD_YS)
    _w(p, "phase2/stage2/synth/netlist.v", "// empty netlist\n")


def _f_sdc_bad(p: Path) -> None:
    _w(p, "phase2/stage2/constraints/top.sdc", _BAD_SDC)
    _w(p, "phase2/stage2/constraints/pvt_matrix.json", {})


def _f_pnr_bad(p: Path) -> None:
    for n in ("floorplan.def", "placed.def", "post_cts.def", "post_hold.def",
              "routed.def", "filled.def"):
        _w(p, f"phase3/stage3/pnr/{n}", "VERSION 5.8 ;\nEND DESIGN\n")
    _w(p, "phase3/stage3/extracted/top.spef", "*SPEF\n")


def _f_gds_bad(p: Path) -> None:
    """A 0-byte GDS deliverable and a 0-byte member inside the handoff pack."""
    _w(p, "phase3/stage4/gds/top.gds", "")
    _w(p, "phase3/stage4/foundry_handoff/empty_member.txt", "")


def _f_gds_no_labels(p: Path) -> None:
    """A parseable GDS whose top cell carries NO text, beside a DEF that PLACES
    a port.

    `gds_port_label_check`'s subject is whether the streamed GDS names every
    port the DEF places, so neither input alone reaches its comparison: on the
    bare EMPTY fixture it answered VACUOUS_PASS, and its blocking clause had
    therefore never been shown to block. That is what step 37 was failing on.

    Geometry but no TEXT records is the smallest input that reaches the
    comparison and fails it. MEASURED before wiring:

        [FAIL] top.gds: NO_LABELS — top cell 'top' carries 0 text labels
               while the DEF places 1 port(s)                        rc 1
    """
    import struct

    def _rec(rt: int, dt: int, payload: bytes = b"") -> bytes:
        return struct.pack(">HBB", len(payload) + 4, rt, dt) + payload

    def _r8(v: float) -> bytes:
        if v == 0:
            return b"\x00" * 8
        sign, exp = 0, 64
        while v >= 1:
            v /= 16.0
            exp += 1
        while v < 1 / 16.0:
            v *= 16.0
            exp -= 1
        return struct.pack(">B", sign | exp) + int(v * (1 << 56)).to_bytes(7, "big")

    nm = b"top\x00"
    stamp = struct.pack(">12h", *([2026, 8, 1, 0, 0, 0] * 2))
    g = _rec(0x00, 2, struct.pack(">h", 600))
    g += _rec(0x01, 2, stamp) + _rec(0x02, 6, nm)
    g += _rec(0x03, 5, _r8(1e-3) + _r8(1e-9))
    g += _rec(0x05, 2, stamp) + _rec(0x06, 6, nm)
    g += _rec(0x08, 0) + _rec(0x0D, 2, struct.pack(">h", 68))
    g += _rec(0x0E, 2, struct.pack(">h", 20))
    pts = [(0, 0), (900, 0), (900, 900), (0, 900), (0, 0)]
    g += _rec(0x10, 3, b"".join(struct.pack(">ii", x, y) for x, y in pts))
    g += _rec(0x11, 0) + _rec(0x07, 0) + _rec(0x04, 0)
    (p / "phase3/stage4/gds").mkdir(parents=True, exist_ok=True)
    (p / "phase3/stage4/gds/top.gds").write_bytes(g)
    _w(p, "phase3/stage3/pnr/top.def",
       "VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
       "PINS 1 ;\n    - a + NET a + DIRECTION INPUT + USE SIGNAL\n"
       "      + LAYER met2 ( -70 -70 ) ( 70 70 ) + PLACED ( 1000 2000 ) N ;\n"
       "END PINS\nEND DESIGN\n")


def _f_mfg_bad(p: Path) -> None:
    """Manufacturing intake artefacts that exist and attest NOTHING."""
    m = "phase3/stage5_manufacturing/"
    for n in ("mask_set_received.json", "wafer_lot_received.json",
              "packaging_log.json", "final_test_yield.json",
              "htol_results.json"):
        _w(p, m + n, {"note": "substanceless"})


def _f_fmeda_bad(p: Path) -> None:
    """A coverage report whose OWN counts contradict an ASIL-D claim."""
    _w(p, "reports/phase2/safety/fmeda_coverage.json",
       {"applicable": True, "asil": "D", "injected_faults": 100,
        "detected_faults": 1, "baseline_valid": True})


def _f_fmeda_rtl_blind(p: Path) -> None:
    """RTL that DECLARES an ECC mechanism whose detector is tied off.

    The PRODUCER clause (`fmeda_fault_injection_coverage`) needs RTL, not a
    report: its subject is the measured diagnostic coverage, and without a
    declared mechanism it answers NOT_APPLICABLE and exits 0. This is the
    smallest input that reaches the DC comparison and fails it — a Hamming
    encoder paired with a decoder whose `syndrome_err` is a constant, so every
    injected single-bit fault escapes and DC lands far below the ASIL-D floor.

    Reddening this clause on the bare EMPTY fixture instead would exercise
    only the `--rtl-dir does not exist` argument-validation arm, leaving the
    diagnostic-coverage verdict — the thing this gate exists to police —
    unfalsified by the suite while the register recorded it as falsifiable.
    """
    _w(p, "phase2/stage1/rtl/enc.v",
       "module ham_enc(input [3:0] data_in, output [6:0] code_out);\n"
       "assign code_out[2]=data_in[0]; assign code_out[4]=data_in[1];\n"
       "assign code_out[5]=data_in[2]; assign code_out[6]=data_in[3];\n"
       "assign code_out[0]=data_in[0]^data_in[1]^data_in[3];\n"
       "assign code_out[1]=data_in[0]^data_in[2]^data_in[3];\n"
       "assign code_out[3]=data_in[1]^data_in[2]^data_in[3]; endmodule\n")
    _w(p, "phase2/stage1/rtl/dec.v",
       "module ham_dec(input [6:0] code_in, output [3:0] data_out,"
       " output syndrome_err);\n"
       "assign data_out={code_in[6],code_in[5],code_in[4],code_in[2]};\n"
       "assign syndrome_err=1'b0; endmodule\n")


def _f_ms_bad(p: Path) -> None:
    """A merged GDS with no LVS behind it; an unparseable power-domain file."""
    _w(p, "phase3/mixed_signal/top_merged.gds", "not a real gds")
    _w(p, "reports/analog/mixed_signal/power_domain.json", "{ not json")


def _f_tb_bad(p: Path) -> None:
    """A testbench that prints a pass without driving the DUT, and a
    professional-TB report self-declaring a functional mismatch."""
    _w(p, "phase2/stage1/sim/tb/case_1.v", _VACUOUS_TB)
    _w(p, "reports/phase2/gates/professional_tb.json",
       {"status": "PASS", "functional_mismatch": True})


def _f_hollow_reports(p: Path) -> None:
    """Reports that EXIST and carry no measurement — the shape that turns a
    missing-input skip into a substance failure."""
    _w(p, "reports/phase3/dynamic_ir.json", {})


FIXTURES: Dict[str, Callable[[Path], None]] = {
    "EMPTY": _f_empty,
    "RTL_BAD": _f_rtl_bad,
    "ANALOG_P3": _f_analog_p3,
    "A0_SKIPPED": _f_a0_skipped,
    "SYNTH_BAD": _f_synth_bad,
    "SDC_BAD": _f_sdc_bad,
    "PNR_BAD": _f_pnr_bad,
    "GDS_BAD": _f_gds_bad,
    "GDS_NO_LABELS": _f_gds_no_labels,
    "MFG_BAD": _f_mfg_bad,
    "FMEDA_BAD": _f_fmeda_bad,
    "FMEDA_RTL_BLIND": _f_fmeda_rtl_blind,
    "MS_BAD": _f_ms_bad,
    "TB_BAD": _f_tb_bad,
    "HOLLOW_REPORTS": _f_hollow_reports,
}

#: Which fixture reddens which clause. Keyed by ``(normalized step id, exact
#: gate command as spelled in the yaml)`` — so a command that is re-worded
#: upstream loses its assignment, falls back to ``EMPTY``, and (if EMPTY does
#: not redden it) fails loudly rather than silently keeping a stale recipe.
#: Clauses absent from this table use ``EMPTY``.
CLAUSE_FIXTURE: Dict[Tuple[str, str], str] = {
    # vibe-ic#700 wired this into D1. EMPTY cannot redden it: absence of the
    # forbidden artefact IS the pass, so the clause needs the artefact present
    # AND carrying the forbidden verdict.
    ("D1", "analog_a0_skip_forbidden_check ."): "A0_SKIPPED",
    ("2", "rtl_hygiene_lint phase2/stage1/rtl/*.sv phase2/stage1/rtl/*.v "
          "--severity ERROR --json reports/phase2/lint/rtl_hygiene.json"):
        "RTL_BAD",
    ("3", "cdc_async_input_check . --json "
          "reports/phase2/gates/cdc_async_input.json"): "RTL_BAD",
    ("3", "reset_dependency_check . --json "
          "reports/phase2/gates/cdc_reset_dep.json"): "RTL_BAD",
    # RTL_BAD's `top` already plants the crossing this gate exists to find:
    # `a_flop` is written under clk_a and read under clk_b with no synchroniser.
    # On the bare EMPTY fixture the gate answers rc=2 (no RTL to analyse), which
    # is a disclosed skip and not a falsification — the crossing verdict itself
    # would go unproven while the register recorded the clause as falsifiable.
    ("3", "clock_domain_reg_crossing_check . --json "
          "reports/phase2/gates/cdc_reg_crossing.json"): "RTL_BAD",
    ("4", "vacuous_testbench_check . --json "
          "reports/phase2/gates/vacuous_testbench.json"): "TB_BAD",
    ("4", "professional_tb_check . --json "
          "reports/phase2/gates/professional_tb_check.json"): "TB_BAD",
    ("7", "pvt_matrix_check . --json reports/phase2/gates/pvt_matrix.json"):
        "SDC_BAD",
    ("8", "sdc_validator_check . --l8 "
          "phase1/generated_docs/L8_TIMING_WAVEFORM.json --json "
          "reports/sdc_validator.json"): "SDC_BAD",
    ("FS1", "fmeda_fault_injection_coverage . --rtl-dir phase2/stage1/rtl "
            "--asil D --json reports/phase2/safety/fmeda_coverage.json"):
        "FMEDA_RTL_BLIND",
    ("FS1", "fmeda_coverage_check . --json "
            "reports/phase2/safety/fmeda_coverage_gate.json"): "FMEDA_BAD",
    ("A1", "analog_a1_spec_extract_check . --json reports/analog/a1_spec.json"):
        "ANALOG_P3",
    ("A2", "analog_a2_topology_select_check . --json "
           "reports/analog/a2_topology.json"): "ANALOG_P3",
    ("A3", "analog_netlist_pdk_check . --json "
           "reports/phase2/gates/analog_netlist_pdk.json"): "ANALOG_P3",
    ("A3", "analog_a3_netlist_gen_check . --json "
           "reports/analog/a3_netlist.json"): "ANALOG_P3",
    ("A4", "analog_a4_corner_sweep_check . --json "
           "reports/phase2/gates/analog_corner_sweep.json"): "ANALOG_P3",
    ("A5", "analog_a5_layout_check . --json reports/analog/a5_layout.json"):
        "ANALOG_P3",
    ("A6", "analog_a6_block_pv_check . --json "
           "reports/phase2/gates/analog_block_pv.json"): "ANALOG_P3",
    ("A7", "analog_pre_vs_post_layout_check . --json "
           "reports/phase2/gates/pre_vs_post.json"): "ANALOG_P3",
    ("A8", "analog_hardmacro_check . --json "
           "reports/phase2/gates/hardmacro.json"): "ANALOG_P3",
    ("A8", "analog_lef_gds_outline_check . --json "
           "reports/phase2/gates/a8_lef_gds_outline.json"): "ANALOG_P3",
    ("A9", "mixed_signal_cosim_check . --json reports/phase2/gates/cosim.json"):
        "ANALOG_P3",
    ("A9", "analog_a9_hw_verify_check . --json "
           "reports/phase2/gates/a9_hw_verify.json"): "ANALOG_P3",
    ("14", "yosys_hilomap_required_check . --json "
           "reports/phase2/gates/yosys_hilomap.json"): "SYNTH_BAD",
    ("14", "yosys_script_template_check . --json "
           "reports/phase2/gates/yosys_script_template.json"): "SYNTH_BAD",
    ("22", "provenance_check . --output phase3/stage3/extracted/*.spef "
           "--tool magic,openroad"): "PNR_BAD",
    ("24", "dynamic_ir_drop_check reports/phase3/dynamic_ir.json "
           "--budget-pct 10"): "HOLLOW_REPORTS",
    ("37", "gds_size_check --gds-file phase3/stage4/gds/*.gds --json "
           "reports/phase3/gds_size.json"): "GDS_BAD",
    ("37", "gds_substance_check . --json reports/phase3/gds_substance.json"):
        "GDS_BAD",
    # `GDS_BAD`'s 0-byte deliverable does not reach this gate's comparison — it
    # needs a PARSEABLE GDS and a DEF that places a port, or it answers
    # VACUOUS_PASS. See `_f_gds_no_labels`.
    ("37", "gds_port_label_check . --json reports/phase3/gds_port_labels.json"):
        "GDS_NO_LABELS",
    ("38", "foundry_handoff_package_check . --json "
           "reports/phase3/foundry_handoff_audit.json"): "GDS_BAD",
    ("M1", "mixed_signal_merge_check . --json "
           "reports/analog/mixed_signal/merge.json"): "MS_BAD",
    ("M2", "power_domain_crossing_check . --json "
           "reports/analog/mixed_signal/power_domain_crossing_audit.json"):
        "MS_BAD",
    ("M2", "level_shifter_required_check . --json "
           "reports/analog/mixed_signal/level_shifter_audit.json"): "MS_BAD",
    ("M2", "isolation_cell_required_check . --json "
           "reports/analog/mixed_signal/isolation_audit.json"): "MS_BAD",
    ("M3", "mixed_signal_cosim_check . --json "
           "reports/analog/mixed_signal/cosim_audit.json"): "ANALOG_P3",
    ("M3", "mixed_signal_interface_si_check . --json "
           "reports/analog/mixed_signal/interface_si_audit.json"): "ANALOG_P3",
    ("M4", "mixed_signal_signoff_check . --json "
           "reports/analog/mixed_signal/signoff_audit.json"): "ANALOG_P3",
    ("40", "manufacturing_fab_intake_check . --json "
           "reports/manufacturing/fab_intake.json"): "MFG_BAD",
    ("42", "packaging_intake_check . --json "
           "reports/manufacturing/packaging.json"): "MFG_BAD",
    ("43", "final_test_attestation_check . --json "
           "reports/manufacturing/final_test.json"): "MFG_BAD",
    ("44", "htol_attestation_check . --json reports/manufacturing/htol.json"):
        "MFG_BAD",
}

#: Blocking clauses this file could NOT drive to a FAIL, with the outcome
#: actually measured across the whole fixture library.
#:
#: This is NOT a waiver of the CELL — every one of these steps still has a
#: sibling clause proven falsifiable, so the step's gate as a whole is known to
#: be able to fail. It is a per-clause admission that THIS program's FAIL
#: branch was not reached from any fixture here, so nothing in this suite
#: proves that program can fail. Each entry names the tiers observed; the
#: register is checked in BOTH directions (stale entry -> red; entry that
#: starts reddening -> red), which is xfail(strict=True) at clause granularity.
#:
#: Measured 2026-07-27 by running each command through
#: ``flow_compliance_check._check_program_exit_zero`` against all 12 fixtures
#: in :data:`FIXTURES`.
UNREDDENED: Dict[Tuple[str, str], str] = {
    ("D1", "phase1_expert_parse_track ."):
        "rc=2 VACUOUS_PASS under every fixture: the expert-parse track needs a "
        "real Phase-1 extraction run to have happened, and a stubbed "
        "generated_docs/ tree still reads as 'track not attempted'",
    ("2", "rom_init_lint phase2/stage1/rtl/*.sv phase2/stage1/rtl/*.v --json "
          "reports/phase2/lint/rom_init_lint.json"):
        "PASS/VACUOUS: needs RTL carrying a Quartus-unsafe ROM initialiser "
        "shape, which the generic broken-RTL fixture does not contain",
    ("2", "rtl_bug_report_schema_check . --json "
          "reports/phase2/gates/rtl_bug_schema.json"):
        "VACUOUS under every fixture: requires a real reports/phase2/"
        "rtl_bugs.json emitted by an eco/close-loop run",
    ("2", "internal_vs_external_timing_check "
          "phase1/generated_docs/L8_TIMING_WAVEFORM.json --layer "
          "phase1/generated_docs/L8_RTL_CONSTANTS.json --json "
          "reports/phase2/gates/int_vs_ext_timing.json"):
        "PASS: needs an L8 pair that DISAGREES numerically; a hollow L8 has no "
        "internal/external pair to contradict",
    ("2", "threshold_range_contiguity_check "
          "phase1/generated_docs/L8_RTL_CONSTANTS.json --json "
          "reports/phase2/gates/threshold_contiguity.json"):
        "PASS: needs a populated threshold table with a gap/overlap; a hollow "
        "L8_RTL_CONSTANTS has no ranges to be non-contiguous",
    ("2", "spec_response_delay_check phase2/stage1/rtl --spec "
          "phase1/generated_docs/L8_TIMING_WAVEFORM.json --spec "
          "phase1/generated_docs/L8_RTL_CONSTANTS.json --json "
          "reports/phase2/gates/spec_response_delay.json"):
        "PASS/VACUOUS: needs RTL whose measured response delay contradicts a "
        "populated L8 spec — a design-specific pair no generic fixture has",
    ("2", "nba_addr_read_race_check phase2/stage1/rtl --json "
          "reports/phase2/gates/nba_addr_race.json"):
        "PASS/VACUOUS: needs the specific NBA address-read race shape "
        "(memory read addressed by a non-blocking-assigned register)",
    ("2", "periodic_timer_vs_rx_activity_check phase2/stage1/rtl --json "
          "reports/phase2/gates/periodic_timer.json"):
        "PASS/VACUOUS: needs a periodic-timer/rx-activity pair in the RTL, a "
        "protocol-specific structure absent from the generic fixture",
    ("2", "memory_read_pipeline_check phase2/stage1/rtl --json "
          "reports/phase2/gates/memory_read_pipeline.json"):
        "PASS/VACUOUS: needs an inferred memory with a mis-pipelined read "
        "path; the fixture declares an array but no read pipeline",
    ("2", "fpga_wrapper_input_polluter_check --rtl phase2/stage1/rtl --json "
          "reports/phase2/gates/fpga_input_polluter.json"):
        "PASS/VACUOUS: needs an FPGA wrapper module driving a DUT input from "
        "a board-level signal; the fixture has no wrapper layer",
    ("4", "cpu_functional_oracle_waiver_check . --json "
          "reports/phase2/gates/cpu_functional_oracle_waiver.json"):
        "PASS: fires only for a CPU-class design with a claimed functional "
        "oracle waiver; the fixture declares no ic_class",
    ("4", "l10_tb_conformance_check --l10 "
          "phase1/generated_docs/L10_TEST_CASES.json --tb-dir "
          "phase2/stage1/sim/tb --out reports/phase2/gates/"
          "l10_tb_conformance.json"):
        "VACUOUS: needs a POPULATED L10 test-case list to check the TB tree "
        "against; a hollow L10 leaves nothing to conform to",
    ("4", "l12_tb_coverage_check . --json "
          "reports/phase2/gates/l12_tb_coverage.json"):
        "PASS/VACUOUS: needs a populated L12 sequence list uncovered by the "
        "TB tree; a hollow L12 declares no sequences",
    # 2026-07-28: the step-4 `verilator_coverage_measure check` clause was
    # registered here as "rc=3 PASS_WITH_WAIVERS under every fixture". That was
    # never a property of the gate — it was the host. The gate FAILs (rc 1) on
    # any machine where the coverage toolchain is installed and self-waives
    # (rc 3) only where it is not, so the entry reddened the moment the suite
    # ran on a host with Verilator. :data:`VERILATOR_BIN_ENV` now pins the
    # capability probe, the clause reaches its real FAIL deterministically, and
    # the excuse is deleted rather than re-worded.
    ("5", "assertion_property_check . --json "
          "reports/phase2/gates/assertion_property.json"):
        "VACUOUS: needs SVA properties present but non-substantive; the "
        "fixture ships no .sva/bind file for the gate to grade",
    ("6", "quartus_map_audit --project . --json "
          "reports/phase2/gates/quartus_map_audit.json"):
        "PASS: needs a real Quartus map report tree (output_files/*.map.rpt) "
        "with a defect; no fixture here synthesises one",
    ("6", "fpga_verification_audit --report reports/"
          "fpga_verification_report.md --summary phase2/stage1/sim/work/"
          "summary.txt --coverage reports/phase2/coverage/"
          "coverage_actual.json --out reports/phase2/gates/"
          "fpga_verification_audit.json"):
        "PASS: needs a human FPGA verification report contradicting the sim "
        "summary; the contradiction is the input, not the absence",
    ("8", "sdc_exception_correlation_check . --json "
          "reports/phase2/gates/sdc_exceptions.json"):
        "PASS/VACUOUS: needs SDC exceptions that fail to correlate with a "
        "real netlist; the broken-SDC fixture has no netlist to correlate to",
    ("8", "derived_clock_sdc_required_check phase2/stage1/rtl --sdc "
          "phase2/stage2/constraints --json "
          "reports/phase2/gates/derived_clock_sdc.json"):
        "PASS: needs RTL that DERIVES a clock (divider/gater) with no matching "
        "create_generated_clock; the fixture derives no clock",
    # ("FS1", "fmeda_fault_injection_coverage ...") — DE-REGISTERED, on the
    # SUBSTANTIVE arm. The entry read "PASS (NOT_APPLICABLE): fires only when
    # the RTL DECLARES an ECC/parity/lockstep mechanism, and reaching its FAIL
    # arm then needs a real fault-injection simulation run". Both halves were
    # true, and the fix is to BUILD that run: the clause is now assigned
    # FMEDA_RTL_BLIND — a Hamming encoder plus a decoder whose syndrome output
    # is tied to a constant — which reaches the DC-vs-ASIL-floor comparison and
    # fails it. RE-MEASURED 2026-07-28, because the figure written here before
    # ("DC=7.14%") reproduces from nothing: driving THIS module's own
    # FIXTURES['FMEDA_RTL_BLIND'] through the exact clause command gives
    # `DC=42.86% (48/112) floor=99.0 ASIL-D -> FAIL`, rc 1, deterministically.
    # The verdict and the exit code were right; the number was not, and a
    # number in shipped code that traces to no artifact is the defect class
    # this campaign exists to remove.
    #
    # It was FIRST de-registered on the bare EMPTY fixture, reddened by a new
    # `--rtl-dir does not exist` argument-validation exit. That is a real
    # non-zero exit and the direction-B anti-rot assertion correctly forced the
    # entry out — but it would have left this register asserting that the
    # diagnostic-coverage verdict is falsifiable when only the argument parser
    # was. Reddening the right arm is the point of the register.
    ("15", "ip_integration_check . --json "
           "reports/phase2/gates/ip_integration.json"):
        "VACUOUS: needs a declared IP catalogue with an integration defect; "
        "the gate is inapplicable to a project that integrates no IP",
    ("23", "post_route_signoff_corner_check . --json "
           "reports/phase3/sta/post_route_signoff_corner.json"):
        "PASS: needs a post-route STA corner set that is missing a signoff "
        "corner — a populated multi-corner report no fixture here produces",
    ("23", "sta_corner_record_completeness_check . --json "
           "reports/phase3/sta/sta_corner_record_completeness.json"):
        "PASS: needs a corner RECORD with holes; absence of the record is not "
        "the same input as an incomplete record",
    ("23", "drv_promotion_corroboration_check . --json "
           "reports/phase3/sta/drv_promotion_corroboration.json"):
        "PASS: needs an STA report claiming a DRV promotion that a second "
        "source does not corroborate",
    ("26", "gds_antenna_deck_check . --json "
           "reports/phase2/gates/gate_oxide_geom_deck.json"):
        "VACUOUS: needs a real PDK antenna rule deck to grade; the check is "
        "inapplicable without one and no fixture can synthesise a PDK",
    ("28", "perc_signoff_check . --json "
           "reports/phase2/gates/perc_signoff.json"):
        "PASS/VACUOUS: needs a PERC-equivalent report present but "
        "non-substantive; a hollow report is read as 'PERC not applicable'",
    ("30", "spice_correlation_check . --json "
           "reports/phase2/gates/spice_correlation.json"):
        "PASS: needs a SPICE-vs-STA correlation pair that disagrees; both "
        "halves must exist and be populated for the FAIL arm to be reachable",
    ("31", "pg_rail_geometry_check . --json "
           "reports/phase3/pg_rail_geometry.json"):
        "VACUOUS: needs a routed DEF with real PG rail geometry; the stub DEF "
        "in PNR_BAD carries no SPECIALNETS section to measure",
    ("34", "metal_fill_emit . --verify-only --json "
           "reports/phase2/gates/cmp_fill_emit.json"):
        "VACUOUS: --verify-only grades an emitted fill dataset; with no fill "
        "to verify the gate is inapplicable rather than failing",
    ("M2", "power_domain_signal_crossing_check . --json "
           "reports/phase2/gates/power_domain_signal_crossing.json"):
        "VACUOUS: needs a power-intent artefact (UPF or L21 domains) plus RTL "
        "signals crossing between the declared domains",
}


# ─────────────────────────────────────────────────────────────────────
# Harness
# ─────────────────────────────────────────────────────────────────────
_OUT_FLAGS = ("--json", "--out", "--coverage-json", "--report")


def _prepare_report_dirs(project: Path, command: str) -> None:
    """Create the parent dirs of the gate's own report outputs.

    Environment setup, not a relaxation: in a real run the project already
    carries ``reports/``. Without it several gates die with a
    ``FileNotFoundError`` while writing their report — a non-zero exit the
    consumer cannot distinguish from a verdict, which would certify a gate
    falsifiable on the strength of a crash. Measured on ``rtl_hygiene_lint``
    and ``rom_init_lint`` while building this file.
    """
    toks = shlex.split(command)
    for i, tok in enumerate(toks):
        val = None
        if tok in _OUT_FLAGS and i + 1 < len(toks):
            val = toks[i + 1]
        else:
            for flag in _OUT_FLAGS:
                if tok.startswith(flag + "="):
                    val = tok.split("=", 1)[1]
                    break
        if val and not val.startswith("-"):
            (project / val).parent.mkdir(parents=True, exist_ok=True)


def _materialise_conditions(project: Path, clause) -> None:
    """Make an ``optional_program_exit_zero`` clause APPLICABLE.

    ``_evaluate_gate`` skips such a clause outright when none of its
    ``condition_files_exist`` patterns match, and a clause that never runs
    cannot fail — so leaving the condition unsatisfied would let every
    conditional gate in the flow "pass" this dimension by never executing.
    Asking "can it fail" therefore requires first making it applicable.

    What is created is deliberately SUBSTANCELESS: an empty dir for a
    suffix-less pattern, ``{}`` for a ``.json``, an empty file otherwise. The
    clause becomes reachable; nothing is handed to it that could make it pass.
    An existing match (from the step's fixture) is left alone.
    """
    for pattern in clause.condition_files:
        if any(project.glob(pattern)):
            continue
        target = project / pattern.replace("*", "d2fixture")
        if target.suffix == "":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n" if target.suffix == ".json" else "",
                          encoding="utf-8")


#: The traceback patterns, RE-EXPORTED FROM THE CONSUMER — not redefined here.
#:
#: 2026-07-27, adversarial finding (HIGH): the classifier detected a crash by
#: looking for the literal ``"Traceback (most recent call last)"``, but the
#: string it is handed comes from ``flow_compliance_check._check_program_exit_zero``
#: as ``(r.stdout[-300:] + "\n" + r.stderr[-300:]).strip()``. One frame line in
#: this tree is ~85-120 characters, so any traceback deeper than two frames has
#: its header cut off. The verifier made ``power_report_check`` raise a KeyError
#: through four frames BEFORE running any check and drove it through this
#: module's own harness: it came back tier **FAIL** — the one tier accepted as
#: proof of falsifiability — and ``test_d2_gate_has_a_reachable_fail[step33]``
#: stayed green. A crash was certifying the gate as falsifiable.
#:
#: 2026-07-28: patching the PATTERNS could not finish the job, because the
#: quantity was being computed from the wrong thing. Both a frame line and an
#: exception message carry ABSOLUTE paths, so what survived the consumer's
#: fixed-offset cut was a function of where the checkout lived. Measured on
#: this tree — one crashing gate, one project, path length the only variable —
#: 107 characters graded ``CRASH`` and 108 graded ``FAIL``. No pattern fixes
#: that; the consumer now decides it against the untruncated streams and says
#: so with :data:`flow_compliance_check._CRASH_HINT_PREFIX`, and this module
#: reads that sentinel first.
#:
#: The patterns remain as the FALLBACK for a snippet that did not come from
#: the live consumer, and they are ALIASES of the consumer's own — a second
#: copy of this logic is what let the two drift in the first place.
_TRACEBACK_FRAME_RE = FCC._TRACEBACK_FRAME_RE
_TRACEBACK_FRAME_TRUNCATED_RE = FCC._TRACEBACK_FRAME_TRUNCATED_RE
_TRACEBACK_CARET_RE = FCC._TRACEBACK_CARET_RE
_TRACEBACK_TAIL_RE = FCC._TRACEBACK_TAIL_RE


def _looks_like_a_traceback(out: str) -> bool:
    """True when *out* carries a Python traceback, header or not.

    Delegates to ``flow_compliance_check.looks_like_python_traceback``: this
    module measures the consumer, so it must not carry its own opinion about
    what a crash looks like.
    """
    return FCC.looks_like_python_traceback(out)


def _classify(passed: bool, out: str) -> str:
    """Map ``_check_program_exit_zero``'s ``(passed, snippet)`` onto a tier.

    Order matters: a crash and a timeout BOTH arrive as ``passed=False`` and
    must be pulled out before the FAIL branch, or an environment problem gets
    counted as a working gate.

    The crash sentinel is read FIRST and is the load-bearing branch: the
    consumer emits it having seen the whole traceback, so it is the one crash
    signal that does not depend on what fitted inside the evidence window.
    ``_looks_like_a_traceback`` stays behind it for snippets that reach this
    function without passing through the live consumer.
    """
    if out.startswith(FCC._CRASH_HINT_PREFIX):
        return CRASH
    if _looks_like_a_traceback(out):
        return CRASH
    if "TIMED OUT" in out:
        return TIMEOUT
    if out.startswith("program not found"):
        return UNWIRED
    if not passed:
        return RED
    if out.startswith(FCC._WAIVER_HINT_PREFIX):
        return WAIVED_TIER
    if out.startswith(FCC._VACUOUS_HINT_PREFIX) or FCC._stdout_signals_vacuous(out):
        return VACUOUS
    return PASS


def _clause_signature(clause) -> str:
    """Stable, human-readable identity for one gate clause.

    Exec clauses are identified by their exact command; the other two kinds by
    their declared payload. Used as the key of :data:`CLAUSE_FIXTURE` and
    :data:`UNREDDENED`, so a clause that is re-worded upstream de-registers
    itself instead of silently inheriting a stale recipe or a stale excuse.
    """
    if clause.command:
        return clause.command
    if clause.kind == F.K_FILES:
        return f"files_exist{'(any_of)' if clause.any_of else ''}: " \
               f"{list(clause.files)}"
    if clause.kind == F.K_JSON_FIELD:
        return (f"json_field_true: {clause.json_file}:{clause.json_field}"
                f"=={clause.json_expect}")
    return clause.raw


def _evaluate_clause(clause, project: Path) -> Tuple[str, str]:
    """Run ONE gate clause against *project* through the real consumer."""
    if clause.command:
        if clause.is_conditional:
            _materialise_conditions(project, clause)
            present = []
            for pat in clause.condition_files:
                present.extend(project.glob(pat))
            if not present:
                return SKIPPED_COND, (
                    f"condition_files_exist {list(clause.condition_files)} "
                    f"could not be materialised -> clause skipped, cannot fail")
        _prepare_report_dirs(project, clause.command)
        passed, out = FCC._check_program_exit_zero(project, clause.command)
        return _classify(passed, out), out.strip()[-400:]
    if clause.kind == F.K_FILES:
        ok, found, missing = FCC._check_files_exist(
            project, list(clause.files), any_of=clause.any_of)
        return (PASS if ok else RED), f"found={found} missing={missing}"
    if clause.kind == F.K_JSON_FIELD:
        ok, out = FCC._check_json_field_true(
            project, {"file": clause.json_file, "field": clause.json_field,
                      "expect": clause.json_expect})
        return (PASS if ok else RED), str(out)[-400:]
    return PASS, f"unhandled clause kind {clause.kind}"


@pytest.fixture(scope="module")
def _gate_timeout():
    """Pin the environment this module measures in, and restore it.

    Two variables, both pinned for the same reason: a tier that is decided by
    the host rather than by the gate is not a measurement of the gate. See
    :data:`GATE_TIMEOUT_S` and :data:`VERILATOR_BIN_ENV`.

    MODULE scope, not session: these are process-wide environment variables
    and six other test modules exercise ``verilator_coverage_measure``'s
    capability probe. A session-scoped pin stays set until the whole run ends,
    so it would reach into whichever of those pytest happened to schedule
    after this module and silently decide their capability branch too. Module
    scope releases it the moment this module is done.
    """
    pinned = {
        "VIBE_IC_GATE_TIMEOUT_S": GATE_TIMEOUT_S,
        VERILATOR_BIN_ENV: sys.executable,
    }
    prev = {k: os.environ.get(k) for k in pinned}
    os.environ.update(pinned)
    yield
    for k, old in prev.items():
        if old is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old


def _build_project(tmp_root: Path, name: str, fixture: str) -> Path:
    project = tmp_root / name
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    FIXTURES[fixture](project)
    return project


def _params():
    """One param per dimension-2 cell, carrying its waiver mark if any."""
    out = []
    for cell in cells_for(DIM):
        mark = W.xfail_mark(cell.step_id, DIM)
        out.append(pytest.param(cell, marks=[mark] if mark else []))
    return out


# ─────────────────────────────────────────────────────────────────────
# The cell test
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cell", _params(), ids=lambda c: f"step{F.normalize_id(c.step_id)}")
def test_d2_gate_has_a_reachable_fail(cell, tmp_path, _gate_timeout):
    sid = cell.step_id
    key = F.normalize_id(sid)
    clauses = F.gate_clauses(sid)

    # ── NA: no gate at all. The precondition is DECLARED (NA_STEPS) and
    #    CHECKED LIVE in both directions, so the NA cannot rot:
    #      * P0 gains a gate  -> the NA branch reddens here, not silently
    #        upgrades itself to an enforced cell that nobody re-reviewed;
    #      * a gated step loses its gate -> that step's cell reddens instead of
    #        quietly becoming an unremarked NA.
    if key in NA_STEPS:
        assert not F.has_gate(sid), (
            f"step {key} is registered NA for dimension 2 because it declares "
            f"no `gate` — but it now carries "
            f"{F.step_by_id(sid).get('gate')!r} with {len(clauses)} clause(s). "
            f"The NA is stale: this cell must be re-decided and, if the gate "
            f"is real, removed from NA_STEPS")
        assert not clauses, (
            f"step {key} declares no `gate` key yet flowref found "
            f"{len(clauses)} clause(s) — the NA precondition is broken")
        return

    assert F.has_gate(sid), (
        f"step {key} has LOST its gate — it is now ungated and nothing can "
        f"fail on it. That is a new NA that must be reviewed and declared in "
        f"NA_STEPS, not absorbed silently")

    blocking = [c for c in clauses if c.is_blocking]
    advisory = [c for c in clauses if c.is_advisory]
    assert blocking, (
        f"step {key} has {len(clauses)} gate clause(s) and NOT ONE of them can "
        f"block: {[c.kind for c in clauses]} ({len(advisory)} advisory). An "
        f"all-advisory gate is unfailable by construction")

    # ``outcomes`` is keyed by signature, so two clauses sharing one would
    # collapse into a single measurement and the second would vanish — an
    # untested clause reported as tested. Zero duplicates at time of writing;
    # this makes the assumption fail loudly instead of silently.
    sigs = [_clause_signature(c) for c in blocking]
    dupes = sorted({s for s in sigs if sigs.count(s) > 1})
    assert not dupes, (
        f"step {key} declares the same blocking clause more than once: "
        f"{dupes} — one of them would be measured and silently dropped")

    outcomes: Dict[str, Tuple[str, str, str]] = {}
    for idx, clause in enumerate(blocking):
        sig = _clause_signature(clause)
        fixture = CLAUSE_FIXTURE.get((key, sig), "EMPTY")
        project = _build_project(tmp_path, f"c{idx}", fixture)
        tier, detail = _evaluate_clause(clause, project)
        outcomes[sig] = (tier, fixture, detail)

    reds = {s for s, (t, _, _) in outcomes.items() if t == RED}

    # ── (1) the gate as a whole must be able to FAIL.
    assert reds, (
        f"step {key} gate CANNOT FAIL: all {len(blocking)} blocking clause(s) "
        f"reached a non-FAIL tier on a deliberately-broken project — "
        + "; ".join(
            f"{s[:70]!r} -> {t} (fixture {fx}) :: "
            f"{d[:120].replace(chr(10), ' ')}"
            for s, (t, fx, d) in outcomes.items()))

    # ── (2) every blocking clause must be individually falsifiable, except
    #        the ones the UNREDDENED register admits to.
    registered = {s for (st, s) in UNREDDENED if st == key}
    unproven = sorted(
        s for s, (t, _, _) in outcomes.items()
        if t != RED and s not in registered)
    assert not unproven, (
        f"step {key}: {len(unproven)} blocking clause(s) reached no FAIL and "
        f"are not in UNREDDENED — either build a fixture that reddens them or "
        f"register the gap with the tier measured: "
        + "; ".join(
            f"{s[:70]!r} -> {outcomes[s][0]} (fixture {outcomes[s][1]}) :: "
            f"{outcomes[s][2][:120].replace(chr(10), ' ')}"
            for s in unproven))

    # ── (3) anti-rot, direction A: a registered gap whose clause is gone.
    stale = sorted(s for s in registered if s not in outcomes)
    assert not stale, (
        f"step {key}: UNREDDENED still excuses {len(stale)} clause(s) that no "
        f"longer exist as blocking clauses of this gate — delete the entries: "
        f"{stale}. Live blocking clauses are {sorted(outcomes)}")

    # ── (4) anti-rot, direction B: a registered gap that now reddens.
    resolved = sorted(s for s in registered if outcomes.get(s, (None,))[0] == RED)
    assert not resolved, (
        f"step {key}: {len(resolved)} clause(s) in UNREDDENED now reach a real "
        f"FAIL — the gap closed, so the entry is a lie and must be deleted: "
        + "; ".join(
            f"{s[:70]!r} -> FAIL (fixture {outcomes[s][1]}) :: "
            f"{outcomes[s][2][:120].replace(chr(10), ' ')}"
            for s in resolved))


# ─────────────────────────────────────────────────────────────────────
# Module self-checks — these guard the harness itself
# ─────────────────────────────────────────────────────────────────────
def test_d2_covers_every_step_exactly_once():
    """63 cells, one per flow step, no duplicates and no invented ids."""
    cells = cells_for(DIM)
    keys = [F.normalize_id(c.step_id) for c in cells]
    assert len(keys) == len(set(keys)) == len(F.step_ids()), (
        f"dimension-2 parametrisation covers {len(keys)} cells "
        f"({len(set(keys))} distinct) but the flow declares "
        f"{len(F.step_ids())} steps")
    assert set(keys) == {F.normalize_id(s) for s in F.step_ids()}
    assert all(c.dim == DIM for c in cells)


def test_d2_registry_keys_all_name_live_clauses():
    """Both registries must describe clauses that EXIST, right now.

    A recipe or an excuse keyed on a command the yaml no longer spells is a
    fact about a dead string. Without this, an upstream re-wording would leave
    a step silently falling back to EMPTY (recipe) or carrying an excuse for
    nothing (register), and the per-step test would still be green.
    """
    live = {
        (F.normalize_id(sid), _clause_signature(c))
        for sid in F.step_ids()
        for c in F.gate_clauses(sid)
        if c.is_blocking
    }
    dead_fixture = sorted(k for k in CLAUSE_FIXTURE if k not in live)
    dead_waived = sorted(k for k in UNREDDENED if k not in live)
    assert not dead_fixture, (
        f"CLAUSE_FIXTURE names {len(dead_fixture)} clause(s) absent from the "
        f"live flow yaml: {dead_fixture}")
    assert not dead_waived, (
        f"UNREDDENED names {len(dead_waived)} clause(s) absent from the live "
        f"flow yaml: {dead_waived}")


def test_d2_fixture_names_all_resolve():
    unknown = sorted({v for v in CLAUSE_FIXTURE.values()
                      if v not in FIXTURES})
    assert not unknown, f"CLAUSE_FIXTURE names unknown fixtures: {unknown}"
    unused = sorted(set(FIXTURES) - set(CLAUSE_FIXTURE.values()) - {"EMPTY"})
    assert not unused, (
        f"fixtures defined but assigned to no clause: {unused} — an unused "
        f"fixture is untested scaffolding")


def test_d2_unreddened_reasons_are_substantive():
    """The per-clause register may not carry a placeholder.

    Same floor the shared waiver registry applies, reused here because
    UNREDDENED is doing the same job at a finer granularity.
    """
    bad = []
    for (sid, sig), reason in UNREDDENED.items():
        text = (reason or "").strip()
        if len(text) < W.MIN_REASON_LEN:
            bad.append(f"{sid}/{sig[:40]}: reason is {len(text)} chars")
        for phrase in W.FORBIDDEN_REASON_SUBSTRINGS:
            if phrase in text.lower():
                bad.append(f"{sid}/{sig[:40]}: non-reason phrase {phrase!r}")
    assert not bad, "UNREDDENED entries that say nothing checkable: " + "; ".join(bad)


def test_d2_harness_reports_crash_and_timeout_as_non_demonstrations():
    """The tier classifier is the whole integrity of this module.

    If a traceback or a killed subprocess were graded FAIL, every gate in the
    flow would look falsifiable the moment its output directory was missing.
    """
    assert _classify(False, "Traceback (most recent call last):\n  ...") == CRASH
    assert _classify(False, "program TIMED OUT after 120s") == TIMEOUT
    assert _classify(False, "program not found: nope_check") == UNWIRED
    assert _classify(False, "verdict: FAIL\n  [ERROR] REAL_FINDING") == RED
    assert _classify(True, FCC._VACUOUS_HINT_PREFIX + "x . --json y") == VACUOUS
    assert _classify(True, "VACUOUS_PASS: nothing to audit") == VACUOUS
    assert _classify(True, FCC._WAIVER_HINT_PREFIX + "x") == WAIVED_TIER
    assert _classify(True, "[PASS] all good") == PASS

    # ── The shape the consumer ACTUALLY produces ──────────────────────
    # `_check_program_exit_zero` hands back
    # `(stdout[-300:] + "\n" + stderr[-300:]).strip()`, so a traceback deeper
    # than two frames arrives WITHOUT its header. Feeding the classifier only
    # the header form certified it on an input that cannot occur; this is the
    # truncated form, built by running the real truncation over a real
    # traceback rather than by hand-writing what it is assumed to look like.
    try:
        _d2_selfcheck_raise_deep(3)
    except KeyError:
        full = traceback.format_exc()
    truncated = (full[-300:] + "\n").strip()
    assert _classify(False, truncated) == CRASH, (
        f"a header-less (truncated) traceback was graded "
        f"{_classify(False, truncated)!r}, not {CRASH!r}; a crashing gate "
        f"would be certified as falsifiable. Snippet:\n{truncated}"
    )

    # ── The same cut, made DETERMINISTIC. ────────────────────────────
    # `full[-300:]` keeps or drops the header depending on how long this
    # checkout's absolute path is, so on its own it exercises the truncation
    # on some hosts and not others — the same host lottery that let this
    # grader read CRASH on a short path and FAIL on a long one (2026-07-28).
    # This cut starts INSIDE the last frame line's path, so on every host the
    # header AND the `File "` prefix are provably gone and only the frame
    # TAIL is left to recognise the crash by.
    # Built from a traceback with NO caret row (an explicit `raise` statement
    # emits none), so the frame TAIL is the only signal left and this case
    # cannot be carried by the caret corroboration below. Deleting the
    # truncated-frame branch reddens exactly here.
    try:
        _d2_selfcheck_raise_plain(3)
    except KeyError:
        full_plain = traceback.format_exc()
    mid_path = full_plain.rindex('File "') + 12
    headerless = full_plain[mid_path:].strip()
    assert "Traceback (most recent call last)" not in headerless
    assert not re.search(r'^\s*File "', headerless, re.MULTILINE), headerless
    assert not _TRACEBACK_CARET_RE.search(headerless), (
        "this sample carries a caret row, so it no longer isolates the "
        f"truncated-frame branch it exists to prove:\n{headerless}")
    assert _classify(False, headerless) == CRASH, (
        f"a traceback cut mid-path — the shape a long checkout path actually "
        f"produces — was graded {_classify(False, headerless)!r}, not "
        f"{CRASH!r}. Snippet:\n{headerless}"
    )

    # ── And a cut deep enough to take the frame tail too. ─────────────
    # A several-hundred-character exception message pushes even the frame
    # line out of the 300-char window; what is left is the caret row and the
    # exception line, and that pair is still a crash.
    deepest = "\n".join(full.splitlines()[-2:])
    assert not _TRACEBACK_FRAME_TRUNCATED_RE.search(deepest), deepest
    assert _classify(False, deepest) == CRASH, (
        f"a traceback cut below its last frame was graded "
        f"{_classify(False, deepest)!r}, not {CRASH!r}. Snippet:\n{deepest}")

    # ── And the converse: a gate legitimately PRINTING an exception name as
    # its finding must still be a real FAIL, not a crash. ────────────────
    assert _classify(
        False, "verdict: FAIL\n  ValueError: corner name 'ss' is not in the "
               "PVT matrix") == RED
    assert _classify(
        False, 'File "top.v", line 12: syntax error near `endmodule`') == RED
    # A frame-shaped line with trailing text is a tool diagnostic, not CPython.
    assert _classify(
        False, 'Error: in file "top.v", line 12, in module top') == RED
    # The caret row corroborates an exception tail; alone it decides nothing.
    assert _classify(False, "    ~~~~~^^^^^") == RED
    # An indented finding above a column-0 exception-named summary is an
    # ordinary gate report, not a traceback tail. 2026-07-28: it was graded
    # CRASH for one revision, i.e. a working gate reported as having blown up
    # and its demonstration deleted from this dimension's count.
    assert _classify(
        False, "verdict: FAIL\n  [ERROR] 3 corners missing\n"
               "    ss_125c, ff_m40c, tt_25c\n"
               "ConstraintError: 3 of 5 PVT corners are undeclared") == RED


#: Gate shapes that all END in a real unhandled exception, differing only in
#: what CPython leaves AFTER the exception line. Each is run for real, so what
#: is measured is the consumer's answer and not a hand-written guess at it.
#:
#: ``overflows`` records whether the shape's own exception MESSAGE carries the
#: (deliberately deep) project path, and therefore whether the evidence body
#: is provably unrecognisable without the sentinel. It is False for
#: ``syntax_error`` for a real reason and not as an escape hatch: a
#: ``SyntaxError`` names the GATE program's path, which is short, so nothing
#: pushes the traceback out of the window. That shape still measures the
#: disclosure — it is the one CPython renders with no header and no ``, in``
#: frame at all — it just cannot ALSO prove the window overflowed.
_D2_CRASH_SHAPES = {
    # the plain case: the traceback is the last thing on stderr
    "plain": (
        "import sys\n"
        "from pathlib import Path\n"
        "def f(p): return {'only': 1}[str(p)]\n"
        "print('probe: audited 0 files')\n"
        "f(Path(sys.argv[1]).resolve() / 'reports' / 'phase2' / 'x.json')\n",
        True),
    # the exception MESSAGE spans two lines, so the exception line is not last
    "multiline_message": (
        "import sys\n"
        "from pathlib import Path\n"
        "print('probe: audited 0 files')\n"
        "raise ValueError('gate precondition broken under %s\\n"
        "  expected reports/phase2/gates/x.json'\n"
        "                 % Path(sys.argv[1]).resolve())\n",
        True),
    # one cleanup line printed after the traceback, on the way out
    "atexit_after_traceback": (
        "import atexit, sys\n"
        "from pathlib import Path\n"
        "atexit.register(lambda: sys.stderr.write('[cleanup] 0 temp files\\n'))\n"
        "def f(p): return {'only': 1}[str(p)]\n"
        "print('probe: audited 0 files')\n"
        "f(Path(sys.argv[1]).resolve() / 'reports' / 'phase2' / 'x.json')\n",
        True),
    # a SyntaxError in the gate: no header, and the frame line has no `, in`
    "syntax_error": ("def broken(:\n    pass\n", False),
}


@pytest.mark.parametrize("shape", sorted(_D2_CRASH_SHAPES))
def test_d2_a_real_crash_is_disclosed_by_the_consumer_not_guessed(
        shape, tmp_path):
    """Drive a REALLY crashing gate through the REAL consumer, deep path.

    Everything above classifies STRINGS. That leaves the mechanism this
    dimension now depends on — ``flow_compliance_check._CRASH_HINT_PREFIX``,
    emitted by the consumer against the untruncated streams — unmeasured
    here: deleting the whole emit block left all of dimension 2 green
    (MEASURED 2026-07-28, 69 passed). A dimension that DEPENDS on a fact must
    fail when the fact stops being reported, so this cell runs the real
    subprocess through the real consumer at a project path that provably
    overflows the evidence window, and asserts BOTH that the tier is CRASH
    and that the sentinel — not a lucky truncation — is what decided it.

    The four shapes differ only in what follows the exception line. Two of
    them (a multi-line exception message, one atexit line) defeated the first
    version of the disclosure, which required the exception line to terminate
    the stream: MEASURED, both were still CRASH at an 80-character project
    path and FAIL at 400, i.e. the path-length lottery survived inside the
    mechanism that was supposed to end it.
    """
    project = tmp_path.joinpath(*(["d" * 40] * 10))
    project.mkdir(parents=True)
    assert len(str(project)) > FCC._OUTPUT_SNIPPET_CHARS, (
        f"the fixture path is {len(str(project))} chars and does not overflow "
        f"the {FCC._OUTPUT_SNIPPET_CHARS}-char evidence window it exists to "
        f"overflow — this cell would prove nothing")
    src, overflows = _D2_CRASH_SHAPES[shape]
    helper = FCC.PROGRAMS_DIR / f"_d2_crash_probe_{shape}.py"
    helper.write_text(src, encoding="utf-8")
    try:
        passed, out = FCC._check_program_exit_zero(
            project, f"{helper.stem} {project}")
    finally:
        helper.unlink(missing_ok=True)

    assert passed is False, f"{shape}: a crash must never be a PASS"
    assert out.startswith(FCC._CRASH_HINT_PREFIX), (
        f"{shape}: the consumer disclosed no crash for a gate that really "
        f"died, so this dimension is back to guessing from prose at a path "
        f"length where the prose does not survive. Snippet:\n{out}")
    assert _classify(passed, out) == CRASH, (
        f"{shape}: graded {_classify(passed, out)!r}, not {CRASH!r} — a "
        f"crashing gate would be certified as falsifiable.\n{out}")
    body = out.split("\n", 1)[1]
    if overflows:
        # NON-DEGENERACY: without the sentinel this input is NOT recognisable,
        # so the assertion above is measuring the sentinel and nothing else.
        assert not FCC.looks_like_python_traceback(body), (
            f"{shape}: the evidence body still reads as a traceback on its "
            f"own, so this cell no longer isolates the sentinel:\n{body}")
    # The evidence must survive `_evaluate_gate`'s `out[:200]` cut — and the
    # sentence explaining the sentinel must NOT be what fills it, or the
    # disclosure costs the operator every character of the gate's own output.
    assert out[:200].startswith(FCC._CRASH_HINT_PREFIX)
    assert "an unhandled exception is NOT a gate verdict" not in out[:200], (
        f"{shape}: the boilerplate consumed the 200-character evidence "
        f"window that `_evaluate_gate` records:\n{out[:200]}")


def _d2_selfcheck_raise_deep(depth: int):
    """Raise a KeyError through *depth* frames, for the truncation self-check.

    The subscript form is deliberate: CPython 3.11+ renders a ``~~~^^^`` anchor
    row under it, which is the shape the caret corroboration is proved against.
    """
    if depth <= 0:
        return {"only": 1}["missing_key_that_is_deliberately_absent"]
    return _d2_selfcheck_raise_deep(depth - 1)


def _d2_selfcheck_raise_plain(depth: int):
    """The same crash with NO anchor row, for the truncated-frame self-check.

    An explicit ``raise`` statement gets no ``~~~^^^`` row, so a snippet built
    from this traceback isolates the frame-tail branch: nothing else in
    :func:`_looks_like_a_traceback` can decide it.
    """
    if depth <= 0:
        raise KeyError("missing_key_that_is_deliberately_absent")
    return _d2_selfcheck_raise_plain(depth - 1)


def test_d2_flow_yaml_override_is_unset():
    """A run with ``$VIBE_IC_MATRIX_FLOW_YAML`` set grades a file nobody
    reviewed. The ledger asserts this too; repeated here because this module
    shells out 150+ times on the strength of that yaml."""
    assert not os.environ.get(F.FLOW_YAML_ENV), (
        f"{F.FLOW_YAML_ENV}={os.environ.get(F.FLOW_YAML_ENV)!r} — this suite "
        f"would measure an unreviewed flow definition")


# ══════════════════════════════════════════════════════════════════════
# UNIFORM CELL-STATE INTERFACE (read by programs/tests/test_matrix_63x8_coverage.py)
#
# The coverage meta-test must be able to ask every dimension module the same
# question and get an answer the module itself computes. Anything it derived on
# its own would be a second opinion about cells it does not own — the adjacent
# measurement this campaign removes. Both functions are LIVE: they re-derive
# from the current tree on every call, so a cell that changes state changes its
# answer here without anyone editing a table.
# ══════════════════════════════════════════════════════════════════════
def matrix_na_precondition(step_id):
    """Why this cell is NA, re-derived LIVE, or ``None`` when it is answerable."""
    if F.has_gate(step_id):
        return None
    return ("declares no `gate` key at all, so there is no clause whose "
            "falsifiability could be measured")


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if W.waiver_for(step_id, DIM) is not None:
        return "WAIVED"
    return "ENFORCED"
