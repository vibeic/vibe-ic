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

A RED THAT ONLY MEANS "NOTHING IS THERE"
----------------------------------------
2026-08-06. A fifth outcome is refused, and this one was counting as proof
for 33 of the 129 reds this module used to publish.

Two of the five gate-clause kinds name no program at all. Their whole
predicate is the consumer's, quoted verbatim from
``flow_compliance_check._check_files_exist`` (programs/flow_compliance_check.py:2239-2242)::

    if any_of:
        passed = len(found) > 0
    else:
        passed = len(missing) == 0

There is no other term. A ``files_exist`` clause asks whether a path resolves
and asks nothing else, so its FAIL branch is reached by exactly one input —
the path not being there — and the default fixture, ``_f_empty`` — whose
entire body is the docstring "Nothing was produced at all." — is that input by
construction. MEASURED before the repair: 33 of 129 reds were this shape
(``('files_exist','FAIL') 32`` + ``('json_field_true','FAIL') 1``), 100% red
rate, zero exceptions, every one of them on ``EMPTY``.

"It rejects a project where nothing exists" does not answer "can this gate
fail?", and the counter-example is in this file's own fixture library:
step 21's ``files_exist: ['phase3/stage3/pnr/routed.def']`` measured against
``PNR_BAD``, whose ``routed.def`` is the 25 bytes
``VERSION 5.8 ;\\nEND DESIGN\\n``, answers **PASS**. A design with no
placement, no routing and no geometry satisfies the clause; only an absent
file does not.

So such a red is graded :data:`ABSENCE_RED` and is NOT a demonstration:

    ABSENCE_RED  the clause FAILed and the artefact it names is not there.
                 For ``files_exist`` that is the only FAIL there is — proven
                 by MEASUREMENT, not by reading the source, in
                 :func:`test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file`,
                 which satisfies every such clause in the live flow with a
                 ZERO-BYTE file and requires all of them to PASS. The day one
                 of them grows a content predicate, that test reddens and the
                 exemption below is re-decided.
                 For ``json_field_true`` it is NOT the only FAIL: a report
                 that exists and states ``false`` is a content red and stays
                 ``FAIL``. The two are separated by asking the consumer's own
                 resolver whether the artefact resolves at all
                 (:func:`_nonexec_artefact_present`), so nothing here
                 re-implements the reports/ or analog/ path fallbacks.

Consequences, both of them deliberate:

  * a ``files_exist`` clause is exempt from the per-clause rule (2) below —
    not excused, EXCLUDED: it has no FAIL a fixture could aim at, so
    registering 32 of them in :data:`UNREDDENED` ("this file could not break
    it") would misdescribe the fact. ``json_field_true`` gets no such
    exemption and must reach a content red or be registered;
  * a STEP whose gate reaches no content red is not falsified. Six did:
    1, 6, 12, 28, 30 and 35 had NO OTHER RED. Three of them are now reddened
    for real, by fixtures built for the purpose (:data:`FIXTURES`
    ``QUARTUS_STUCK_AT``, ``PERC_ESD_FAIL``, ``POST_LAYOUT_NO_SPICE``), which
    also de-registered three :data:`UNREDDENED` entries. The other three —
    1, 12 and 35 — are gated by a file's existence and nothing else, and are
    WAIVED in ``matrix_63x8/waivers.py`` with strict xfail, so the day one of
    them acquires a gate that can judge content the waiver turns the suite red.

Nothing here was made greener by weakening a check: no gate program, no
waiver and no fixture was relaxed, and the count of clauses driven to a real
FAIL went UP.

THE PREDICATE, PER STEP
-----------------------
1. Every **blocking** clause of the step's gate is run against its assigned
   broken fixture. (``advisory_program_exit_zero`` clauses are excluded: they
   run, they report, and they CANNOT fail the step — grading an advisory
   clause as enforcement is measuring something adjacent.)
2. At least one blocking clause must reach a genuine ``FAIL`` **earned by
   content** — a red graded :data:`ABSENCE_RED` does not satisfy this, so a
   step gated only by "the file is there" is not falsified by this module.
3. **Every** blocking clause must reach ``FAIL``, except the ones named in
   :data:`UNREDDENED` — the honest, per-clause register of what this file
   could not break — and except ``files_exist`` clauses, which have no FAIL
   other than absence (see above). Without (3), a step could hide an
   unfailable program behind one trivially-failing sibling clause, which is
   the "at least one green light is on" fallacy in miniature.
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

LIVE, not remembered: 182<!--figure:blocking_clauses--> blocking clauses over
67<!--figure:gated_steps--> gated steps. This is the denominator a reader
wants, and it moves with the yaml: the digits are written by
``tools/gen_matrix_63x8_census.py`` and the ``<!--figure:...-->`` anchors name
the bindings that produced them (vibe-ic#961). Do not hand-edit them.

The paragraph below is a PINNED RECORD of what was measured while this file
was built, not a claim about the tree now. It is kept verbatim on purpose:
re-deriving a dated measurement destroys the only evidence that the decision
taken then was taken on real numbers (``programs/_derived_corpus_figure.py``,
"THE THREE HONEST DISPOSITIONS OF A STATED FIGURE"). Read it as history, and
read the live count above as the denominator. MEASURED while writing this
note: the flow yaml at the last commit of 2026-07-28 carries 149 blocking
clauses, not 150, so the pinned figure does not reproduce at that vintage
either — reported, not silently overwritten.

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
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, Dict, Tuple

import pytest

import flow_compliance_check as FCC

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W
from matrix_63x8.cells import cells_for

DIM = 2

#: The shipped ``programs/`` directory — this file's own parent's parent.
#: Two release-document fixtures below run a producer out of it rather than
#: hand-writing a document set; :func:`_run_producer` records why.
_PROGRAMS = Path(__file__).resolve().parents[1]

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

#: A FAIL whose whole cause is that the artefact the clause names is not
#: there. Refused as a demonstration — see the module docstring. Its own tier
#: rather than a boolean so it shows up, spelled out, in every failure message
#: this module prints: "the red you were counting was the empty directory".
ABSENCE_RED = "FAIL_ON_ABSENCE_ONLY"

#: The tiers that are a genuine demonstration of falsifiability. Exactly one,
#: kept as a named set so a future tier cannot be added to the accepted side by
#: editing a comparison in one branch and forgetting the other three.
DEMONSTRATIONS: Tuple[str, ...] = (RED,)

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


#: A Quartus map report carrying two of the four silent-failure indicators
#: ``quartus_map_audit`` scans for (programs/quartus_map_audit.py:12-27),
#: inside a build the tool called successful. ``_MAP_RPT_CLEAN`` is the SAME
#: report with those two lines removed and nothing else changed, so the
#: negative control differs from the fixture in the findings alone.
_MAP_RPT_HEAD = (
    "Analysis & Synthesis report for top\n"
    "Info (12128): Elaborating entity \"top\" for the top level hierarchy\n"
)
_MAP_RPT_TAIL = (
    "Info: Quartus Prime Analysis & Synthesis was successful. "
    "0 errors, 2 warnings\n"
)
_MAP_RPT_STUCK = _MAP_RPT_HEAD + (
    "Warning (13410): Pin \"led[3]\" is stuck at GND\n"
    "Warning (10030): Net \"cfg_reg[2]\" has no driver or initial value\n"
) + _MAP_RPT_TAIL
_MAP_RPT_CLEAN = _MAP_RPT_HEAD + _MAP_RPT_TAIL


def _write_perc_signoff(p: Path, esd_result: str) -> None:
    """Write step 28's three declared PERC artefacts as ONE coherent sign-off,
    with the ESD category's conclusive result as the only variable.

    A builder rather than two sets of literals because ``perc_signoff_check``
    cross-checks the JSON against both human-readable projections
    (programs/perc_signoff_check.py:78-126): a negative control that corrected
    only the JSON would leave the .rpt and the memo asserting the old verdict
    and would come back FAIL for a SECOND reason — measured, verbatim:
    ``perc_equivalent.rpt states overall verdict 'FAIL' but
    perc_equivalent.json states 'PASS'``. That control would have "passed" the
    fixture while proving nothing about the ESD arm. Driving all three from
    one argument means the fixture and its control differ in exactly the thing
    the gate is being asked to judge.
    """
    verdict = "FAIL" if esd_result == "FAIL" else "PASS"
    note = "2 of 14 pads have no ESD clamp on the VDDIO ring"
    _w(p, "reports/phase3/perc_equivalent.json",
       {"verdict": verdict,
        "categories": [
            {"category": "ESD_PAD_RING", "status": "AUTOMATED",
             "result": esd_result, "note": note},
            {"category": "LATCHUP_WELL_TAP", "status": "AUTOMATED",
             "result": "PASS"},
        ]})
    _w(p, "reports/phase3/perc_equivalent.rpt",
       "PERC-equivalent reliability sign-off\n"
       f"ESD_PAD_RING: {esd_result}"
       + (f" — {note}\n" if esd_result == "FAIL" else "\n")
       + "LATCHUP_WELL_TAP: PASS\n"
       f"OVERALL VERDICT: {verdict}\n")
    _w(p, "reports/phase3/PERC_SIGNOFF_MEMO.md",
       "# PERC sign-off memo\n\n"
       f"**Overall verdict:** `{verdict}`\n\n"
       f"- ESD_PAD_RING — {note if esd_result == 'FAIL' else 'clean'}\n"
       "- LATCHUP_WELL_TAP — clean\n")


def _write_quartus_build(p: Path, map_rpt: str) -> None:
    """Write a finished Quartus build tree with the map report as the only
    variable, and the hand-written audit JSON the gate exists to distrust
    (programs/quartus_map_audit.py:43-58) always claiming a clean audit."""
    _w(p, "phase2/stage1/fpga/output_files/top.sof", "sof-stub")
    _w(p, "phase2/stage1/fpga/output_files/top.map.rpt", map_rpt)
    _w(p, "reports/phase2/fpga/quartus_map_audit.json",
       {"verdict": "PASS", "audited": True, "findings": []})


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


def _f_ldoc_todo(p: Path) -> None:
    """An L doc still carrying the generator's `__TODO__` placeholder.

    `l_doc_todo_stub_count_check` was wired into D1 by vibe-ic#704 and had no
    fixture proving its FAIL reachable. EMPTY answers VACUOUS_PASS by design —
    no `generated_docs/` means phase1 has not run, which is not the same as an
    incomplete extraction — so the fixture has to produce the docs AND leave a
    placeholder in one."""
    _w(p, "phase1/generated_docs/L1_DATASHEET.json",
       {"ic_name": "probe", "fields": {"supply_v": "__TODO__"}})
    _w(p, "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
       {"ic_name": "probe", "ports": []})


def _f_signoff_unverifiable(p: Path) -> None:
    """A sign-off DRC certificate with NO parseable verdict and NO geometry,
    and a PORTLESS top .subckt beside it.

    vibe-ic#717 wired `drc_vacuous_pass_check` and `lvs_signoff_guard` into
    step 31 and neither had a fixture proving its FAIL reachable. Both are
    fail-safe gates, so each needs the ABSENCE of positive evidence rather than
    the presence of a bad number:

      drc  DRC_UNVERIFIABLE_RUN — a report whose verdict will not parse and
           behind which no geometry can be established. A clean requires
           positive evidence; this supplies none.
      lvs  a top `.subckt` with no ports, so a netgen verdict about it is
           anchored to nothing.
    """
    # It must READ as a DRC report (`_is_drc_log` looks for drc/violation/error)
    # and still yield no verdict — a bare "no verdict here" file is SKIPped as
    # not-a-DRC-report and reddens nothing. This is the killed-mid-write shape.
    _w(p, "reports/phase3/drc_signoff.rpt",
       "signoff DRC deck run started\n"
       "(the tool was killed before it wrote a verdict line)\n")
    _w(p, "reports/phase3/lvs.rpt", "Final result: Circuits match uniquely.\n")
    _w(p, "phase3/stage3/extracted/chip_top.spice",
       ".subckt chip_top\nX1 a b sky130_fd_sc_hd__inv_1\n.ends\n")


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


def _f_pnr_tcl_hold_only(p: Path) -> None:
    """The hold-only P&R script — the measured silicon-DOA shape.

    `pnr_timing_repair_completeness_check` was wired into step 17 as a blocking
    clause, and neither EMPTY nor PNR_BAD can redden it: it audits the P&R
    SCRIPT, and PNR_BAD writes only DEFs. Both answer rc=2 — a disclosed skip,
    not a falsification. MEASURED, verbatim:

        EMPTY    rc 2  VACUOUS_PASS: … no OpenROAD P&R Tcl flow to audit
                       error: phase3/stage3/pnr: not found
        PNR_BAD  rc 2  VACUOUS_PASS: … no OpenROAD P&R Tcl flow to audit
                       error: phase3/stage3/pnr: no pnr*.tcl in this directory

    Presence alone is not enough either: a script carrying `set_wire_rc` +
    `repair_design` + `repair_timing -setup` PASSes, which is the whole point.
    The smallest input that reaches the verdict and fails it is a script that
    repairs HOLD and nothing else — without `set_wire_rc` OpenSTA has no
    per-layer R/C, so `repair_timing -setup` aborts and high-fanout nets ship
    unbuffered. MEASURED on THIS fixture through the exact clause command:

        rc 1  FAIL: … [phase3/stage3/pnr/pnr.tcl] — setup_chain=NO; hold=yes;
              [hold_only_antipattern] script runs `repair_timing -hold` but
              NONE of {set_wire_rc, repair_design, repair_timing -setup}

    NEGATIVE CONTROL, same tree, only the script's content changed to the
    complete chain:

        rc 0  PASS: … setup_chain=yes; hold=yes; missing_required=none

    so the red is the verdict and not the tree shape. The DEFs are here so the
    fixture is a plausible post-placement tree rather than a lone Tcl; the
    script is what the gate judges.
    """
    for n in ("floorplan.def", "placed.def"):
        _w(p, f"phase3/stage3/pnr/{n}", "VERSION 5.8 ;\nEND DESIGN\n")
    _w(p, "phase3/stage3/pnr/pnr.tcl",
       "read_lef merged.lef\n"
       "read_def floorplan.def\n"
       "global_placement\n"
       "detailed_placement\n"
       "repair_timing -hold\n"
       "write_def placed.def\n")


def _f_hold_corner_contradicted(p: Path) -> None:
    """A hold sign-off whose DECLARED corner contradicts its own script.

    `hold_corner_coverage_check` was wired into step 23 as a blocking clause
    and EMPTY answers rc=2 NOT CHECKED by design: a run that produced no hold
    sign-off record at all has no corner to judge, and that disclosed skip is
    what lets the clause be wired unconditionally. So the fixture has to
    produce a hold sign-off AND make it wrong.

    MEASURED, EMPTY, verbatim:

        rc 2  VACUOUS_PASS: … NOT CHECKED [NO_HOLD_SIGNOFF_ARTEFACT]

    It is wrong in the way that MATTERS, not the easy way. The easy fixture is
    a stance declaring `hold_process_corner: "TT"`, which reddens through the
    declared field alone. This one declares "FF" — the CORRECT label — beside a
    script whose only `read_liberty` is `..._ss_...` and whose own banner says
    `process=SS`. Until the worst-of repair, project mode returned the moment
    the stance existed and never opened the script, and reddening this clause
    with a bare TT stance would have proved the gate blocks while leaving the
    arm that was actually broken — a declared field outranking the evidence it
    summarises — unmeasured. Two published roots carry BOTH artefacts, so the
    discarded input was not hypothetical.

    MEASURED on THIS fixture through the exact clause command:

        rc 1  verdict: FAIL   judged corners: ['SS'] (basis: declared_hold_view)
              source[stance] PASS [HOLD_AT_FF]  reports/…/mcorner_ocv_stance.json
              source[tcl] FAIL [HOLD_NOT_AT_FF] phase3/…/sta_mcorner_ocv_hold.tcl
                                                                     <- DECIDES

    TWO CONTROLS, both on this same fixture, because one alone would not
    separate "the gate blocks" from "the repair is what blocks it":

      * the stance ALONE — the input the pre-repair project mode judged, still
        reachable as the shipped `--stance` mode:
            rc 0  verdict: PASS   declared hold_process_corner: 'FF'
        so this tree is exactly the false PASS, and the red below is the
        worst-of repair doing the work.
      * the script rewritten to AGREE with the label (ff liberty, banner
        `process=FF`), everything else untouched:
            rc 0  verdict: PASS
        so agreeing evidence is not reddened.
    """
    _w(p, "reports/phase3/mcorner_ocv_stance.json",
       {"hold_process_corner": "FF", "setup_process_corner": "SS",
        "multi_process_corner": True,
        "report": "phase3/stage3/sta/mcorner_ocv.rpt"})
    _w(p, "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl",
       "# === HOLD corner: process=SS "
       "liberty=/pdk/lib/stdcells__ss_100C_1v60.lib ===\n"
       "read_liberty /pdk/lib/stdcells__ss_100C_1v60.lib\n"
       "read_verilog top_pnr.v\n"
       "link_design top\n"
       "report_checks -path_delay min -digits 4\n")


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


def _f_step_fail_unacknowledged(p: Path) -> None:
    """A step-internal FAIL that nobody acknowledged, beside a step that says it
    passed — the anti-fabrication shape doctrine rule #4 exists to catch.

    Reddens the Step-36 clause ``step_internal_fail_bubble_up_check .``, which
    was wired BLOCKING by D9 Phase 1 on 17 measured reds across the published
    corpus. Neither absence nor presence alone reaches it, and that is the whole
    reason this fixture is not ``EMPTY``. MEASURED, verbatim:

        EMPTY   rc 2  [CANNOT DETERMINE] step_internal_fail_bubble_up: no
                      reports/ tree (pre-output project), so no report was
                      examined. NOT a pass

    i.e. the gate REFUSES a zero denominator rather than passing it, so an empty
    project can never redden it. The report has to exist, carry ``verdict:
    FAIL``, and go unacknowledged.

    The PASS report beside it is load-bearing twice over: it gives the gate a
    real denominator to disclose, and it proves the fixture reddens on the FAIL
    verdict specifically rather than on "a report exists at all".

    Chip-AGNOSTIC and version-less by construction: an invented step name, no
    process, no vendor, no tool.
    """
    _w(p, "reports/some_internal_step.json", {"verdict": "FAIL"})
    _w(p, "reports/another_internal_step.json", {"verdict": "PASS"})


def _f_pdk_declared_not_used(p: Path) -> None:
    """The design declares one process and the tools loaded another.

    Reddens the Step-36 clause ``declared_pdk_is_the_pdk_used_check .``, wired
    BLOCKING by D9 Phase 2 on ONE measured red across the published corpus —
    a root whose own L19 names one process while its PnR log names another
    vendor's tech + stdcell LEF.

    EMPTY cannot reach it, and after vibe-ic#1002 that is a VIRTUE rather than
    a gap. MEASURED, verbatim:

        EMPTY   rc 2  declared_pdk_is_the_pdk_used: rc=2 NOT CHECKED — the
                      design declares no PDK target and no cell library was
                      loaded — no physical implementation to judge

    The gate refuses a zero denominator, so BOTH halves of its question have to
    be present before it has anything to judge: a declaration, and a recorded
    library load to compare it against. A fixture carrying only the declaration
    is ALSO rc 2 now (that is exactly the change #1002 made), so this fixture
    is the minimum that reddens — which is what makes it a real negative
    control rather than a way of tripping an unguarded branch.

    Chip-, PDK- and vendor-AGNOSTIC by construction: both names are invented,
    and the rule under test is agreement between two records, not the identity
    of either.
    """
    _w(p, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
       {"doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
        "fields": {"pdk_target": "Example Foundry ZQ42-K3"}})
    _w(p, "phase3/stage3/pnr/pnr.log",
       "[INFO ODB-0227] LEF file: /pdks/othernode/othernode_fd_sc_hd.lef\n"
       "[INFO STA-0001] Liberty: /pdks/othernode/othernode_fd_sc_hd__tt.lib\n")


def _f_em_peak_exceeds_supply(p: Path) -> None:
    """The EM report contradicts itself: a branch carries more current than the
    net is supplied with.

    Reddens the Step-25 clause
    ``em_peak_current_authority_check . --json reports/phase3/em_current_authority.json``.

    EMPTY cannot reach it, and after vibe-ic#1017 that is a VIRTUE rather than a
    gap. MEASURED on an empty tree, verbatim:

        EMPTY   rc 2  INCOMPLETE: electromigration was NOT screened — missing
                      authority: per-layer Jmax (PDK tech LEF DCCURRENTDENSITY,
                      or a --jmax JSON); and the net supply current ...

    Through #1000 that same tree exited **0** and PASSED this BLOCKING clause
    while printing ``NOT screened`` — which is why `test_d2_gate_has_a_reachable_fail`
    was red on main for five merges. The refusal now leaves through the exit
    code as well as the text, so the fixture below has to carry a real
    contradiction to redden the cell.

    The finding is `EM_PEAK_CURRENT_EXCEEDS_SUPPLY`, and it is ORACLE-FREE: no
    Jmax, no PDK, no golden value is consulted. The report states its own
    supply authority (``Total power / Supply voltage``) and its own peak segment
    current, and the peak is 9x the supply. **No branch of a grid can carry more
    current than the supply injects**, so the artefact refutes itself on
    conservation of charge — the limit is 1.0 because it is physics, not a
    guardband.

    Chip-, PDK- and vendor-AGNOSTIC by construction: the numbers are invented
    and the rule is internal consistency of one report, not agreement with any
    process.
    """
    _w(p, "reports/phase3/em.rpt",
       "Electromigration summary\n"
       "Net: VDD\n"
       "  Supply voltage: 1.8 V\n"
       "  Total power: 1.0e-03 W\n"
       "  Maximum current: 5.0e-03 A\n")


def _f_power_over_budget(p: Path) -> None:
    """Total power exceeds the budget the design's own L19 declares.

    Reddens the Step-33 clause
    ``power_total_vs_budget_check . --json reports/phase2/gates/power_budget.json``.

    EMPTY cannot reach it, and after vibe-ic#1017 that is a VIRTUE. MEASURED on
    an empty tree, verbatim:

        EMPTY   rc 2  INCOMPLETE: total power was NOT compared against
                      anything — missing authority: L19_CONSTRAINTS_PDK.json
                      fields.power_budget_uw ...

    Through #1000 that tree exited **0** into a BLOCKING clause.

    BOTH halves are load-bearing, which is what makes this a real negative
    control rather than a way of tripping an unguarded branch: a fixture with
    only the report and no budget is rc 2 (nothing to compare against), and a
    fixture with only the budget and no report is rc 2 as well (nothing to
    compare). The gate refuses to derive a budget from die area or supply
    voltage — a threshold nobody declared would turn an unanswered question
    into an answered one — so the declaration has to be present and the
    measurement has to be present before there is a verdict to earn.

    330 uW against a declared 100 uW: 3.3x over. Chip- and PDK-AGNOSTIC — a
    watt figure, a micro-watt budget, and the design's own number as the only
    authority.

    A THIRD HALF BECAME LOAD-BEARING IN v1.11.22 AND THIS FIXTURE DID NOT SAY SO
    ----------------------------------------------------------------------------
    `POWER_ANALYSIS_MODE: vectorless_sdc` is not decoration on the report above.
    Until v1.11.22 the gate compared any watt figure to the budget; it now
    refuses — rc 2, INCOMPLETE — a figure whose ACTIVITY BASIS it cannot derive,
    because a vectorless estimate and a VCD-driven measurement are both "total
    power" and are not the same number. MEASURED on this fixture with the mode
    line removed, verbatim:

        rc 2  INCOMPLETE: total power was NOT compared against anything —
              missing authority: the total-power record's activity basis is
              'UNSTATED' ...

    and rc 2 is a VACUOUS_PASS to `check_step`, so the blocking Step-33 clause
    became one no input could redden — silently, because the fixture still
    "worked" in the sense of being read. `test_d2_gate_has_a_reachable_fail`
    [step33] is the mutation arm: delete the mode line and it goes red naming
    this clause. `vectorless_sdc` and NOT a vector mode deliberately — a
    declared vector basis is CONTRADICTED unless the transcript corroborates it
    (`_ppa/power.py`: zero published vector report in this repository does), and
    a fixture that has to fake a corroborating annotation count would be
    asserting an activity model it never ran.
    """
    _w(p, "reports/phase2/power.rpt",
       "POWER_ANALYSIS_MODE: vectorless_sdc\n"
       "Group                  Internal  Switching    Leakage      Total\n"
       "                          Power      Power      Power      Power (Watts)\n"
       "-----------------------------------------------------------------\n"
       "Total                  1.00e-04   2.00e-04   3.00e-05   3.30e-04 100.0%\n")
    _w(p, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
       {"doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
        "fields": {"power_budget_uw": 100}})


def _f_area_over_ceiling(p: Path) -> None:
    """Synthesised cell area exceeds the die the design's own L19 declares.

    Reddens the Step-9 clause
    ``area_total_vs_budget_check . --json reports/phase2/gates/area_budget.json``.

    The AREA sibling of :func:`_f_power_over_budget`, and it needs the same
    three things present for the same reason. EMPTY cannot reach it, and that
    is a virtue rather than a gap. MEASURED on an empty tree, verbatim:

        EMPTY   rc 2  INCOMPLETE: synthesised area was NOT compared against
                      anything — missing authority: L19_CONSTRAINTS_PDK.json
                      fields.die_area_budget_um ...; a readable chip_area in
                      any synth stats artefact

    THREE halves are load-bearing here, not two, and the third is the one the
    power axis does not have:

      * a tree with only the stats and no ceiling is rc 2 (nothing to compare);
      * a tree with only the ceiling and no stats is rc 2 (nothing to compare);
      * a tree with BOTH, where `chip_area_unit` does not name um^2, is ALSO
        rc 2 — because `phase2/stage2/synth/stats.json` as the corpus actually
        ships it says "cell-library area unit (as declared by the library the
        synthesis script loaded)", i.e. the PRODUCER declines to name the unit.
        Asserting it anyway would be `ART-POWER-FIGURES-X1000` one axis over: a
        figure off by 1000x reading as the same verdict as the true one.

    So the fixture makes the producer look RUN and WRONG rather than absent: it
    states its unit, states its ceiling, and is 3.0x over it. 6000 um^2 of cells
    against a declared 40x50 um die = 2000 um^2. The limit is 1.0 because
    utilisation cannot exceed 1.0 by definition of the two words — no PDK, no
    guardband and no golden value is consulted, exactly as in
    `_f_em_peak_exceeds_supply`.

    Chip-, PDK- and vendor-AGNOSTIC by construction: invented numbers, and the
    rule is the design's own declaration against the design's own measurement.
    """
    _w(p, "phase2/stage2/synth/stats.json",
       {"schema": "vibe-ic/synth-stats/1",
        "netlist": "phase2/stage2/synth/top_synth.v",
        "top_module": "top",
        "chip_area": 6000.0,
        "chip_area_unit": "um^2",
        "sequential_area": 2400.0,
        "cell_count": 512,
        "includes_submodules": False,
        "selection": {"rule": "SINGLE_MODULE_NO_HIERARCHY"}})
    _w(p, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
       {"doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
        "fields": {"die_area_budget_um": "40x50"}})


# ── The three fixtures that replaced an empty-directory red with a real one ──
#
# Steps 6, 28 and 30 each had exactly one red before 2026-08-06, and each of
# those reds was a `files_exist` clause answering "nothing is there" on
# ``EMPTY``. Their program clauses were all registered in :data:`UNREDDENED`.
# The three fixtures below reach those programs' real verdicts, so the three
# register entries are DELETED rather than re-worded, and each step's cell is
# now carried by a project that produced work and got it WRONG.

def _f_quartus_stuck_at(p: Path) -> None:
    """A Quartus build that reports success while the map report says the
    hardware is dead.

    This is the defect ``quartus_map_audit`` was written from
    (programs/quartus_map_audit.py:7-26): Quartus returns 0 errors having
    optimised a pin to a constant and dropped a net with no driver, and the
    hand-written ``quartus_map_audit.json`` beside it says ``PASS`` — the gate
    re-scans the report on disk rather than trusting that JSON
    (programs/quartus_map_audit.py:43-58).

    Neither absence nor presence alone reaches it. MEASURED, verbatim:

        EMPTY   rc 0  [NO_BUILD] quartus_map_audit: no phase2/stage1/fpga/
                      output_files/*.sof — no Quartus build to audit in this run

    and the same tree with a CLEAN map report — the negative control, run in
    :func:`test_d2_the_three_replaced_empty_reds_are_earned_by_content` —

        rc 0  [PASS] quartus_map_audit: scanned … — no silent-failure indicators

    so the red below is the report's content and not the tree's shape:

        rc 1  [FAIL] quartus_map_audit: 2 silent-failure indicator(s) in
              phase2/stage1/fpga/output_files/top.map.rpt: no-driver,
              stuck-at-gnd
    """
    _write_quartus_build(p, _MAP_RPT_STUCK)


def _f_perc_esd_fail(p: Path) -> None:
    """A PERC sign-off that ran, concluded, and concluded FAIL.

    ``perc_signoff_check`` grades the runner's PERC-equivalent aggregate;
    absence of it is an honest rc=2 skip
    (programs/perc_signoff_check.py:136-139), so ``EMPTY`` cannot reach the
    verdict. MEASURED, verbatim:

        EMPTY  rc 2  __VACUOUS_HINT__: perc_signoff_check . --json …

    The smallest input that reaches the verdict and fails it is an aggregate
    carrying one AUTOMATED category whose result is FAIL — a conclusive
    reliability defect, not an open item (INCOMPLETE / MANUAL_REVIEW are
    named open items and exit 0, :150-:154, :189-:192):

        rc 1  conclusive PERC reliability defect(s): ESD_PAD_RING: 2 of 14
              pads have no ESD clamp on the VDDIO ring

    Both human-readable projections are written and AGREE with the JSON, so
    the red is the ESD category and not the memo cross-check (:78-:126) —
    the negative control flips only the category's ``result`` to PASS and the
    same tree reads ``rc 0 all AUTOMATED PERC categories conclusive PASS``.
    """
    _write_perc_signoff(p, "FAIL")


def _f_post_layout_no_spice(p: Path) -> None:
    """A design taken through extraction and post-route STA, whose timing
    model was never corroborated by SPICE.

    ``spice_correlation_check`` self-skips rc=2 when there is no SPEF (step 20
    not reached) or no STA (step 21 not reached), and its docstring names the
    DIFFERENT case as deliberately non-vacuous:

        "the DIFFERENT case — SPEF and STA both present but no SPICE run at
         all — is deliberately NOT vacuous: it sets `skipped: False` and FAILs
         NO_SPICE_VERIFICATION"
        (programs/spice_correlation_check.py:41-45)

    So ``EMPTY`` measures the skip, not the gate. MEASURED, verbatim:

        EMPTY  rc 2  __VACUOUS_HINT__: spice_correlation_check . --json …

    and on THIS fixture — a project that produced parasitics and a post-route
    timing report and stopped there:

        rc 1  [ERROR] NO_SPICE_VERIFICATION: Post-layout SPICE verification
              was not performed. SPEF extraction exists (Step 20) and STA ran
              (Step 21), but no SPICE decks or results found …
    """
    _w(p, "phase3/stage3/extracted/top.spef",
       '*SPEF "IEEE 1481-1998"\n*DESIGN "top"\n*DIVIDER /\n')
    _w(p, "phase3/stage3/sta/post_route_timing.rpt",
       "Startpoint: din_reg[0] (rising edge-triggered flip-flop clocked by clk)\n"
       "Endpoint: dout_reg[0] (rising edge-triggered flip-flop clocked by clk)\n"
       "  data arrival time      1.2043\n"
       "  data required time     1.5000\n"
       "  slack (MET)            0.2957\n")


def _f_on_board_scenarios_failed(p: Path) -> None:
    """The on-board sign-off record, PRESENT, stating that it did not pass.

    Step 39's ``json_field_true`` clause is the one non-exec clause in the
    whole flow that HAS a content predicate — ``_check_json_field_true``
    compares the resolved field with the expected value
    (programs/flow_compliance_check.py:7012) — so unlike every ``files_exist``
    clause it can be reddened by something other than an empty directory, and
    leaving it on ``EMPTY`` would have hidden that distinction behind a red
    that meant "no such file".

    MEASURED on ``EMPTY``:   ``json file missing: on_board_pass.json``
                             -> graded FAIL_ON_ABSENCE_ONLY
    MEASURED on THIS tree:   ``all_scenarios_passed = False`` -> FAIL

    The reverse case is asserted in
    :func:`test_d2_a_present_but_wrong_json_field_is_still_a_real_red`: the
    same file with the field set True reads PASS, so the red is the recorded
    board result and not the file's presence.
    """
    _w(p, "reports/phase2/fpga/on_board_pass.json",
       {"all_scenarios_passed": False,
        "scenarios": [{"name": "half_duplex_byte6", "passed": False,
                       "observed": "0x00", "expected": "0xF2"}]})


def _f_post_dft_scan_lost(p: Path) -> None:
    """Step 11 genuinely inserted a scan chain; Step 12's own output has
    none — the exact substitution its files_exist-only gate used to miss.

    ``dft_post_optimization_scan_survival_check`` self-skips (rc=2,
    SKIPPED-CONDITION) when ``phase2/stage2/dft/scan_netlist.v`` itself is
    absent — vacuous on ``EMPTY``, so this fixture supplies BOTH artefacts:
    a scan_netlist.v that instantiates a scan flop (scan insertion ran) and
    a post_dft_netlist.v that instantiates none (a plain buffer only) — the
    "scan chain vanished between Step 11 and Step 12" arm, chosen over the
    "byte-identical to the pre-DFT netlist" arm because it does not also
    require staging Step 9's netlist.v to demonstrate.

    MEASURED, verbatim:

        EMPTY  rc 2  __VACUOUS_HINT__: dft_post_optimization_scan_survival_check …
        THIS   rc 1  verdict: FAIL
               scan_netlist.v instantiates 1 DFF-family cell(s) (scan
               insertion ran), but post_dft_netlist.v instantiates 0 — the
               scan chain did not survive post-DFT optimization
    """
    _w(p, "phase2/stage2/dft/scan_netlist.v",
       "module top(a, b, c);\n"
       "  SDFFRQD1 _f0_ (.D(a), .Q(b), .CLK(c));\n"
       "endmodule\n")
    _w(p, "phase2/stage2/synth/post_dft_netlist.v",
       "module top(a, b);\n"
       "  BUF1 _b0_ (.A(a), .Y(b));\n"
       "endmodule\n")


# ─────────────────────────────────────────────────────────────────────
# Steps 15 and 21 — the two obstruction gates
# ─────────────────────────────────────────────────────────────────────
# v1.10.26 (2026-08-09) moved `macro_obs_load_parity_check` and
# `macro_obs_geometry_intersect_check` out of "shipped but invoked by nothing"
# into a BLOCKING gate leg of the step that owns each one's subject, and
# recorded the reachable red in its own message: "with one defective LEF
# staged, macro_obs_load_parity_check returns rc=1 and step 15 goes red".
# CLAUSE_FIXTURE was not extended in that change, so both clauses fell back to
# EMPTY — a tree with no LEF and no DEF, on which each gate correctly answers
# rc=2 __VACUOUS_HINT__ ("I could not read the thing I judge"). That is the
# gates being honest, not the gates being unfalsifiable; what was missing was
# an input. These two fixtures supply it.
#
# chip-AGNOSTIC by construction: every layer, macro and instance name below is
# synthetic LEF/DEF grammar. `macro_obs_load_parity_check`'s rule is
# "referenced but not declared" and never a layer name — held live by
# test_macro_obs_load_parity.py::
# test_the_rule_is_referenced_but_not_declared_not_a_layer_name — so no PDK,
# foundry or process identifier is needed to reach either verdict.

#: The layer an abstract's OBS opens on and the tech LEF may or may not
#: declare. One name, used by both the fixture and its control, so the control
#: differs from the fixture in the DECLARATION and not in the reference.
_OBS_EXTENT_LAYER = "blockExtent"


def _tech_lef(*declared: str) -> str:
    """A tech LEF declaring one routing layer, one cut layer, and whatever
    else *declared* names. The declaration set is the single variable step
    15's negative control moves."""
    extra = "".join(f"\nLAYER {n}\n  TYPE OVERLAP ;\nEND {n}\n"
                    for n in declared)
    return ("VERSION 5.8 ;\n"
            "UNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\n"
            "MANUFACTURINGGRID 0.005 ;\n\n"
            "LAYER metalA\n  TYPE ROUTING ;\n  DIRECTION HORIZONTAL ;\n"
            "END metalA\n\n"
            "LAYER cutA\n  TYPE CUT ;\nEND cutA\n"
            + extra + "\nEND LIBRARY\n")


def _abstract_lef(n_metal: int = 8) -> str:
    """One abstract whose OBS opens on :data:`_OBS_EXTENT_LAYER` and then puts
    *n_metal* rects on a routing layer the tech LEF DOES declare.

    The undeclared entry is FIRST on purpose: a reader that meets a layer it
    cannot resolve inside an OBS stops there and returns success, so the whole
    section — including the rects on the layer it could have loaded — is what
    is lost. That is the position the gate's own measurement calls the common
    one, and the position on which parsed-vs-loadable differ by the most.
    """
    rects = "".join(
        f"      RECT 0.500 {0.5 + i * 0.6:.3f} 39.500 {0.8 + i * 0.6:.3f} ;\n"
        for i in range(n_metal))
    return ("VERSION 5.8 ;\n\nMACRO block_a\n  CLASS BLOCK ;\n"
            "  SIZE 40.000 BY 40.000 ;\n"
            "  OBS\n"
            f"    LAYER {_OBS_EXTENT_LAYER} ;\n"
            "      RECT 0.000 0.000 40.000 40.000 ;\n"
            "    LAYER metalA ;\n" + rects +
            "  END\nEND block_a\n\nEND LIBRARY\n")


def _write_macro_obs_lefs(p: Path, *, declared: bool) -> None:
    """Stage the LEF pair step 15's gate reads.

    *declared* is the ONE thing that differs between the fixture and its
    negative control: the abstract, its OBS, the rect count and both file
    paths are identical in each arm, so a red that came from the tree's shape
    cannot be mistaken for the parity verdict.
    """
    _w(p, "input/pdk/tech.lef",
       _tech_lef(_OBS_EXTENT_LAYER) if declared else _tech_lef())
    _w(p, "input/pdk/block_a.lef", _abstract_lef())


def _f_macro_obs_layer_undeclared(p: Path) -> None:
    """An abstract declares obstruction geometry a reader CANNOT LOAD.

    The tech LEF declares ``metalA`` and ``cutA``; the abstract's OBS opens on
    ``blockExtent``, which no LEF in the set declares. Everything from that
    entry onward is discarded by a real reader, so all 9 parsed OBS rects are
    lost and the footprint loads with no obstruction at all.

    MEASURED, verbatim:

        EMPTY  rc 2  __VACUOUS_HINT__: macro_obs_load_parity_check . --json …
                     ([CANNOT DETERMINE] no LEF under . — a run with no LEF is
                     not a run whose obstructions all loaded)
        THIS   rc 1  [FAIL] 1 macro(s) declare obstruction geometry that a
                     reader CANNOT LOAD — 9 of 9 parsed OBS rect(s) would be
                     discarded

    The reverse arm is asserted in
    :func:`test_d2_the_two_obstruction_gates_redden_and_only_on_content`: the
    same abstract, byte for byte, against a tech LEF that declares the layer
    reads PASS — so the red is the missing declaration and not the tree.
    """
    _write_macro_obs_lefs(p, declared=False)


#: An abstract that declares its extent on ``OVERLAP`` and a real obstruction
#: on a routing layer. Both are needed: a gate that counted ``OVERLAP`` as
#: metal would fire on every macro ever placed, and the geometry gate's own
#: test pins that it does not.
_OBSTRUCTED_MACRO_LEF = (
    "VERSION 5.8 ;\n\nMACRO big_ip\n  CLASS BLOCK ;\n"
    "  SIZE 100.000 BY 60.000 ;\n"
    "  OBS\n"
    "    LAYER OVERLAP ;\n      RECT 0 0 100.000 60.000 ;\n"
    "    LAYER metalA ;\n      RECT 0 0 100.000 60.000 ;\n"
    "  END\nEND big_ip\n\nEND LIBRARY\n")


def _routed_def(*, spanning: int, total: int = 10) -> str:
    """A routed DEF with one placed macro and *total* supply segments, the
    first *spanning* of which run straight across its declared obstruction.

    Only the ORDINATE of a segment changes between the two arms — same macro,
    same orientation, same net, same layer, same segment count — so the
    control cannot pass by having fewer wires or a differently-shaped tree.
    """
    rows = []
    for i in range(total):
        y = 102000 + i * 2000 if i < spanning else 20000 + i * 2000
        rows.append(
            f"- VDD ( * VDD ) + USE POWER + ROUTED metalA 140 + SHAPE "
            f"FOLLOWPIN ( 100000 {y} ) ( 400000 {y} ) ;")
    return ("VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            "COMPONENTS 1 ;\n"
            "- u_ip big_ip + FIXED ( 200000 100000 ) N ;\n"
            "END COMPONENTS\nSPECIALNETS 1 ;\n" + "\n".join(rows)
            + "\nEND SPECIALNETS\nEND DESIGN\n")


def _write_macro_obs_layout(p: Path, *, spanning: int) -> None:
    """Stage the LEF + routed DEF step 21's gate reads."""
    _w(p, "input/pdk/big_ip.lef", _OBSTRUCTED_MACRO_LEF)
    _w(p, "phase3/stage3/pnr/routed.def", _routed_def(spanning=spanning))


def _f_macro_obs_spanned(p: Path) -> None:
    """Supply metal routed straight through a placed macro's obstruction.

    The macro occupies 100x60 um at (200, 100); six of the ten FOLLOWPIN
    segments are placed inside that footprint on the very layer its OBS
    claims. Sign-off DRC cannot see this — a macro obstruction is in the LEF,
    not in the PDK deck — and the wires are attached to the correct net, so a
    connectivity audit cannot either. That is why the gate exists.

    MEASURED, verbatim:

        EMPTY  rc 2  __VACUOUS_HINT__: macro_obs_geometry_intersect_check …
                     ([CANNOT DETERMINE] no routed DEF under .)
        THIS   rc 1  [FAIL] 6 supply segment(s) SPAN a placed macro's declared
                     obstruction (6 of them follow-pins)
                     BY LAYER: metala=6

    The reverse arm is asserted in
    :func:`test_d2_the_two_obstruction_gates_redden_and_only_on_content`: the
    same macro and the same ten segments, moved clear of the footprint, read
    PASS.
    """
    _write_macro_obs_layout(p, spanning=6)


def _f_pad_decl_partial(p: Path) -> None:
    """A tape-out declaration whose pad-ring section was STARTED and abandoned.

    Reddens the Step-15.5ic clause
    ``pad_assignment_gen . --json reports/phase3/pad_assignment.json``,
    wired in vibe-ic#1410/cpath as the author of
    ``phase3/stage3/pnr/pad_assignment.json`` — a path that had two references
    in the whole repository before that change and both were READERS.

    EMPTY cannot reach it, and the reason is the program working correctly.
    With no declaration and no operator slot file it answers NOT_ASKED at rc 2:

        NOT_ASKED: no source answers any of the 8 questions of declaration
        section 2B_pad_ring and no operator slot file pins a per-side pad list

    which the flow reads as its disclosed-skip tier. That is "nobody was asked
    for a pin-out", which is not a statement about a pad ring, and it is the
    tier this suite refuses to count as a red. It is also the state EVERY tree
    in this repository is in, which is exactly why the clause could be wired
    without moving any existing verdict.

    So the fixture has to make the declaration look ANSWERED and INCOMPLETE.
    It writes a well-formed declaration — one the declaration's own validator
    accepts, because an incomplete declaration is deliberately NOT a malformed
    one — carrying SEVEN of section 2B's eight answers and leaving
    ``pad_site_name`` at ``NOT_DETERMINED``. The program's split between an
    ABSENT config and a HALF-WRITTEN one then fires.

    MEASURED, verbatim:

        rc 1  declaration section 2B_pad_ring was STARTED (7 of 8 question(s)
              answered) and still owes 1 of the 13 variables `pad_ring_gen`
              requires ... Still owed: PAD_SITE_NAME (declaration question
              pad_site_name)

    Chosen over an unreadable declaration deliberately: that branch reddens on
    the FILE, and a program that did nothing but try to parse its input would
    pass it. This branch is one the program has to read the CONTENT to reach,
    and it is the exact behaviour the change exists for — a NOT_DETERMINED
    field is NAMED, never guessed, because a pad site invented here would be
    indistinguishable in the artefact from a real pin-out.

    Chip- and PDK-AGNOSTIC: the instance, master and site names are synthetic
    and no design, vendor or process literal appears. No oracle is consulted.
    """
    decl = p / "input" / "submission_template" / "tapeout_declaration.json"
    decl.parent.mkdir(parents=True, exist_ok=True)
    pads = [f"pad_{s}{i}" for s in "senw" for i in range(2)]
    answers = {
        "deliverable": "DIE",
        "pad_order_by_side": {"south": pads[0:2], "east": pads[2:4],
                              "north": pads[4:6], "west": pads[6:8]},
        # "pad_site_name" is DELIBERATELY ABSENT — it is the whole fixture.
        "pad_corner_site_name": "io_corner_site",
        "pad_edge_spacing_um": 10,
        "pad_rotations": {"horizontal": "R0", "vertical": "R90",
                          "corner": "R0"},
        "pad_corner_master": "pad_corner",
        "pad_fillers": ["pad_fill1"],
        "pad_signal_map": {n: n[4:] for n in pads},
    }
    # Built through the declaration's OWN constructor and merge, so the fixture
    # cannot drift into a shape the module would refuse for an unrelated reason
    # and redden this clause by accident.
    import _tapeout_declaration as _TD
    doc = _TD.blank_declaration()
    doc, ignored = _TD.merge_answers(doc, answers)
    assert not ignored, ignored
    assert _TD.validate(doc) == [], _TD.validate(doc)
    assert doc["answers"]["pad_site_name"] == _TD.NOT_DETERMINED
    decl.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _f_die_unfinished(p: Path) -> None:
    """The die-finishing report claims a seal ring the run did not leave behind.

    Reddens the Step-26.5ic clause
    ``die_finishing_check . --json reports/phase3/die_finishing.json``.

    EMPTY cannot reach it and the reason is the gate working correctly: with no
    producer report, `die_finishing_check.evaluate` returns DISCLOSED_SKIP and
    main() prints ``VACUOUS_PASS: die_finishing_check judged nothing`` at rc 2.
    That is "nobody ran the producer", which is not a statement about a seal
    ring, and it is exactly the tier this suite refuses to count as a red.

    So the fixture has to make the producer look RUN and WRONG. It writes the
    producer's own report, correctly attributed (``producer:
    "die_finishing_gen"`` — the gate refuses an unattributed document outright),
    claiming ``seal_ring.state == "PASS"``, and leaves
    ``phase3/stage3/pnr/die_finished.def`` absent. The gate's CROSS-CHECK arm
    then fires: a claim and the thing it claims about are two different facts.

    MEASURED, verbatim:

        rc 1  die_finishing_check: FAIL — the report says the seal ring was
              inserted, but phase3/stage3/pnr/die_finished.def is not on disk —
              the finished die the report describes was not left behind

    Chosen over the simpler ``seal_ring.state == "FAIL"`` deliberately: that
    branch only re-prints a verdict the producer already reached, so a gate that
    did nothing but echo its input would pass it. This branch is one the gate
    has to LOOK at the tree to reach. Chip- and PDK-AGNOSTIC: no design, vendor
    or process literal, and no oracle is consulted.
    """
    _w(p, "reports/phase3/die_finishing.json",
       {"producer": "die_finishing_gen",
        "seal_ring": {"state": "PASS",
                      "reason": "seal ring inserted on the four die edges"},
        "die_id": {"state": "PRESENT",
                   "reason": "die identification cells placed"}})


def _f_hardmacro_kit_incomplete(p: Path) -> None:
    """An IP delivery kit with the LEF and none of the other three views.

    Reddens the Step-37.5ip clause
    ``digital_hardmacro_check . --json reports/phase3/digital_hardmacro.json``.

    EMPTY cannot reach it BY DESIGN, and that design is stated in the gate's own
    docstring: "An absent ``phase3/stage4/hardmacro/`` is NOT a pass. It is rc 2"
    — NOT_DETERMINED, "no digital hardmacro package exists to examine". A step
    whose only red were the absence of the delivery would be measuring that
    nobody delivered, not that a delivery was bad.

    So the fixture DELIVERS. One macro, a real LEF with CLASS BLOCK, SIZE and a
    pin with a port rectangle, and no ``.lib``, no ``.v``, no ``.gds``. That is
    the kit's core failure in the gate's own words — placeable, untimeable,
    unsimulatable, unstreamable.

    MEASURED, verbatim (rc 1, three findings):

        [ERROR] VIEW_MISSING: macro 'core_macro': no `.lib` view. ...
        [ERROR] VIEW_MISSING: macro 'core_macro': no `.gds` view. ...
        [ERROR] VIEW_MISSING: macro 'core_macro': no `.v` view. ...

    Chip- and PDK-AGNOSTIC: the macro name is a generic noun, the layer name is
    LEF's own generic ``met1``, and no branch of the gate reads either.
    """
    _w(p, "phase3/stage4/hardmacro/core_macro.lef",
       'VERSION 5.7 ;\n'
       'BUSBITCHARS "[]" ;\n'
       'DIVIDERCHAR "/" ;\n'
       'MACRO core_macro\n'
       '  CLASS BLOCK ;\n'
       '  FOREIGN core_macro 0 0 ;\n'
       '  ORIGIN 0 0 ;\n'
       '  SIZE 100.000 BY 80.000 ;\n'
       '  PIN clk\n'
       '    DIRECTION INPUT ;\n'
       '    USE SIGNAL ;\n'
       '    PORT\n'
       '      LAYER met1 ;\n'
       '        RECT 1.000 1.000 1.400 1.400 ;\n'
       '    END\n'
       '  END clk\n'
       'END core_macro\n'
       'END LIBRARY\n')


def _run_producer(p: Path, script: str) -> None:
    """Run one of the flow's own document producers over the fixture tree.

    The two release-document fixtures below are the only ones in this module
    that call a producer instead of writing every byte, and the reason is the
    thing ``_release_docs_contract`` exists to prevent. That module is the ONE
    declaration of which documents a release carries and which H2 sections each
    must hold, in which order; it was written because "a generator that decides
    which sections it writes, and a checker that decides which sections it
    demands, are two definitions of the same contract". A hand-typed document
    set in this file would be a THIRD, and the direction it drifts is the
    invisible one: the contract gains a section, the fixture does not, the
    fixture's release reddens on the missing section, and this cell stays green
    while proving something entirely different from what its docstring claims.

    So the clean release is GENERATED from the contract and the defect is
    planted on top of it. What the cell then measures is the gate re-deriving a
    stated quantity and refusing the disagreement — which is the only thing a
    hand-written release could never establish, because it would agree with the
    checker by construction.
    """
    result = subprocess.run(
        [sys.executable, str(_PROGRAMS / script), str(p)],
        capture_output=True, text=True)
    assert result.returncode == 0, (
        f"{script} could not build the clean release this fixture plants its "
        f"defect on — the fixture is broken, not the gate: "
        f"{(result.stdout + result.stderr)[-600:]}")


def _restate_signal_pins(doc: Path, was: int, now: int) -> None:
    """Edit ONE stated pin count in a generated datasheet.

    Asserts the row is there before touching it. A silent no-op here would hand
    the cell a CLEAN release, the clause would answer PASS, and the cell would
    go red saying the gate cannot fail — a true statement about the wrong
    subject. This turns that into a fixture failure that names the row.
    """
    text = doc.read_text(encoding="utf-8")
    old, new = f"| Signal pins | {was} |", f"| Signal pins | {now} |"
    assert old in text, (
        f"{doc.name} no longer states {old!r}, so this fixture plants nothing. "
        f"The datasheet's interface table was re-worded upstream and the "
        f"mutation must be re-aimed, not deleted")
    doc.write_text(text.replace(old, new, 1), encoding="utf-8")


def _f_ip_release_docs_pin_count_lie(p: Path) -> None:
    """A delivered IP kit whose datasheet states a pin count no view supports.

    Reddens the Step-37.5ip clause ``release_docs_check . --arm ip --json
    reports/phase3/release_docs.json``.

    EMPTY CANNOT REACH IT, BY A DESIGN THE FLOW YAML SPELLS OUT at this very
    step: "rc 2 IS RESERVED AND IS NOT REACHABLE HERE ON A RUN THAT DELIVERS A
    KIT. The gate answers rc 2 for exactly one state — no kit and no documents,
    so there is no release to examine". An empty tmp_path IS that one state, so
    the default fixture measured the reserved tier and nothing else.

    Two things are deliberately NOT done here. The fixture does not simply
    delete the documentation: a kit with no documents beside it IS rc 1 (the
    gate's own ``test_a_kit_that_ships_with_no_documentation_is_a_refusal_not_
    a_skip``), but it would show only that the gate noticed a hole, and this
    module's other fixtures are built the other way — every file PRESENT, the
    producer looking RUN AND WRONG. And it does not hand-write the document set;
    see :func:`_run_producer` for why a third copy of the contract is the one
    thing that must not be added.

    So: ``_release_kit`` builds the IP-path project with TWO delivered packages,
    ``ip_release_docs_gen`` documents both, and then the SUBJECT release's
    datasheet is edited to state 7 signal pins. The delivered Verilog view still
    declares 3. That is rule R3, the gate's own headline — "R3 AND R6 ARE THE
    TWO THAT CANNOT BE SATISFIED BY WRITING PROSE" — and it is a branch the gate
    can only reach by reading a SECOND view and comparing.

    MEASURED through ``flow_compliance_check._check_program_exit_zero`` on the
    declared clause (rc 1):

        [ERROR] PIN_COUNT_DISAGREES_WITH_NETLIST (block_a): IP_DATASHEET.md
        states 'Signal pins' = 7, derived from
        `phase3/stage4/hardmacro/block_a.lef`; the netlist view
        `phase3/stage4/hardmacro/block_a.v` declares 3 logical port(s). A
        datasheet with a pin count no view supports is stale on arrival.

    and the UNTOUCHED second package stays green in the same invocation, so the
    red is content-earned and not environmental. Restoring the row returns the
    clause to PASS.

    Chip- and PDK-AGNOSTIC: every literal belongs to ``_release_kit``, whose own
    docstring records that its package names are generic nouns and its PDK
    string is an open PDK this flow already targets.
    """
    import _release_kit as _RK

    _RK.build_project(p)
    _run_producer(p, "ip_release_docs_gen.py")
    _restate_signal_pins(_RK.docs_dir(p) / "IP_DATASHEET.md", 3, 7)


def _f_ic_release_docs_pin_count_lie(p: Path) -> None:
    """A signed-off die whose datasheet states a pin count the netlist refutes.

    Reddens the Step-37.5ic clause ``release_docs_check . --arm ic --json
    reports/phase3/release_docs_ic.json``. The ip sibling above carries the full
    reasoning; this is the SAME defect over the OTHER arm's tree, and the two
    trees are genuinely different — a chip has a routed DEF, a gate-level
    netlist and a metrics file where a hard IP has four views, so sharing one
    fixture would judge one arm over a tree it never sees in a real run. That is
    the same split ``test_release_docs_check_ic_arm`` states for itself.

    ``_ic_release_kit`` builds the chip-path project with two releases,
    ``ic_release_docs_gen`` documents both, and the SUBJECT's
    ``PRELIMINARY_DATASHEET.md`` is edited to state 7 signal pins against a
    netlist that declares 3.

    MEASURED through the same consumer (rc 1):

        [ERROR] PIN_COUNT_DISAGREES_WITH_NETLIST (...): PRELIMINARY_DATASHEET.md
        states 'Signal pins' = 7, derived from `phase3/stage3/pnr/routed.def`;
        the netlist view `phase3/stage3/pnr/widget_pnr.v` declares 3 logical
        port(s). ...

    with the untouched second release green in the same invocation.
    """
    import _ic_release_kit as _IK

    _IK.build_project(p)
    _run_producer(p, "ic_release_docs_gen.py")
    _restate_signal_pins(_IK.docs_dir(p) / "PRELIMINARY_DATASHEET.md", 3, 7)


def _f_reentry_loop_inert(p: Path) -> None:
    """A runner whose only re-entry can neither change nor detect anything.

    Reddens the Step-37.5ic clause ``closed_loop_executed_reentry_census .
    --json reports/phase3/closed_loop_executed_reentry.json``.

    THIS CLAUSE IS THE ONE IN THE MATRIX WHOSE SUBJECT IS NOT THE PROJECT. The
    loops it censuses live in the shipped plugin, not in the tree it is pointed
    at, so ``_plugin_root`` (programs/closed_loop_executed_reentry_census.py)
    falls back to THIS REPOSITORY when the root it is given carries no
    ``vibe-ic-marketplace/plugins/vibe-ic/programs/``. Its own docstring records
    why: without the fallback "the gate would return its zero-denominator
    refusal on every real project and be recorded as `n/a`, which is how a
    census becomes decoration".

    The consequence for THIS module is exact and was measured before this
    fixture existed: on EMPTY the clause censused the shipped plugin — 27 sites
    across 8 runners, INERT=0 — and answered rc 0. Not VACUOUS_PASS, which would
    at least have disclosed a skip: a confident PASS about a tree the fixture
    never wrote. Every project-shaped fixture in FIXTURES would have done the
    same, so no amount of building a better PROJECT could ever have reddened it.

    But the fallback is CONDITIONAL, and that is the way in. A fixture that
    plants the plugin path is censused instead of the repository, and one
    ``step_*`` function calling itself with no varying argument and no read-back
    is the census's INERT verdict — the failing condition its docstring names as
    reachable, here made reachable from a tmp_path.

    MEASURED through ``flow_compliance_check._check_program_exit_zero`` (rc 1):

        [INERT] probe_one_shot_runner.py:2 step_probe -> step_probe: this
        re-entry passes no argument that can differ and the region never reads
        back a result. It re-runs the work and cannot change or detect anything.
        closed_loop_executed_reentry_census: 1 executed re-entry site(s) across
        1 runner(s); ACTUATING=0, SELF_CHECKED_ONLY=0, INERT=1.

    THE CONTROL IS THE SAME FILE WITH THE TWO SIGNALS PUT BACK — a varying
    argument and a read-back the region branches on — which the census grades
    ACTUATING and answers rc 0 for. So the red is earned by the loop's shape and
    not by the fixture having planted a plugin directory at all, which is the
    one alternative explanation available here.

    Chip-AGNOSTIC: the planted module names a step and a runner in the repo's
    own ``step_`` / ``*_one_shot_runner`` convention and nothing else.
    """
    _w(p, "vibe-ic-marketplace/plugins/vibe-ic/programs/probe_one_shot_runner.py",
       "def step_probe(ctx):\n"
       "    for _ in range(3):\n"
       "        step_probe(ctx)\n"
       "    return 0\n")


def _f_extract_illegal_overlap(p: Path) -> None:
    """Magic filed illegal-overlap feedback areas; the extraction is fiction.

    Reddens both Step-31 illegal-overlap clauses: the record validator
    ``magic_illegal_overlap_record_check . --record
    reports/phase3/magic_illegal_overlap.json`` and the independent audit
    ``magic_illegal_overlap_check . --json
    reports/audit/magic_illegal_overlap_audit.json``.

    EMPTY cannot reach it, and the gate's docstring says why in its own terms:
    with no extraction in scope there is "no run for the question to be about",
    which is rc 2 and never a statement that the extraction was clean. ABSENT
    IS NOT ZERO — the distinction is the whole point of the gate — so the
    fixture must supply an extraction that DID run and DID file feedback.

    Two `feedback add` records in magic's own save format, each preceded by its
    `box` line so the structural parser can read it, beside an extracted
    netlist so the extraction is evidenced. Both counting arms then agree at 2,
    which is itself load-bearing: the gate takes the LARGER of the string and
    structural counts and raises FEEDBACK_COUNT_DISAGREEMENT when they differ,
    so a fixture whose records did not parse would redden the gate for the
    WRONG reason and would prove nothing about the overlap arm.

    MEASURED, verbatim (rc 1):

        [ERROR] MAGIC_ILLEGAL_OVERLAP: the extractor reported 2 illegal
        overlap(s), against a threshold of 0. Counted from: feedback dump
        string=2 structural=2 (2 area(s)), transcript=0 ...

    Chip- and PDK-AGNOSTIC: the only literals are magic's own message text (the
    channel itself) and LEF/SPICE-generic layer and device nouns.
    """
    _w(p, "phase3/stage3/extracted/extract_feedback.txt",
       "box 20 20 35 40\n"
       'feedback add "Illegal overlap between nwell and pdiff '
       '(types do not connect)" pale\n'
       "box 61 12 74 26\n"
       'feedback add "Illegal overlap between metal1 and poly '
       '(types do not connect)" pale\n')
    _w(p, "phase3/stage3/extracted/top.spice",
       ".subckt top a b\nM1 a b 0 0 nfet\n.ends\n")


def _f_crosslayer_refuted(p: Path) -> None:
    """A cross-layer search whose candidate is NOT the baseline RTL.

    Step 1.6x landed in v1.11.15 with a blocking gate whose FAIL nothing proved
    reachable, and EMPTY cannot reach it BY DESIGN. The gate's own docstring
    settles why: it was first written CONDITIONAL on the baseline snapshot and
    `flow_condition_reachability_check` refused that shape in one line — "a
    check disabled by exactly the situation it was written for" — so it runs
    unconditionally and answers `NOT_APPLICABLE` for a design that never ran a
    search. On EMPTY that is the honest answer, not a defect, which is exactly
    the position `_f_a0_skipped` was built for one gate over.

    So the fixture has to make a search look ATTEMPTED and REFUTED: the
    baseline snapshot the search writes before it touches a lever, plus a
    rewrite-fidelity report whose status says the candidate diverges. That is
    the step's own closed_loop trigger, spelled in the yaml — "the candidate
    RTL is not the baseline RTL ... The candidate is DISCARDED and step 1's RTL
    stands" — so reddening here is the gate doing the one job it exists for,
    not an artificial break.

    MEASURED: rc 1, `CLX_NOT_EQUIVALENT`. Reached through the program's own
    status ladder rather than by malforming the file — an unparseable report
    would redden the clause too, and would prove only that the gate can crash.
    """
    (p / "reports" / "crosslayer").mkdir(parents=True, exist_ok=True)
    (p / "reports" / "crosslayer" / "baseline_rtl").write_text(
        "cross-layer baseline snapshot marker\n", encoding="utf-8")
    _w(p, "reports/crosslayer/rewrite_equivalence.json",
       {"status": "NOT_EQUIVALENT",
        "compared_points": 4,
        "unproven_points": 0,
        "explanation": ("candidate diverges from baseline at 1 of 4 compared "
                        "points")})


def _f_ppa_h2h_claim_contradicted(p: Path) -> None:
    """A published head-to-head asserts the one-word win its own triple denies.

    Reddens the Step-36 clause ``ppa_head_to_head_check --corpus .``, which the
    PPA lane wires BLOCKING. EMPTY cannot reach it, and the reason is
    structural rather than incidental: the clause is
    ``optional_program_exit_zero`` conditioned on ``**/*head_to_head*.json``,
    and :func:`_materialise_conditions` satisfies that glob with a
    SUBSTANCELESS ``{}``. A document carrying no ``vibeic.ppa.comparison.``
    schema is not a record, so the corpus walk finds a population of zero and
    the gate answers, correctly, that it judged nothing:

        EMPTY  rc 2  __VACUOUS_HINT__: ppa_head_to_head_check --corpus .

    A gate that has only ever said "there was nothing to look at" has not been
    shown able to block, which is what this cell asks.

    WHAT THIS RECORD IS. Two arms over ONE problem, both triples MEASURED, the
    baseline untuned by this project and its configuration sourced, the
    measurement basis declared as simulated, contract identity and scope parity
    intact, every feasibility check clean, tuning parity satisfied. It is a
    record the gate ACCEPTS -- until it states a verdict.

    The triple is deliberately MIXED: the subject is smaller and burns more
    power, so the derived Pareto relation is INCOMPARABLE, which the program's
    own docstring calls the common and honest result. The record then asserts
    ``pareto: SUBJECT_DOMINATES`` against that same triple. C2 forbids the
    record to CARRY a collapsed figure of merit, so the asserted verdict is the
    one route left for an author who wants to say "we won" in a single word --
    and the program says so in those terms: "an unchecked `pareto:
    SUBJECT_DOMINATES` over a mixed triple is that word".

    MEASURED, and in BOTH directions, which is what makes it a negative control
    rather than a way of tripping an unguarded branch:

        this record                    rc 1  VERDICT_CONTRADICTED
                                             "record asserts
                                             pareto='SUBJECT_DOMINATES'; the
                                             numbers in the same record derive
                                             'INCOMPARABLE'"
        the same record, verdict key
        removed and NOTHING else                rc 0  1 accepted

    So the red is earned by the CLAIM contradicting the numbers beside it, not
    by an absent input, a malformed document or a missing field -- reached
    through the program's own derivation rather than by breaking the file.

    Chip-, PDK- and vendor-AGNOSTIC by construction: both flow names and the
    process name are invented, and the rule under test is agreement between a
    stated verdict and the numbers in the same document.
    """
    scope = {
        "area_um2": {"stage": "post_route", "tool": "openroad",
                     "fill": "post_fill"},
        "timing_wns_ns": {"stage": "post_route_extracted", "mode": "functional",
                          "process": "tt", "voltage_v": 1.8,
                          "temperature_c": 25.0, "rc_corner": "max",
                          "clock": "clk", "check": "setup"},
        "power_mw": {"stage": "post_route_extracted", "scenario": "diagnostic",
                     "activity_basis": "VECTORLESS", "liberty": "typical",
                     "tool": "opensta", "process": "tt", "voltage_v": 1.8,
                     "temperature_c": 25.0, "mode": "functional",
                     "group": "Total"},
    }
    units = {"area_um2": "um^2", "timing_wns_ns": "ns", "power_mw": "mW"}
    tools = {"area_um2": ("openroad", "pnr/openroad.log"),
             "timing_wns_ns": ("opensta", "sta/sta.rpt"),
             "power_mw": ("opensta", "diag/power.rpt")}

    def _arm(flow, role, values, tuned, config_source):
        return {
            "flow": flow, "role": role,
            "design": {"spec_sha256": "sha256:" + "1" * 64,
                       "pdk": "open-pdk-a", "clock_target_ns": 10.0,
                       "corners": ["ss", "tt", "ff"]},
            "contract": {"sha256": "sha256:" + "2" * 64,
                         "source": "contract.json"},
            "measurement_basis": "post_route_sta",
            "config_source": config_source,
            "tuned_by_this_project": tuned,
            "ppa": {ax: {"status": "MEASURED", "unit": units[ax],
                         "scope": scope[ax], "value": val,
                         "source": {"path": tools[ax][1],
                                    "sha256": "sha256:" + "0" * 64,
                                    "tool": tools[ax][0],
                                    "parser": f"_ppa/{tools[ax][0]}.py"}}
                    for ax, val in values.items()},
            "feasibility": {"checks": {
                k: {"status": "CLEAN", "violations": 0,
                    "source": "ppa_feasibility_check: SATISFIED (FEAS_OK)"}
                for k in ("setup", "hold", "drv", "drc", "lvs", "antenna",
                          "em", "ir", "equivalence")}},
            "tuning": {"supported": False},
        }

    _w(p, "reports/ppa/head_to_head.json", {
        "schema": "vibeic.ppa.comparison.v2",
        "arms": [
            _arm("their-flow-defaults", "baseline",
                 {"area_um2": 6594.0, "timing_wns_ns": 0.0,
                  "power_mw": 0.573},
                 False, "their flow's shipped defaults, unmodified"),
            #: smaller AND hungrier than the baseline, so the derived relation
            #: is INCOMPARABLE -- the mixed triple the asserted verdict below
            #: collapses into a win.
            _arm("our-flow", "subject",
                 {"area_um2": 5961.0, "timing_wns_ns": 0.0,
                  "power_mw": 0.698},
                 True, "our flow's search winner"),
        ],
        "verdict": {"their-flow-defaults": {"pareto": "SUBJECT_DOMINATES"}},
    })


def _f_slot_pad_over_budget(p: Path) -> None:
    """A design whose declared interface cannot be bonded out on the one slot
    the project ingested — and still cannot after every fold is applied.

    Reddens the Step-2 clause
    ``slot_pad_budget_check . --json reports/phase2/gates/slot_pad_budget.json``,
    wired BLOCKING in vibe-ic#1347. The clause arrived with no fixture, so it
    fell back to EMPTY, and EMPTY cannot reach it. That is the program working
    correctly, MEASURED verbatim on an empty project:

        rc 2  slot_pad_budget_check: UNDECIDED
                no slot files under input/submission_template/slots — step
                0.5ic has not run

    rc 2 is this flow's disclosed-skip tier, so the cell banked a VACUOUS_PASS
    and the gate was declared blocking while nothing could make it block.

    The fixture supplies BOTH halves the program needs before it will answer:
    the slot inventory step 0.5ic ingests, and the step-1 RTL the gate globs
    out of ``phase2/stage1/rtl``. The slot is written in the INGESTED shape —
    ``pads.lists[].raw`` — because that is the only shape a real chip-path
    project has, and reading the operator's RAW ``PAD_<SIDE>`` keys instead is
    a defect this program already shipped once (it counted zero pads and
    returned DOES_NOT_FIT with an authoritative-looking "0").

    MEASURED, verbatim, through the same consumer this suite grades with:

        rc 1  slot_pad_budget_check: DOES_NOT_FIT
                declared signal bits            : 193
                largest slot digital signal pads: 52
                over by                         : 3.71x  (after folding every
                                                  candidate: 2.48x)

    THE FOLD MARGIN IS THE POINT, not a detail. This gate deliberately reports
    fold candidates without applying them, because whether two buses are ever
    simultaneously live is a PROTOCOL fact it does not decide — so a red that
    a competent bond-out could fold away would be a red about arithmetic and
    not about fitting. 2.48x over AFTER folding every candidate is a red no
    bond-out decision can remove, which is the fact the step exists to refuse.
    The one candidate the program names (a 64-bit input and a 64-bit output of
    equal width) is therefore present on purpose: the fixture exercises the
    fold path and still reddens, rather than dodging it.

    Chip-, vendor- and PDK-AGNOSTIC: the module is ``chip_top`` with arithmetic
    port names, the pad instance names are the generic per-side lists, and no
    design, foundry or process literal appears. No oracle is consulted.
    """
    # The pad inventory, in the shape `submission_template_ingest` writes:
    # 40 bidirectional + 12 input = 52 digital signal pads, plus analog, power
    # and corner pads the gate must NOT count as signal.
    entries = (
        [f"bidir\\[{i}\\].pad" for i in range(40)]
        + [f"inputs\\[{i}\\].pad" for i in range(12)]
        + [f"analog\\[{i}\\].pad" for i in range(2)]
        + [f"dvdd_pads\\[{i}\\].pad" for i in range(9)]
        + [f"dvss_pads\\[{i}\\].pad" for i in range(9)]
        + [f"corner\\[{i}\\].pad" for i in range(4)]
        + ["clk_pad", "rst_n_pad"])
    q = len(entries) // 4 + 1
    sides = ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST")
    chunks = [entries[:q], entries[q:2 * q], entries[2 * q:3 * q],
              entries[3 * q:]]
    _w(p, "input/submission_template/slots/slot_1x1.json", {
        "slot": "slot_1x1",
        "die_area": {"width": "3932"},
        "pads": {"pattern": "^PAD.*$",
                 "lists": [{"key": k, "raw": c, "count": len(c)}
                           for k, c in zip(sides, chunks)]},
    })
    # 193 declared signal bits against 52 pads. The two 64-bit operands and the
    # 64-bit result give the program exactly one fold candidate to find, and
    # applying it still leaves the design over the budget.
    _w(p, "phase2/stage1/rtl/chip_top.v", """
module chip_top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [63:0] operand_a,
    input  wire [63:0] operand_b,
    output wire [63:0] result,
    output wire        valid
);
endmodule
""")


FIXTURES: Dict[str, Callable[[Path], None]] = {
    "EMPTY": _f_empty,
    "RTL_BAD": _f_rtl_bad,
    "ANALOG_P3": _f_analog_p3,
    "A0_SKIPPED": _f_a0_skipped,
    "LDOC_TODO": _f_ldoc_todo,
    "SIGNOFF_UNVERIFIABLE": _f_signoff_unverifiable,
    "SYNTH_BAD": _f_synth_bad,
    "SDC_BAD": _f_sdc_bad,
    "PNR_BAD": _f_pnr_bad,
    "PNR_TCL_HOLD_ONLY": _f_pnr_tcl_hold_only,
    "HOLD_CORNER_CONTRADICTED": _f_hold_corner_contradicted,
    "GDS_BAD": _f_gds_bad,
    "GDS_NO_LABELS": _f_gds_no_labels,
    "MFG_BAD": _f_mfg_bad,
    "FMEDA_BAD": _f_fmeda_bad,
    "FMEDA_RTL_BLIND": _f_fmeda_rtl_blind,
    "MS_BAD": _f_ms_bad,
    "TB_BAD": _f_tb_bad,
    "HOLLOW_REPORTS": _f_hollow_reports,
    "QUARTUS_STUCK_AT": _f_quartus_stuck_at,
    "PERC_ESD_FAIL": _f_perc_esd_fail,
    "POST_LAYOUT_NO_SPICE": _f_post_layout_no_spice,
    "ON_BOARD_FAILED": _f_on_board_scenarios_failed,
    "POST_DFT_SCAN_LOST": _f_post_dft_scan_lost,
    "MACRO_OBS_LAYER_UNDECLARED": _f_macro_obs_layer_undeclared,
    "MACRO_OBS_SPANNED": _f_macro_obs_spanned,
    "STEP_FAIL_UNACKNOWLEDGED": _f_step_fail_unacknowledged,
    "PDK_DECLARED_NOT_USED": _f_pdk_declared_not_used,
    "PPA_H2H_CLAIM_CONTRADICTED": _f_ppa_h2h_claim_contradicted,
    "EM_PEAK_EXCEEDS_SUPPLY": _f_em_peak_exceeds_supply,
    "POWER_OVER_BUDGET": _f_power_over_budget,
    "AREA_OVER_CEILING": _f_area_over_ceiling,
    "DIE_UNFINISHED": _f_die_unfinished,
    "HARDMACRO_KIT_INCOMPLETE": _f_hardmacro_kit_incomplete,
    "IP_RELEASE_PIN_COUNT_LIE": _f_ip_release_docs_pin_count_lie,
    "IC_RELEASE_PIN_COUNT_LIE": _f_ic_release_docs_pin_count_lie,
    "REENTRY_LOOP_INERT": _f_reentry_loop_inert,
    "EXTRACT_ILLEGAL_OVERLAP": _f_extract_illegal_overlap,
    "CROSSLAYER_REFUTED": _f_crosslayer_refuted,
    "PAD_DECL_PARTIAL": _f_pad_decl_partial,
    "SLOT_PAD_OVER_BUDGET": _f_slot_pad_over_budget,
}

#: Which fixture reddens which clause. Keyed by ``(normalized step id, exact
#: gate command as spelled in the yaml)`` — so a command that is re-worded
#: upstream loses its assignment, falls back to ``EMPTY``, and (if EMPTY does
#: not redden it) fails loudly rather than silently keeping a stale recipe.
#: Clauses absent from this table use ``EMPTY``.
CLAUSE_FIXTURE: Dict[Tuple[str, str], str] = {
    # vibe-ic#1347 wired `slot_pad_budget_check` BLOCKING on Step 2 and shipped
    # it with no fixture, so it fell back to EMPTY and banked a VACUOUS_PASS —
    # a gate declared blocking that nothing could make block. EMPTY cannot
    # reach it by design: with no ingested slot the program answers rc 2
    # "UNDECIDED: no slot files ... step 0.5ic has not run", which is this
    # flow's disclosed-skip tier and is not an answer to "can this gate fail?".
    #
    # MEASURED through `_evaluate_clause` on this tree:
    #   EMPTY                 tier=VACUOUS_PASS  rc 2 UNDECIDED (no slot files)
    #   SLOT_PAD_OVER_BUDGET  tier=FAIL          rc 1 DOES_NOT_FIT, 193 bits
    #                                            against 52 pads, still 2.48x
    #                                            over after folding every
    #                                            candidate
    # The red is earned on the design's own declared interface against the
    # operator's own pad list, not on a malformed file — and it survives the
    # fold path, so it is not a red a bond-out decision could remove.
    ("2", "slot_pad_budget_check . --json reports/phase2/gates/slot_pad_budget.json"): "SLOT_PAD_OVER_BUDGET",
    # vibe-ic#700 wired this into D1. EMPTY cannot redden it: absence of the
    # forbidden artefact IS the pass, so the clause needs the artefact present
    # AND carrying the forbidden verdict.
    ("D1", "analog_a0_skip_forbidden_check ."): "A0_SKIPPED",
    # Step 1.6x (v1.11.15) — its single blocking clause answers
    # NOT_APPLICABLE on EMPTY and banks a PASS, so nothing proved its FAIL
    # reachable and the cell was red on main from the version it arrived in.
    # See `_f_crosslayer_refuted` for why EMPTY cannot reach it by design.
    # TWO LANES MAPPED THIS SAME CLAUSE AND THE MERGE KEPT ONE, ON EVIDENCE.
    # `CLAUSE_FIXTURE` is a dict, so both entries under one key meant the second
    # silently won and the first was dead code that read as live — the merge
    # hazard, before the question of which fixture is better.
    #
    # BOTH REDDEN, MEASURED through `_evaluate_clause` on this tree:
    #   EMPTY                        tier=PASS  (NOT_APPLICABLE — correct, and
    #                                            therefore no answer to "can it
    #                                            fail?")
    #   CROSSLAYER_SEARCH_UNDECLARED tier=FAIL  CLX_BASELINE_PRESENT_NO_REPORT
    #   CROSSLAYER_REFUTED           tier=FAIL  CLX_NOT_EQUIVALENT
    #
    # Neither is graded ABSENCE_RED, so the choice is not about which counts. It
    # is about what each PROVES. The first reddens on a procedural precondition
    # — a search ran and declared nothing. The second reddens on the relation
    # the step exists for, the candidate diverging from the baseline, reached
    # through the program's own status ladder rather than by malforming a file.
    # The second is kept.
    ("2", "crosslayer_rewrite_equivalence_check . --report reports/crosslayer/rewrite_equivalence.json --baseline-marker reports/crosslayer/baseline_rtl --search-space reports/crosslayer/search_space.json --json reports/crosslayer/rewrite_equivalence_check.json"): "CROSSLAYER_REFUTED",
    # This change moves `reports/phase1/extraction_coverage_report.{md,json}`
    # onto D1 and wires this clause to read it. EMPTY cannot redden it, and for
    # the SAME reason `LDOC_TODO` exists at all: with no `generated_docs/` the
    # gate answers `SKIP — Phase 1 (doc-extraction) not attempted and no
    # input/docs/`, which is a self-skip, not a judgement. The fixture has to
    # make Phase 1 look ATTEMPTED while leaving the coverage report absent.
    #
    # MEASURED against all 12 fixtures via `FCC._check_program_exit_zero`, the
    # same way this register's provenance line was built: three redden it —
    # LDOC_TODO, PDK_DECLARED_NOT_USED, POWER_OVER_BUDGET — each with a content
    # red, `") coverage report missing: …/extraction_coverage_report.md"`. The
    # other nine self-skip. `LDOC_TODO` is chosen because it is the Phase-1
    # fixture and is already D1's assignment for `l_doc_todo_stub_count_check`,
    # so the step's two content reds come from one tree rather than two.
    #
    # It is assigned here rather than registered in `UNREDDENED`: a fixture DOES
    # break it, and an `UNREDDENED` entry whose clause reddens fails this suite
    # by design ("the gap closed and nobody noticed").
    ("D1", "phase1_coverage_report_present_check ."): "LDOC_TODO",
    # D9 Phase 1 wired this into step 36 as the one BLOCKING promotion of that
    # campaign. EMPTY cannot redden it: the gate REFUSES a zero denominator
    # (rc 2, "no reports/ tree … NOT a pass"), so the unacknowledged FAIL has
    # to be present for the gate to have anything to judge.
    ("36", "step_internal_fail_bubble_up_check ."): "STEP_FAIL_UNACKNOWLEDGED",
    # D9 Phase 2 wired this into step 36 (vibe-ic#1002). EMPTY cannot redden
    # it: the gate REFUSES a zero denominator, so both halves of its question
    # -- a declared target AND a recorded library load -- have to be present
    # before it has anything to compare.
    ("36", "declared_pdk_is_the_pdk_used_check ."): "PDK_DECLARED_NOT_USED",
    # The PPA lane wires this into step 36 as its one BLOCKING clause, and it
    # arrived reaching only VACUOUS_PASS: the clause is conditioned on
    # `**/*head_to_head*.json`, `_materialise_conditions` satisfies that glob
    # with a substanceless `{}`, and a document with no
    # `vibeic.ppa.comparison.` schema is not a record -- so the corpus walk
    # judged a population of zero and the gate said so. Nothing had shown the
    # clause able to block, which is the condition this cell exists to catch.
    #
    # MEASURED through `_evaluate_clause` on this tree:
    #   EMPTY                        tier=VACUOUS  __VACUOUS_HINT__ (0 records)
    #   PPA_H2H_CLAIM_CONTRADICTED   tier=FAIL     VERDICT_CONTRADICTED
    # and the same fixture with its `verdict` key removed is rc 0 / 1 accepted,
    # so the red is the claim contradicting its own numbers and not the record
    # being broken.
    ("36", "ppa_head_to_head_check --corpus ."): "PPA_H2H_CLAIM_CONTRADICTED",
    # vibe-ic#1017. #1000 wired both of these BLOCKING and left INCOMPLETE on
    # rc 0, so EMPTY answered PASS to a blocking clause while the programs' own
    # last lines said "NOT screened" / "NOT compared against anything". #1017
    # moved INCOMPLETE to the disclosed-skip tier (rc 2), so EMPTY can no longer
    # carry either cell and each needs an artefact that is WRONG on its own
    # terms -- self-contradiction for EM, an exceeded self-declared budget for
    # power. Neither fixture consults an oracle.
    # 2026-08-20, R7 — the three clauses this suite could reach no FAIL on.
    # Each was VACUOUS_PASS (rc 2) under EMPTY and under every other fixture in
    # the library, and for 26.5ic and 37.5ip that clause is the step's ONLY
    # blocking clause, so the whole cell was unfalsifiable: the gate could not
    # fail on anything a project DID. UNREDDENED is not available for those two
    # -- it is explicitly "NOT a waiver of the CELL" and presumes a sibling
    # clause already proven falsifiable -- so a real fixture was the only
    # honest close. Each new fixture makes the producer look RUN and WRONG
    # rather than absent; see each `_f_*` docstring for the measured rc and
    # message, and for why the chosen FAIL branch is one the gate has to look
    # at the tree to reach.
    ("26.5ic", "die_finishing_check . --json "
               "reports/phase3/die_finishing.json"): "DIE_UNFINISHED",
    # vibe-ic#1410/cpath wired `pad_assignment_gen` into 15.5ic as the AUTHOR
    # of `phase3/stage3/pnr/pad_assignment.json`, which nothing had ever
    # written. EMPTY answers NOT_ASKED at rc 2 — the disclosed-skip tier —
    # because with no declaration and no slot file nobody has been asked for a
    # pin-out, and that is the state every tree in this repository is in. The
    # fixture makes the declaration look ANSWERED AND INCOMPLETE, which is the
    # branch the change exists for: the owed field is NAMED, never guessed.
    # See `_f_pad_decl_partial` for the measured rc and message, and for why
    # the half-written declaration is chosen over an unreadable one.
    ("15.5ic", "pad_assignment_gen . --json "
               "reports/phase3/pad_assignment.json"): "PAD_DECL_PARTIAL",
    ("37.5ip", "digital_hardmacro_check . --json "
               "reports/phase3/digital_hardmacro.json"):
        "HARDMACRO_KIT_INCOMPLETE",
    # 2026-08-31 — THE SAME MISTAKE THREE TIMES, and the shape is worth naming
    # because it is the one this whole dimension exists to catch arriving by
    # the back door. Each of these three clauses was wired BLOCKING into the
    # flow with no entry here, so the harness defaulted it to EMPTY, and for
    # each of them EMPTY is the one input the clause is DESIGNED not to judge:
    #
    #   v1.13.58  37.5ip gains `release_docs_check --arm ip`. Its flow-yaml note
    #             says outright "rc 2 IS RESERVED AND IS NOT REACHABLE HERE ON A
    #             RUN THAT DELIVERS A KIT ... no kit and no documents". EMPTY is
    #             that state. Cell red from that commit, measured at its parent.
    #   v1.13.66  37.5ic gains `closed_loop_executed_reentry_census`, whose
    #             subject is the PLUGIN and not the project — on EMPTY it
    #             censuses this repository and answers a confident rc 0.
    #   v1.13.76  37.5ic gains `release_docs_check --arm ic` on top of an
    #             already-red cell, taking it from one unproven clause to two.
    #
    # None of the three is unfalsifiable and none is registered in UNREDDENED:
    # each has a fixture below that reddens it and a control that does not. What
    # was missing was the fixture, and a cell red for a missing fixture reads
    # exactly like a cell red for an unfailable gate — which is why these are
    # assignments and not excuses.
    ("37.5ip", "release_docs_check . --arm ip --json "
               "reports/phase3/release_docs.json"): "IP_RELEASE_PIN_COUNT_LIE",
    ("37.5ic", "release_docs_check . --arm ic --json "
               "reports/phase3/release_docs_ic.json"): "IC_RELEASE_PIN_COUNT_LIE",
    ("37.5ic", "closed_loop_executed_reentry_census . --json "
               "reports/phase3/closed_loop_executed_reentry.json"):
        "REENTRY_LOOP_INERT",
    ("31", "magic_illegal_overlap_check . --json "
           "reports/audit/magic_illegal_overlap_audit.json"):
        "EXTRACT_ILLEGAL_OVERLAP",
    ("31", "magic_illegal_overlap_record_check . --record "
           "reports/phase3/magic_illegal_overlap.json"):
        "EXTRACT_ILLEGAL_OVERLAP",
    ("25", "em_peak_current_authority_check . --json "
           "reports/phase3/em_current_authority.json"): "EM_PEAK_EXCEEDS_SUPPLY",
    ("33", "power_total_vs_budget_check . --json "
           "reports/phase2/gates/power_budget.json"): "POWER_OVER_BUDGET",
    # The AREA sibling, wired into step 9 in the same change that gave step 9
    # its `closed_loop` edge. Registered as an ASSIGNMENT and not in
    # `UNREDDENED`: a fixture DOES break it, and an `UNREDDENED` entry whose
    # clause reddens fails this suite by design.
    ("9", "area_total_vs_budget_check . --json "
          "reports/phase2/gates/area_budget.json"): "AREA_OVER_CEILING",
    # vibe-ic#704 wired this into D1. EMPTY answers VACUOUS_PASS by design:
    # no generated_docs means phase1 has not run, which is not an incomplete
    # extraction. The docs must exist AND carry a placeholder.
    ("D1", "l_doc_todo_stub_count_check ."): "LDOC_TODO",

    # D1 gained `phase1_coverage_report_present_check` in this change (#1219):
    # the report moved off step 1, so D1 declares it and D1's gate reads it.
    # A wired clause with no fixture is exactly what d2 calls `unproven`.
    #
    # EMPTY cannot redden it, for the same reason `LDOC_TODO` exists: with no
    # `generated_docs/` the gate answers "SKIP - Phase 1 (doc-extraction) not
    # attempted", which is a self-skip, not a judgement. The fixture has to make
    # Phase 1 look ATTEMPTED while leaving the coverage report absent.
    #
    # RE-DERIVED 2026-08-14 against ALL 30 entries of `FIXTURES` via
    # `FCC._check_program_exit_zero`, rather than adopted: exactly THREE redden
    # it - LDOC_TODO, PDK_DECLARED_NOT_USED, POWER_OVER_BUDGET - each with the
    # same content red, `") coverage report missing: .../extraction_coverage_
    # report.md"`. The other 27 self-skip. LDOC_TODO is chosen because it is the
    # Phase-1 fixture and is already D1's assignment for
    # `l_doc_todo_stub_count_check`, so D1's two content reds come from one tree
    # rather than two.
    #
    # Assigned here rather than registered in `UNREDDENED`: a fixture DOES break
    # it, and an `UNREDDENED` entry whose clause reddens fails this suite by
    # design ("the gap closed and nobody noticed").
    ("D1", "phase1_coverage_report_present_check ."): "LDOC_TODO",
    # vibe-ic#717 wired both into step 31. Both are FAIL-SAFE gates, so an
    # EMPTY tree gives them nothing to refuse; each needs the absence of
    # positive evidence to be OBSERVABLE, which means the artefact has to
    # exist and be unverifiable.
    ("31", "drc_vacuous_pass_check . --under reports/phase3/drc_signoff.rpt --json reports/phase3/drc_vacuous.json"): "SIGNOFF_UNVERIFIABLE",
    ("31", "lvs_signoff_guard . --verdict-file reports/phase3/lvs.rpt"): "SIGNOFF_UNVERIFIABLE",
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
    # Wired into step 17 as a BLOCKING clause with this branch. It audits the
    # P&R SCRIPT, so neither EMPTY nor PNR_BAD (DEFs only) reaches its verdict
    # — both answer rc=2 NOT CHECKED. The fixture supplies the hold-only
    # script, which is the shape the gate exists to refuse.
    ("17", "pnr_timing_repair_completeness_check phase3/stage3/pnr --json "
           "reports/phase3/pnr/timing_repair_completeness.json"):
        "PNR_TCL_HOLD_ONLY",
    # Wired into step 23 as a BLOCKING clause with this branch. EMPTY answers
    # rc=2 NOT CHECKED by design — a run with no hold sign-off record has no
    # corner to judge, and that tier is what lets the clause be unconditional.
    # The fixture states a hold sign-off whose declared corner CONTRADICTS its
    # own script, so the arm it reddens is the declared-field-over-evidence
    # one rather than the easier bare-bad-label one.
    ("23", "hold_corner_coverage_check . --json "
           "reports/phase3/sta/hold_corner_coverage.json"):
        "HOLD_CORNER_CONTRADICTED",
    # ── 2026-08-06: the three steps whose ONLY red was an empty directory ──
    # Each of these programs was in UNREDDENED, so each step's cell rested
    # entirely on its `files_exist` sibling answering "nothing is there". The
    # register entries are deleted, not re-worded: the fixtures reach the
    # programs' real verdicts. See each `_f_*` docstring for the measured
    # EMPTY tier these replace and the negative control that separates the
    # verdict from the tree's shape.
    ("6", "quartus_map_audit --project . --json "
          "reports/phase2/gates/quartus_map_audit.json"): "QUARTUS_STUCK_AT",
    ("28", "perc_signoff_check . --json "
           "reports/phase2/gates/perc_signoff.json"): "PERC_ESD_FAIL",
    ("30", "spice_correlation_check . --json "
           "reports/phase2/gates/spice_correlation.json"):
        "POST_LAYOUT_NO_SPICE",
    # The one non-exec clause in the flow that HAS a content predicate. On
    # EMPTY it reddens with "json file missing", which is graded
    # ABSENCE_RED and proves nothing; the fixture supplies the record the
    # board run actually writes, stating that it did not pass.
    ("39", "json_field_true: reports/phase2/fpga/on_board_pass.json:"
           "all_scenarios_passed==True"): "ON_BOARD_FAILED",
    # 2026-08-08: step 12 gained a real content clause (was absence-only,
    # see the ABSENCE_ONLY_STEPS docstring). EMPTY answers rc=2
    # SKIPPED-CONDITION (no scan_netlist.v to compare against) — vacuous,
    # not a demonstration — so the fixture supplies a project where Step 11
    # genuinely ran and Step 12's own output lost the scan chain.
    ("12", "dft_post_optimization_scan_survival_check . --json "
           "reports/phase2/gates/dft_post_optimization_scan_survival.json"):
        "POST_DFT_SCAN_LOST",
    # 2026-08-09 (v1.10.26) wired both obstruction gates into a BLOCKING
    # gate leg; neither got a fixture, so both fell back to EMPTY — a tree
    # with no LEF and no DEF, where each gate answers rc=2 __VACUOUS_HINT__
    # because it cannot read its own subject. The gates were always
    # falsifiable; the harness had no input that reached them. See each
    # `_f_*` docstring for the measured EMPTY tier and the negative control.
    ("15", "macro_obs_load_parity_check . --json "
           "reports/phase3/pnr/macro_obs_load_parity.json"):
        "MACRO_OBS_LAYER_UNDECLARED",
    ("21", "macro_obs_geometry_intersect_check . --json "
           "reports/phase3/pnr/macro_obs_geometry.json"): "MACRO_OBS_SPANNED",
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
    # The command string is the KEY, so it moves with the flow declaration.
    # `--require-measured` (2026-08-27) makes this clause additionally ask
    # whether the run bound to the SPEF carried positive evidence it measured
    # anything; `PNR_BAD` still reddens it for the reason it always did — the
    # artefact is not there to bind.
    ("22", "provenance_check . --output phase3/stage3/extracted/*.spef "
           "--tool magic,openroad --require-measured"): "PNR_BAD",
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
    # ("6", "quartus_map_audit …") — DE-REGISTERED 2026-08-06. The entry read
    # "PASS: needs a real Quartus map report tree (output_files/*.map.rpt)
    # with a defect; no fixture here synthesises one". The premise was right
    # and the conclusion was that nobody had written the fixture, so it was
    # written: QUARTUS_STUCK_AT is a .sof beside a .map.rpt carrying
    # Warning(13410) stuck-at-GND and Warning(10030) no-driver — the two
    # indicators the program's own docstring names — under a build the tool
    # called successful, with the hand-written quartus_map_audit.json beside
    # it still claiming a clean audit. rc 1, deterministically. This mattered
    # more than the entry suggested: step 6's ONLY other red was
    # `files_exist: ['…/*.sof']` on the EMPTY fixture, so with this clause
    # excused the cell's whole green rested on an empty directory.
    ("6", "fpga_verification_audit --report reports/"
          "fpga_verification_report.md --summary phase2/stage1/sim/work/"
          "summary.txt --coverage reports/phase2/coverage/"
          "coverage_verilator.json --out reports/phase2/gates/"
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
    # ("28", "perc_signoff_check …") — DE-REGISTERED 2026-08-06. The entry
    # read "PASS/VACUOUS: needs a PERC-equivalent report present but
    # non-substantive; a hollow report is read as 'PERC not applicable'". It
    # described the wrong input. A hollow aggregate IS read as inapplicable —
    # that part was true — but the gate's FAIL arm is not reached by making
    # the report emptier, it is reached by making it CONCLUDE: one AUTOMATED
    # category with result=FAIL (perc_signoff_check.py:149, :182).
    # PERC_ESD_FAIL states that, with both declared human-readable
    # projections written and AGREEING, so the red is the ESD verdict and not
    # the memo cross-check. Step 28's only other red was
    # `files_exist: ['reports/phase3/perc_equivalent.json']` on EMPTY.
    #
    # ("30", "spice_correlation_check …") — DE-REGISTERED 2026-08-06. The
    # entry read "PASS: needs a SPICE-vs-STA correlation pair that disagrees;
    # both halves must exist and be populated for the FAIL arm to be
    # reachable". That is one FAIL arm and not the only one: the program's
    # own docstring names the other (spice_correlation_check.py:41-45) —
    # SPEF and STA both present and NO SPICE run at all is deliberately not
    # vacuous and FAILs NO_SPICE_VERIFICATION. POST_LAYOUT_NO_SPICE is that
    # tree. The disagreeing-pair arm remains unmeasured by this suite and is
    # named as such in the fix notes; step 30's only other red was
    # `files_exist(any_of)` over the spice deck patterns, on EMPTY.
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


def _nonexec_artefact_present(project: Path, rel: str) -> bool:
    """Does the artefact a non-exec clause names RESOLVE in *project*?

    Asked through ``flow_compliance_check._check_files_exist``, which is the
    consumer's own resolver: it carries the ``reports/<subdir>/`` fallback and
    the canonical-analog-dir remap (``_glob_first``,
    programs/flow_compliance_check.py:1785-1845), and a second implementation
    of those two remaps here is exactly the drift this module refuses
    everywhere else. Nothing is parsed out of the consumer's prose.
    """
    ok, _found, _missing = FCC._check_files_exist(project, [rel], any_of=False)
    return ok


def _evaluate_clause(clause, project: Path) -> Tuple[str, str]:
    """Run ONE gate clause against *project* through the real consumer.

    The two non-exec kinds are where a FAIL can mean nothing at all, so their
    FAIL is split in two — see the module docstring for the measurement that
    forced this.

    ``files_exist``  — the consumer's entire predicate is
        ``passed = len(missing) == 0`` (or ``len(found) > 0`` for any_of),
        programs/flow_compliance_check.py:2239-2242. A FAIL therefore says one
        named pattern matched nothing and says nothing else, so it is ALWAYS
        :data:`ABSENCE_RED`. That is not an assumption: every such clause in
        the live flow is satisfied by a ZERO-BYTE file in
        :func:`test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file`.

    ``json_field_true`` — has a real content predicate (``v == expect``,
        programs/flow_compliance_check.py:7012), so its FAIL is split by
        whether the artefact is there at all. Present and wrong is a genuine
        demonstration; absent is not.
    """
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
        if ok:
            return PASS, f"found={found} missing={missing}"
        return ABSENCE_RED, (
            f"found={found} missing={missing} — a files_exist clause has no "
            f"predicate but resolution, so this FAIL means the path is not "
            f"there and nothing more")
    if clause.kind == F.K_JSON_FIELD:
        ok, out = FCC._check_json_field_true(
            project, {"file": clause.json_file, "field": clause.json_field,
                      "expect": clause.json_expect})
        if ok:
            return PASS, str(out)[-400:]
        if _nonexec_artefact_present(project, clause.json_file):
            return RED, str(out)[-400:]
        return ABSENCE_RED, (
            f"{str(out)[-300:]} — {clause.json_file} does not resolve at all, "
            f"so this FAIL is the artefact's absence and not its content")
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
    kinds: Dict[str, str] = {}
    for idx, clause in enumerate(blocking):
        sig = _clause_signature(clause)
        fixture = CLAUSE_FIXTURE.get((key, sig), "EMPTY")
        project = _build_project(tmp_path, f"c{idx}", fixture)
        tier, detail = _evaluate_clause(clause, project)
        outcomes[sig] = (tier, fixture, detail)
        kinds[sig] = clause.kind

    reds = {s for s, (t, _, _) in outcomes.items() if t in DEMONSTRATIONS}
    absence_only = {s for s, (t, _, _) in outcomes.items() if t == ABSENCE_RED}

    # ── (1) the gate as a whole must be able to FAIL **on content**.
    #        A red graded ABSENCE_RED does not count: it says the project was
    #        empty, which every gate in the flow would say. Six steps used to
    #        be carried entirely by such a red; three of them still are and
    #        are WAIVED in matrix_63x8/waivers.py, so this assertion is what
    #        their strict xfail is satisfied by — and what turns the suite red
    #        the day one of them gains a clause that can judge content.
    assert reds, (
        f"step {key} gate CANNOT FAIL on anything a project DID: all "
        f"{len(blocking)} blocking clause(s) reached a non-FAIL tier on a "
        f"deliberately-broken project"
        + (f", and the {len(absence_only)} red(s) it does reach are "
           f"{ABSENCE_RED} — earned by the artefact being absent, which is "
           f"not an answer to 'can this gate fail?'" if absence_only else "")
        + " — "
        + "; ".join(
            f"{s[:70]!r} -> {t} (fixture {fx}) :: "
            f"{d[:120].replace(chr(10), ' ')}"
            for s, (t, fx, d) in outcomes.items()))

    # ── (2) every blocking clause must be individually falsifiable, except
    #        the ones the UNREDDENED register admits to and the ones that
    #        have no content predicate to reach.
    #
    #        `files_exist` is EXCLUDED, not excused. UNREDDENED means "this
    #        file could not break it"; for a clause whose whole predicate is
    #        `len(missing) == 0` the truth is stronger and different — there
    #        is no other branch for a fixture to aim at — so registering 32 of
    #        them would misdescribe the fact and bury the 5 real gaps that
    #        register exists to publish. The exclusion is held live by
    #        test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file.
    #        `json_field_true` gets NO exclusion: it compares a value, so it
    #        must reach a content red or be registered like any program.
    registered = {s for (st, s) in UNREDDENED if st == key}
    excluded = {s for s in absence_only if kinds[s] == F.K_FILES}
    unproven = sorted(
        s for s, (t, _, _) in outcomes.items()
        if t not in DEMONSTRATIONS and s not in registered and s not in excluded)
    assert not unproven, (
        f"step {key}: {len(unproven)} blocking clause(s) reached no "
        f"content-earned FAIL and are not in UNREDDENED — either build a "
        f"fixture that reddens them or register the gap with the tier "
        f"measured: "
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


#: The two clauses this branch wired into a BLOCKING slot, with the fixture
#: that reddens each. Kept beside the controls below so a fixture that stops
#: reddening for the RIGHT reason is caught here as well as in the matrix.
_WIRED_BLOCKING = (
    ("17", "pnr_timing_repair_completeness_check phase3/stage3/pnr --json "
           "reports/phase3/pnr/timing_repair_completeness.json",
     "PNR_TCL_HOLD_ONLY"),
    ("23", "hold_corner_coverage_check . --json "
           "reports/phase3/sta/hold_corner_coverage.json",
     "HOLD_CORNER_CONTRADICTED"),
)


def _tier(project: Path, command: str) -> Tuple[str, str]:
    """The matrix's own consumer, so a control cannot pass by a softer path."""
    _prepare_report_dirs(project, command)
    passed, out = FCC._check_program_exit_zero(project, command)
    return _classify(passed, out), out


def test_d2_the_two_newly_wired_blocking_clauses_redden_and_only_on_content(
        tmp_path, _gate_timeout):
    """The claims written into the two new fixtures' docstrings, RUN.

    A fixture docstring that narrates a measurement nobody re-runs is the
    "baseline that outlives its truth" shape at the granularity of one comment.
    Each arm below is the smallest edit to the SAME tree that flips the verdict,
    so a red that came from the tree's shape — a missing directory, an
    unparseable file, an argument error — cannot be mistaken for the gate's
    verdict.
    """
    for key, command, fixture in _WIRED_BLOCKING:
        red, out_red = _tier(_build_project(tmp_path, f"red{key}", fixture),
                             command)
        assert red == RED, (
            f"step {key}: fixture {fixture} no longer reddens "
            f"{command!r} -> {red} :: {out_red[-300:]}")
        empty, out_empty = _tier(_build_project(tmp_path, f"e{key}", "EMPTY"),
                                 command)
        assert empty != RED, (
            f"step {key}: EMPTY now reddens {command!r}, so the dedicated "
            f"fixture is measuring nothing the bare tree does not :: "
            f"{out_empty[-300:]}")

    # ── step 17, negative control: same tree, complete repair chain ──────
    p17 = _build_project(tmp_path, "ctl17", "PNR_TCL_HOLD_ONLY")
    (p17 / "phase3/stage3/pnr/pnr.tcl").write_text(
        "read_lef merged.lef\nread_def floorplan.def\nglobal_placement\n"
        "set_wire_rc -layer met3\nestimate_parasitics -placement\n"
        "repair_design\nrepair_timing -setup\nrepair_timing -hold\n"
        "detailed_placement\nwrite_def placed.def\n", encoding="utf-8")
    tier, out = _tier(p17, _WIRED_BLOCKING[0][1])
    assert tier == PASS, (
        "the complete setup-repair chain must PASS on the identical tree, "
        f"else the red above is the tree and not the script :: {out[-300:]}")

    # ── step 23, control A: the stance ALONE — the input the pre-repair
    #    project mode judged, still reachable as the shipped --stance mode.
    p23 = _build_project(tmp_path, "ctl23a", "HOLD_CORNER_CONTRADICTED")
    tier, out = _tier(
        p23, "hold_corner_coverage_check --stance "
             "reports/phase3/mcorner_ocv_stance.json")
    assert tier == PASS, (
        "the declared stance of this fixture must read PASS on its own — that "
        "is what makes the tree a false PASS before the worst-of repair, and "
        f"what the matrix red proves the repair now catches :: {out[-300:]}")

    # ── step 23, control B: same stance, script rewritten to AGREE ───────
    p23b = _build_project(tmp_path, "ctl23b", "HOLD_CORNER_CONTRADICTED")
    (p23b / "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl").write_text(
        "# === HOLD corner: process=FF "
        "liberty=/pdk/lib/stdcells__ff_n40C_1v95.lib ===\n"
        "read_liberty /pdk/lib/stdcells__ff_n40C_1v95.lib\n"
        "read_verilog top_pnr.v\nlink_design top\n"
        "report_checks -path_delay min -digits 4\n", encoding="utf-8")
    tier, out = _tier(p23b, _WIRED_BLOCKING[1][1])
    assert tier == PASS, (
        "agreeing evidence must not be reddened: worst-of is worst-of the "
        f"verdicts REACHED, not a second way to fail :: {out[-300:]}")


#: The three step-37.5 clauses that had no fixture, with the one that reddens
#: each. Kept beside the control below for the same reason as the pairs above,
#: and for one more specific to these three: two of them are graded over trees
#: this module does not otherwise build (a documented IP release, a documented
#: die) and the third is graded over a PLANTED PLUGIN, so "the fixture stopped
#: reddening" and "the fixture stopped building" look identical in the matrix
#: cell and are told apart here.
_RELEASE_BLOCKING: Tuple[Tuple[str, str, str], ...] = (
    ("37.5ip", "release_docs_check . --arm ip --json "
               "reports/phase3/release_docs.json", "IP_RELEASE_PIN_COUNT_LIE"),
    ("37.5ic", "release_docs_check . --arm ic --json "
               "reports/phase3/release_docs_ic.json", "IC_RELEASE_PIN_COUNT_LIE"),
    ("37.5ic", "closed_loop_executed_reentry_census . --json "
               "reports/phase3/closed_loop_executed_reentry.json",
     "REENTRY_LOOP_INERT"),
)

#: The datasheet each release arm's mutation is planted in.
_RELEASE_DATASHEET = {
    "IP_RELEASE_PIN_COUNT_LIE": "IP_DATASHEET.md",
    "IC_RELEASE_PIN_COUNT_LIE": "PRELIMINARY_DATASHEET.md",
}


def _datasheet_in(project: Path, name: str) -> Path:
    """The SUBJECT release's datasheet, found by walking the tree the fixture
    built rather than by re-deriving the kits' package names here.

    A second copy of "which package is the subject" would be a second answer to
    it the day either kit renames one.
    """
    hits = sorted(project.glob(f"phase3/stage4/documentation/*/*/{name}"))
    assert hits, f"{name} is nowhere under {project} — the fixture built nothing"
    return hits[0]


def _census_verdicts(project: Path):
    """The per-site verdicts the census WROTE, not the tail of what it printed.

    The clause declares ``--json reports/phase3/closed_loop_executed_reentry.
    json``, so the report is the gate's own record of what it graded. The
    consumer returns a 400-character tail of stdout and the counts line does not
    fit inside it, so a control asserted on the snippet would silently stop
    asserting the day the gate prints one more sentence.
    """
    report = project / "reports/phase3/closed_loop_executed_reentry.json"
    assert report.is_file(), f"the census wrote no report under {project}"
    return [s["verdict"]
            for s in json.loads(report.read_text(encoding="utf-8"))["sites"]]


def test_d2_the_three_step_37_5_clauses_redden_and_only_on_content(
        tmp_path, _gate_timeout):
    """The claims in the three step-37.5 fixture docstrings, RUN.

    Each arm is the SMALLEST edit to the SAME tree that flips the verdict, so a
    red earned by the tree's shape — no kit, no plugin directory, an
    unparseable file — cannot be mistaken for the gate's verdict on content.
    """
    for i, (key, command, fixture) in enumerate(_RELEASE_BLOCKING):
        red, out_red = _tier(_build_project(tmp_path, f"r{i}", fixture), command)
        assert red == RED, (
            f"step {key}: fixture {fixture} no longer reddens {command!r} -> "
            f"{red} :: {out_red[-300:]}")
        empty, out_empty = _tier(_build_project(tmp_path, f"e{i}", "EMPTY"),
                                 command)
        assert empty != RED, (
            f"step {key}: EMPTY now reddens {command!r}, so the dedicated "
            f"fixture is measuring nothing the bare tree does not :: "
            f"{out_empty[-300:]}")
        if fixture == "REENTRY_LOOP_INERT":
            # WHICH tree the census graded, from its own report. On EMPTY it
            # falls back to THIS repository and answers rc 0 about a population
            # the fixture never wrote; the planted plugin must have replaced
            # that population entirely, or the red above is this repo's.
            assert _census_verdicts(tmp_path / f"r{i}") == ["INERT"], (
                f"the planted runner is not the population the census graded: "
                f"{_census_verdicts(tmp_path / f'r{i}')}")
            assert len(_census_verdicts(tmp_path / f"e{i}")) > 1, (
                "EMPTY no longer censuses the shipped plugin, so the fallback "
                "this fixture exists to work around is gone and the fixture "
                "must be re-decided")

    # ── the two release arms, negative control: the SAME generated release
    #    with the one edited row put back. Nothing else is touched, so a PASS
    #    here is the pin-count disagreement and not the document set.
    for i, (key, command, fixture) in enumerate(_RELEASE_BLOCKING[:2]):
        project = _build_project(tmp_path, f"c{i}", fixture)
        _restate_signal_pins(
            _datasheet_in(project, _RELEASE_DATASHEET[fixture]), 7, 3)
        tier, out = _tier(project, command)
        assert tier == PASS, (
            f"step {key}: the repaired release must PASS on the identical "
            f"tree, else the red above is the fixture and not the stated pin "
            f"count -> {tier} :: {out[-300:]}")

    # ── the census, negative control: the SAME planted plugin, the SAME single
    #    re-entry site, with the varying argument and the read-back put back.
    #    Graded ACTUATING, so the red above is the LOOP'S SHAPE and not the
    #    fixture having planted a plugin directory at all — which is the one
    #    alternative explanation this clause admits.
    census = _build_project(tmp_path, "cc", "REENTRY_LOOP_INERT")
    (census / "vibe-ic-marketplace/plugins/vibe-ic/programs"
            / "probe_one_shot_runner.py").write_text(
        "def step_probe(ctx, n):\n"
        "    r = step_probe(ctx, n - 1)\n"
        "    if r:\n"
        "        return r\n"
        "    return 0\n", encoding="utf-8")
    tier, out = _tier(census, _RELEASE_BLOCKING[2][1])
    assert tier == PASS, (
        "a re-entry that varies its argument and branches on what came back is "
        f"ACTUATING; reddening it would make the census unusable :: {out[-300:]}")
    # Read off the census's OWN report rather than its stdout: the consumer
    # hands this module a 400-character tail, and the counts line is not in it.
    # A control asserted on a truncated snippet is a control that stops being
    # asserted the day the gate prints one more sentence.
    assert _census_verdicts(census) == ["ACTUATING"], (
        f"the control loop was not graded ACTUATING, so this control is not "
        f"the one the docstring claims :: {_census_verdicts(census)}")


#: The two obstruction gates, with the fixture that reddens each. Kept beside
#: the control below so a fixture that stops reddening for the RIGHT reason —
#: the gate got stricter, the grammar moved — is caught here, named, as well
#: as in the matrix cell.
_OBSTRUCTION_BLOCKING: Tuple[Tuple[str, str, str], ...] = (
    ("15", "macro_obs_load_parity_check . --json "
           "reports/phase3/pnr/macro_obs_load_parity.json",
     "MACRO_OBS_LAYER_UNDECLARED"),
    ("21", "macro_obs_geometry_intersect_check . --json "
           "reports/phase3/pnr/macro_obs_geometry.json",
     "MACRO_OBS_SPANNED"),
)


def test_d2_the_two_obstruction_gates_redden_and_only_on_content(
        tmp_path, _gate_timeout):
    """The claims in the two obstruction fixtures' docstrings, RUN.

    THE DISTINCTION THIS DEFENDS. Before the fixtures, both clauses reached
    ``VACUOUS_PASS`` on ``EMPTY`` and the matrix could not tell that apart
    from a gate with no failing branch at all. The two are opposite facts: one
    is a gate saying "I was given nothing to read", the other is a gate that
    can never say no. Three arms per gate keep them apart —

      EMPTY     -> VACUOUS_PASS  the gate DISCLOSES that it could not measure
      fixture   -> FAIL          the same gate, given its subject, refuses
      corrected -> PASS          the same tree, one property flipped

    — and the third is what makes the second a verdict rather than a shape:
    each control is the smallest edit to the SAME tree that flips the answer,
    so a red earned by a missing directory, an unparseable file or an argument
    error could not have produced it.

    The EMPTY arm is asserted as ``VACUOUS_PASS`` and not merely "not FAIL":
    that tier IS the wiring change's stated justification for landing two
    unconditional legs — a cell that stages no LEF records an honest
    could-not-measure rather than a green — so it is checked rather than
    narrated.
    """
    for key, command, fixture in _OBSTRUCTION_BLOCKING:
        assert CLAUSE_FIXTURE.get((key, command)) == fixture, (
            f"step {key}: {command!r} is no longer assigned {fixture!r}; this "
            f"control and the matrix cell would measure different things")
        tier, out = _tier(_build_project(tmp_path, f"obs{key}", fixture),
                          command)
        assert tier == RED, (
            f"step {key}: fixture {fixture} no longer reddens {command!r} -> "
            f"{tier} :: {out[-300:]}")
        tier, out = _tier(_build_project(tmp_path, f"obse{key}", "EMPTY"),
                          command)
        assert tier == VACUOUS, (
            f"step {key}: on a tree with nothing to read {command!r} answered "
            f"{tier}, not {VACUOUS}. If it is FAIL the fixture is measuring "
            f"nothing the bare tree does not; if it is PASS the gate now "
            f"certifies a run it could not read :: {out[-300:]}")

    # ── step 15, negative control: the SAME abstract, byte for byte, with the
    #    tech LEF declaring the layer its OBS opens on. Nothing else moves.
    p15 = _build_project(tmp_path, "obsctl15", "EMPTY")
    _write_macro_obs_lefs(p15, declared=True)
    assert ((p15 / "input/pdk/block_a.lef").read_text()
            == _abstract_lef()), "the control must not alter the abstract"
    tier, out = _tier(p15, _OBSTRUCTION_BLOCKING[0][1])
    assert tier == PASS, (
        "declaring the referenced layer must PASS on the identical abstract, "
        f"else the red above is the tree and not the parity :: {out[-300:]}")

    # ── step 21, negative control: the same macro, same orientation, same ten
    #    supply segments — only their ordinate moves clear of the footprint.
    p21 = _build_project(tmp_path, "obsctl21", "EMPTY")
    _write_macro_obs_layout(p21, spanning=0)
    assert ((p21 / "input/pdk/big_ip.lef").read_text()
            == _OBSTRUCTED_MACRO_LEF), "the control must not alter the OBS"
    tier, out = _tier(p21, _OBSTRUCTION_BLOCKING[1][1])
    assert tier == PASS, (
        "the same segment count routed clear of the obstruction must PASS, "
        f"else the red above is the macro's presence and not the crossing :: "
        f"{out[-300:]}")


# ─────────────────────────────────────────────────────────────────────
# The empty-directory red — the controls, both directions
# ─────────────────────────────────────────────────────────────────────
#: The step whose `files_exist` clause is the worked counter-example in the
#: module docstring. Pinned so the control quotes a real cell rather than
#: whichever clause happens to be first; if step 21's gate stops carrying
#: exactly one `files_exist` clause, the control says so instead of drifting
#: onto a different subject.
_ABSENCE_COUNTEREXAMPLE_STEP = "21"

#: The glob metacharacters this module's materialiser understands. The live
#: flow uses only `*` (and the consumer's own " OR " alternation); a pattern
#: with `?` or a character class would be materialised WRONG — silently
#: producing a file the clause does not match — so the sweep refuses it out
#: loud rather than reporting a PASS it did not measure.
_SUPPORTED_GLOB_CHARS = "*"


def _materialise_files_exist(project: Path, clause) -> list:
    """Satisfy every pattern of a ``files_exist`` clause with a ZERO-BYTE file.

    The emptiest artefact that can exist. Whatever a gate could want to say
    about content, it cannot say it about nothing — so a clause that PASSES
    against this has no content predicate, and its FAIL can only ever have
    meant "the path is not there".

    Returns the paths written, so a caller can show what was handed over.
    """
    written = []
    for pat in clause.files:
        # The consumer splits alternation on the literal " OR " (:2230-2231);
        # satisfying the first alternative satisfies the entry.
        first = pat.split(F.ANY_OF_SEP)[0].strip()
        bad = [ch for ch in "?[" if ch in first]
        assert not bad, (
            f"pattern {first!r} uses glob metacharacter(s) {bad} that this "
            f"materialiser does not model; it understands "
            f"{_SUPPORTED_GLOB_CHARS!r} only, so it cannot state what it "
            f"handed the clause")
        target = project / first.replace("*", "d2probe")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
        written.append(str(target.relative_to(project)))
    return written


def test_d2_an_absent_artefact_is_not_falsifiability_evidence(tmp_path):
    """The red that proved nothing, run in both directions.

    FORWARD — against the pre-repair file this assertion FAILS: the same
    clause, the same empty tree, came back ``FAIL``, was counted among the
    129 reds, and was the whole of step 21's neighbours' cells. 33 of 129
    reds were this shape.

    REVERSE — the same clause against a project that produced a routed.def
    must still PASS, so the grading below is about what the clause can
    DEMONSTRATE and not a second way to fail it. The stub is 25 bytes,
    ``VERSION 5.8 ;\\nEND DESIGN\\n``: no placement, no routing, no geometry,
    and the clause is satisfied. That contrast is the whole finding.
    """
    clauses = [c for c in F.gate_clauses(_ABSENCE_COUNTEREXAMPLE_STEP)
               if c.is_blocking and c.kind == F.K_FILES]
    assert len(clauses) == 1, (
        f"step {_ABSENCE_COUNTEREXAMPLE_STEP} no longer carries exactly one "
        f"blocking {F.K_FILES} clause ({len(clauses)} found), so this control "
        f"has lost its subject and must be re-pointed, not deleted")
    clause = clauses[0]

    # ── (a) nothing was produced: FAIL, and the FAIL demonstrates nothing.
    tier, detail = _evaluate_clause(
        clause, _build_project(tmp_path, "absent", "EMPTY"))
    assert tier == ABSENCE_RED, (
        f"a {F.K_FILES} clause measured on a tree where nothing exists came "
        f"back {tier!r}. Its whole predicate is `passed = len(missing) == 0` "
        f"(flow_compliance_check.py:2239-2242), so this FAIL says the path is "
        f"absent and says nothing else :: {detail}")
    assert tier not in DEMONSTRATIONS, (
        f"{ABSENCE_RED} is being counted as a demonstration of "
        f"falsifiability, which is the defect this tier exists to name")

    # ── (b) the reverse: a project that produced the file, badly, PASSES.
    produced = _build_project(tmp_path, "stub", "PNR_BAD")
    named = list(clause.files)
    assert len(named) == 1, named
    stub = produced / named[0]
    assert stub.is_file(), (
        f"the PNR_BAD fixture no longer produces {named[0]}, so the reverse "
        f"arm below would pass for the wrong reason")
    assert stub.read_bytes() == b"VERSION 5.8 ;\nEND DESIGN\n", (
        f"the stub this control quotes has changed to "
        f"{stub.read_bytes()!r}; re-measure the docstring before editing it")
    tier2, detail2 = _evaluate_clause(clause, produced)
    assert tier2 == PASS, (
        f"a 25-byte DEF with no geometry must still SATISFY this clause — "
        f"that is the counter-example, and if it stopped being true the "
        f"grading above would be measuring something else :: {tier2} {detail2}")


def test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file():
    """The exclusion in rule (2), MEASURED over every such clause in the flow.

    Rule (2) excludes ``files_exist`` clauses from "must reach a FAIL" on the
    ground that they have no FAIL to reach other than absence. That ground is
    a claim about the consumer, and a claim about the consumer that nobody
    runs is how this dimension got into trouble in the first place — so it is
    not read out of ``flow_compliance_check`` here, it is measured: every
    blocking ``files_exist`` clause in the live flow is handed a ZERO-BYTE
    file for each pattern it names, and every one of them must PASS.

    The day a ``files_exist`` clause grows a content predicate — a size floor,
    a parse — this reddens and the exclusion has to be re-decided rather than
    silently continuing to excuse a clause that could now have been broken.
    """
    subjects = [(F.normalize_id(sid), c)
                for sid in F.step_ids()
                for c in F.gate_clauses(sid)
                if c.is_blocking and c.kind == F.K_FILES]
    assert subjects, (
        "the flow declares no blocking files_exist clause at all — rule (2)'s "
        "exclusion now excuses nothing and should be deleted with this test")

    survivors = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for idx, (key, clause) in enumerate(subjects):
            project = root / f"z{idx}"
            project.mkdir()
            written = _materialise_files_exist(project, clause)
            tier, detail = _evaluate_clause(clause, project)
            if tier != PASS:
                survivors.append(
                    f"step {key} {_clause_signature(clause)[:70]!r} -> {tier} "
                    f"given empty files {written} :: {detail[:160]}")
    assert not survivors, (
        f"{len(survivors)} of {len(subjects)} files_exist clause(s) refused a "
        f"zero-byte artefact, so they DO judge something beyond resolution "
        f"and rule (2) must stop excluding them: " + "; ".join(survivors))


def test_d2_a_present_but_wrong_json_field_is_still_a_real_red(tmp_path):
    """The tightening must not swallow the non-exec clause that DOES judge.

    ``json_field_true`` compares a value (``v == expect``,
    flow_compliance_check.py:7012), so unlike ``files_exist`` it can be
    reddened by a project that produced its artefact and got the answer wrong.
    Three arms on the one clause the flow declares, so "absent" and "present
    and wrong" cannot be collapsed:

      EMPTY            -> ABSENCE_RED   (json file missing)
      field == False   -> FAIL          (the board run says it did not pass)
      field == True    -> PASS          (agreeing evidence is not reddened)

    Without the middle arm this repair would degenerate into "no non-exec
    clause can ever demonstrate anything", which is a tightening that fires
    on everything and distinguishes nothing.
    """
    subjects = [(F.normalize_id(sid), c)
                for sid in F.step_ids()
                for c in F.gate_clauses(sid)
                if c.is_blocking and c.kind == F.K_JSON_FIELD]
    assert subjects, (
        "the flow declares no blocking json_field_true clause, so the "
        "absent-vs-wrong distinction this test defends is unreachable; delete "
        "the branch in _evaluate_clause in the same change that deletes this")
    key, clause = subjects[0]
    assert (key, _clause_signature(clause)) in CLAUSE_FIXTURE, (
        f"step {key}'s json_field_true clause has no fixture and would fall "
        f"back to EMPTY, where its red means only 'no such file'")

    tier, detail = _evaluate_clause(
        clause, _build_project(tmp_path, "j_absent", "EMPTY"))
    assert tier == ABSENCE_RED, f"EMPTY -> {tier} :: {detail}"

    wrong = _build_project(tmp_path, "j_wrong", "ON_BOARD_FAILED")
    tier, detail = _evaluate_clause(clause, wrong)
    assert tier == RED, (
        f"a record that EXISTS and states the run did not pass must be a real "
        f"FAIL — it is a project that did the work and got it wrong, which is "
        f"exactly the input this dimension asks for :: {tier} {detail}")

    # ── reverse: same file, same tree, the field flipped to the expected
    #    value. Nothing else changes, so the red above is the value.
    right = _build_project(tmp_path, "j_right", "ON_BOARD_FAILED")
    payload = json.loads((right / clause.json_file).read_text())
    payload[clause.json_field] = clause.json_expect
    (right / clause.json_file).write_text(json.dumps(payload, indent=1))
    tier, detail = _evaluate_clause(clause, right)
    assert tier == PASS, (
        f"flipping ONLY {clause.json_field!r} to {clause.json_expect!r} must "
        f"PASS, else the red above is the tree and not the field :: "
        f"{tier} {detail}")


#: The three clauses whose fixtures replaced an empty-directory red, each with
#: the tree that must NOT redden. ``corrected`` rewrites the fixture's whole
#: artefact set through the SAME builder with the defect argument flipped, so
#: the control differs from the fixture in the one thing the gate judges — and
#: in a way that stays internally consistent.
#:
#: Correcting one FILE was tried and was wrong. ``perc_signoff_check`` also
#: cross-checks the JSON against the .rpt and the memo
#: (programs/perc_signoff_check.py:78-126), so a control that fixed only the
#: JSON came back FAIL for a different reason — measured, verbatim:
#: ``perc_equivalent.rpt states overall verdict 'FAIL' but
#: perc_equivalent.json states 'PASS' — the signed record contradicts the
#: machine record``. It would have "held" while proving nothing about the ESD
#: arm, which is the degenerate control this campaign exists to remove.
_CONTENT_REPLACEMENTS: Tuple[Tuple[str, str, str, Callable[[Path], None]], ...] = (
    ("6", "quartus_map_audit --project . --json "
          "reports/phase2/gates/quartus_map_audit.json",
     "QUARTUS_STUCK_AT",
     lambda p: _write_quartus_build(p, _MAP_RPT_CLEAN)),
    ("28", "perc_signoff_check . --json "
           "reports/phase2/gates/perc_signoff.json",
     "PERC_ESD_FAIL",
     lambda p: _write_perc_signoff(p, "PASS")),
)


def test_d2_the_three_replaced_empty_reds_are_earned_by_content(
        tmp_path, _gate_timeout):
    """Steps 6, 28 and 30: the red is the artefact's content, not the tree.

    Each of these steps used to be certified falsifiable by one thing — a
    ``files_exist`` clause answering "nothing is there" on the EMPTY fixture —
    while its program clause sat in :data:`UNREDDENED`. Three claims are run
    here for each:

      * the fixture drives the program to a real FAIL;
      * the EMPTY tree does NOT, so the fixture is measuring something the
        bare tree does not (this is what makes the replacement a repair
        rather than a relabelling);
      * for the two that have a one-field negative control, the SAME tree with
        that field corrected reads PASS.

    Step 30 has no such control here: its FAIL arm is the ABSENCE of any SPICE
    run in a tree that reached SPEF and STA, so the input that flips it is a
    whole SPICE result set rather than one edited field. Its EMPTY arm below
    is still the discriminator that matters — rc=2 there, rc=1 here — and the
    fix notes record the arm this suite does not reach.
    """
    for key, command, fixture in (
            ("6", _CONTENT_REPLACEMENTS[0][1], "QUARTUS_STUCK_AT"),
            ("28", _CONTENT_REPLACEMENTS[1][1], "PERC_ESD_FAIL"),
            ("30", "spice_correlation_check . --json "
                   "reports/phase2/gates/spice_correlation.json",
             "POST_LAYOUT_NO_SPICE")):
        assert CLAUSE_FIXTURE.get((key, command)) == fixture, (
            f"step {key}: {command!r} is no longer assigned {fixture!r}; this "
            f"control and the matrix cell would be measuring different things")
        tier, out = _tier(_build_project(tmp_path, f"r{key}", fixture), command)
        assert tier == RED, (
            f"step {key}: fixture {fixture} no longer reddens {command!r} -> "
            f"{tier} :: {out[-300:]}")
        tier, out = _tier(_build_project(tmp_path, f"n{key}", "EMPTY"), command)
        assert tier != RED, (
            f"step {key}: EMPTY now reddens {command!r}, so the dedicated "
            f"fixture is measuring nothing the bare tree does not :: "
            f"{out[-300:]}")

    for key, command, fixture, correct in _CONTENT_REPLACEMENTS:
        project = _build_project(tmp_path, f"ctl{key}", fixture)
        correct(project)
        tier, out = _tier(project, command)
        assert tier == PASS, (
            f"step {key}: the same tree with the defect corrected must PASS, "
            f"else the red above is the tree's shape and not the content the "
            f"gate judges :: {tier} {out[-300:]}")


def test_d2_a_content_earned_program_red_is_still_a_real_red(
        tmp_path, _gate_timeout):
    """Non-degeneracy: the exec clauses this change did not touch still redden.

    A repair that grades reds more strictly can pass its own forward control
    by grading EVERYTHING as no-demonstration. These three are program clauses
    whose fixtures judge content — a 0-byte GDS, a hollow IR report, a
    testbench that prints a pass without driving the DUT — and all three must
    still come back ``FAIL``.
    """
    subjects = (
        ("37", "gds_size_check --gds-file phase3/stage4/gds/*.gds --json "
               "reports/phase3/gds_size.json", "GDS_BAD"),
        ("24", "dynamic_ir_drop_check reports/phase3/dynamic_ir.json "
               "--budget-pct 10", "HOLLOW_REPORTS"),
        ("4", "vacuous_testbench_check . --json "
              "reports/phase2/gates/vacuous_testbench.json", "TB_BAD"),
    )
    for key, command, fixture in subjects:
        assert CLAUSE_FIXTURE.get((key, command)) == fixture, (
            f"step {key}: {command!r} is no longer assigned {fixture!r}")
        tier, out = _tier(_build_project(tmp_path, f"nd{key}", fixture),
                          command)
        assert tier == RED, (
            f"step {key}: {command!r} on {fixture} came back {tier!r}. The "
            f"absence-red repair must not have reclassified content-earned "
            f"program reds :: {out[-300:]}")


#: The cells this repair could NOT close, and the reason, in one place.
#:
#: 2026-08-08: was ``("1", "12", "35")``. Step 12 closed for real — it gained
#: ``dft_post_optimization_scan_survival_check`` as a blocking clause (a
#: genuine content check LEC cannot subsume: scan insertion is functionally
#: transparent, so LEC would still pass a post-DFT netlist whose scan chain
#: silently vanished) — so it left this register and its waiver in
#: ``matrix_63x8/waivers.py`` was removed, not re-worded. Steps 1 and 35 did
#: NOT close: both carry an explicit, owner-confirmed AUDIT NOTE in the flow
#: yaml stating the files_exist-only gate is DELIBERATE (Step 1: content
#: judgement belongs downstream at Steps 2-6 by design; Step 35: promoting
#: the DFM clause to blocking would fabricate unfixable FAILs, since no
#: OpenROAD repair pass exists for what it finds) — their waivers were
#: reworded to say PERMANENT rather than pending, not removed.
#:
#: Each remaining step declares a gate whose every BLOCKING clause is a
#: ``files_exist`` — so by the measurement in
#: :func:`test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file` the
#: whole gate is satisfied by empty files and can fail on one input only, the
#: file not being there. They are WAIVED in ``matrix_63x8/waivers.py`` with
#: ``strict=True``: a stale entry (the step gains a content clause) reddens
#: the suite exactly as it did for step 12.
ABSENCE_ONLY_STEPS: Tuple[str, ...] = ("1", "35")


def test_d2_the_waived_cells_are_gated_by_existence_alone():
    """The honest record and the flow must say the same thing.

    Both directions, because either alone rots:

      * a step in :data:`ABSENCE_ONLY_STEPS` that acquires a blocking clause
        able to judge content is no longer an accepted gap — the entry must go,
        and until it does this test names it (the strict xfail catches the same
        thing from the other side, one full matrix run later);
      * a step whose gate is ALL ``files_exist`` and which is NOT registered
        here is an unpublished absence-only cell — the exact shape that let
        six steps report a green earned by an empty directory.

    The registry side is checked too: every entry must carry a dimension-2
    waiver, or the accepted gap is invisible in the one file that publishes
    accepted gaps.
    """
    all_files_only = set()
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        if key in NA_STEPS or not F.has_gate(sid):
            continue
        blocking = [c for c in F.gate_clauses(sid) if c.is_blocking]
        if blocking and all(c.kind == F.K_FILES for c in blocking):
            all_files_only.add(key)

    registered = set(ABSENCE_ONLY_STEPS)
    assert all_files_only == registered, (
        f"the flow's absence-only gates and this module's register disagree. "
        f"Gated by files_exist alone but unregistered: "
        f"{sorted(all_files_only - registered)}; registered but no longer "
        f"absence-only: {sorted(registered - all_files_only)}")

    unpublished = [k for k in sorted(registered) if W.waiver_for(k, DIM) is None]
    assert not unpublished, (
        f"{unpublished} are recorded here as not-yet-falsified but carry no "
        f"dimension-{DIM} waiver in matrix_63x8/waivers.py, so the accepted "
        f"gap is invisible where accepted gaps are published — and the cell "
        f"would be RUN as if enforced")


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
