#!/usr/bin/env python3
"""`counter_decode_lookahead_phase_check` has to be REACHED, and its verdict READ.

WHAT WENT WRONG
===============
The checker landed in v1.18.3 with its own tests and NOTHING invoked it. A grep
of `flow/`, `benchmark/CAPTURE_ROUTING.json`, `tools/ci/` and every `*_runner.py`
found no caller, and the only two references in the whole tree outside the
program itself were `programs/INDEX.md` (documentation, which
`gate_is_wired_check` excludes on purpose) and its own test file.

The register that exists for exactly this said so, on the shipped tree:

    gates: 655   unwired: 27 (baseline 26)   of those named in a skill: 23
    [FAIL] 1 gate(s) newly consulted by no automatic verdict:
       counter_decode_lookahead_phase_check

A gate nothing invokes produces no verdict and the tree looks identical either
way — and this one was distilled from two designs that failed one clean-room run
for the same structural reason, in two different subsystems. Shipping it unwired
means the next design fails the same way with the checker sitting in the tree.

WHERE IT IS WIRED, AND WHY THAT PLACE AND NOT ANOTHER
=====================================================
`step_determinism_gates` in `design_one_shot_runner` (flow Step 2, the RTL
validation step, site `rtl_validate`) is the step where the subject exists: it is
the one place that already walks every authored RTL file with structural
phase gates. It is wired there as an ADVISORY member, alongside
`edge_history_reset_phantom_check` and by the same argument — but the argument
here is the checker's OWN, not caution about it:

    a lookahead decode is LEGITIMATE when the spec asks for the level to lead
    (a pre-emptive `almost_full`, a one-cycle-early enable)

so the finding may not reach that step's FAIL list, which refuses the phase-2
verdict. It is ROUTED instead, to `gate_directed_rtl_repair`, whose
`counter-decode-lookahead-phase` entry decides ESCALATE — a verdict that
discards nothing and refuses no delivery — and names who holds the spec fact.

BOTH DIRECTIONS, ALWAYS
=======================
Every consumer below is driven over the SAME module twice with ONE token
different, `bin2gray(waddr_bin + wen)` vs `bin2gray(waddr_bin)`:

    router, lookahead decode        -> ESCALATE, rc 1
    router, pre-increment decode    -> NOT_APPLICABLE, rc 0
    phase-2 dispatch, lookahead     -> row verdict FINDING, router ESCALATE
    phase-2 dispatch, pre-increment -> row verdict PASS, router NOT_APPLICABLE
    phase-2 dispatch, no RTL read   -> no row at all
    phase-2 dispatch, either arm    -> status unchanged (the advisory may NEVER
                                       move a determinism verdict)

THE ROW IS WRITTEN EVEN WHEN THE SCAN IS CLEAN, and that is not decoration. The
defect being repaired here is that a shipped checker with no caller left a
published record byte-identical to one where the checker ran and found nothing.
A row that appeared only on a finding would not distinguish those two either, so
the row carries its own verdict and is absent only when no RTL file was read.
This is the rule flow Step 2 already states for its sibling output: "Always
written, including NOT_APPLICABLE, so `no cross-layer search` remains distinct
from `the fidelity check never ran`."

chip-AGNOSTIC: a counter, a clock and a reset. No IC, vendor, SKU or process
appears here.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import counter_decode_lookahead_phase_check as CDL  # noqa: E402
import gate_directed_rtl_repair as GDR  # noqa: E402

_CLASS = "counter-decode-lookahead-phase"

# The gray-coded write pointer is loaded from a LOOKAHEAD of the binary address
# on the very edge that advances that address, so it is published one source
# cycle early relative to the address it encodes.
RTL_DEFECT = """
module fifo_wptr (input wclk, input wrstn, input wen);
  reg [4:0] waddr_bin, wptr;
  function [4:0] bin2gray(input [4:0] b); bin2gray = b ^ (b >> 1); endfunction
  always @(posedge wclk or negedge wrstn) begin
    if (!wrstn) begin
      waddr_bin <= 5'd0;
      wptr      <= 5'd0;
    end else begin
      waddr_bin <= waddr_bin + wen;
      wptr      <= bin2gray(waddr_bin + wen);
    end
  end
endmodule
"""

# The SAME module with the pre-increment decode the checker's own message names,
# and nothing else. Any verdict difference below is attributable to one token.
RTL_CLEAN = RTL_DEFECT.replace("bin2gray(waddr_bin + wen)", "bin2gray(waddr_bin)")

SPEC = ("Asynchronous FIFO write-pointer block. Maintain a binary write address "
        "and its gray-coded form; the gray pointer names the address the FIFO "
        "has actually written.")


def _write_project(tmp_path: Path, rtl: str) -> Path:
    import _path_layout as _pl
    project = tmp_path / "proj"
    rtl_dir = _pl.rtl_dir(project)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "fifo_wptr.v").write_text(rtl)
    return project


# ── the premise the routing rests on ────────────────────────────────────────

def test_the_checker_fires_on_the_lookahead_and_not_on_the_fix():
    """If this ever stops discriminating, every claim below is vacuous."""
    bad = CDL.scan(RTL_DEFECT)
    assert [f["signal"] for f in bad] == ["wptr"], bad
    assert bad[0]["counter"] == "waddr_bin"
    assert CDL.scan(RTL_CLEAN) == []


def test_the_checker_is_advisory_by_default():
    """The reason this may not join the step's FAIL list is the checker's own
    default, not a judgement made at the wiring site. Pin it: the day `--strict`
    becomes the default, the routing decision has to be re-argued rather than
    silently changing meaning."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "fifo_wptr.v"
        f.write_text(RTL_DEFECT)
        prog = str(_PROGRAMS / "counter_decode_lookahead_phase_check.py")
        loose = subprocess.run([sys.executable, prog, str(f)],
                               capture_output=True, text=True)
        strict = subprocess.run([sys.executable, prog, str(f), "--strict"],
                                capture_output=True, text=True)
    assert loose.returncode == 0, loose.stdout + loose.stderr
    assert "FINDING" in loose.stdout, loose.stdout
    assert strict.returncode == 1, strict.stdout + strict.stderr


# ── consumer 1: the router's VERDICT, both directions ───────────────────────

def test_router_escalates_on_the_lookahead_and_not_on_the_fix():
    bad = GDR.repair(RTL_DEFECT, SPEC)
    good = GDR.repair(RTL_CLEAN, SPEC)
    assert bad["verdict"] == "ESCALATE", bad
    assert bad["defect"] == _CLASS
    assert good["verdict"] == "NOT_APPLICABLE", good
    assert good.get("defect") is None


def test_router_evidence_names_the_gate_and_the_signal():
    res = GDR.repair(RTL_DEFECT, SPEC)
    ev = res["evidence"]
    assert ev["gate"] == "counter_decode_lookahead_phase_check"
    assert ev["finding"]["signal"] == "wptr"
    assert ev["finding"]["counter"] == "waddr_bin"
    # The route has to name what a human is supposed to DO with it.
    assert "spec" in res["why_not_bucket_a"].lower()
    assert "PRE-increment" in res["escalate_to"]


def test_router_exit_status_moves_on_the_checker_alone(tmp_path):
    """The rc a caller reads, not just the dict — driven through the CLI."""
    spec = tmp_path / "spec.txt"
    spec.write_text(SPEC)
    rcs = {}
    for label, rtl in (("defect", RTL_DEFECT), ("clean", RTL_CLEAN)):
        p = tmp_path / f"{label}.v"
        p.write_text(rtl)
        rcs[label] = subprocess.run(
            [sys.executable, str(_PROGRAMS / "gate_directed_rtl_repair.py"),
             "--rtl", str(p), "--spec", str(spec)],
            capture_output=True, text=True).returncode
    assert rcs == {"defect": 1, "clean": 0}, rcs


def test_the_registered_reason_is_a_measurement_not_a_gesture():
    """The bar this module already sets for its other non-repairable classes."""
    entry = GDR.NOT_REPAIRABLE[_CLASS]
    assert entry["gate"] == "counter_decode_lookahead_phase_check"
    assert len(entry["why_not_bucket_a"]) >= 120
    assert len(entry["escalate_to"]) >= 60
    # It names the oracles it measured as blind, not a general worry.
    assert "clock_divider_ratio_oracle_check" in entry["why_not_bucket_a"]


def test_router_does_not_disturb_the_classes_that_were_here_first(tmp_path):
    """This branch is ordered LAST. A design that trips an older signature keeps
    the routing it already had."""
    divider = """
module freqdiv(input clk, input rst_n, output clk_div);
  reg [2:0] cnt1, cnt2; reg clk_div1, clk_div2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt1<=0; clk_div1<=1'b0; end
    else begin
      if(cnt1==4) cnt1<=0; else cnt1<=cnt1+1;
      if(cnt1==2 || cnt1==4) clk_div1 <= ~clk_div1;
    end
  always @(negedge clk or negedge rst_n)
    if(!rst_n) begin cnt2<=0; clk_div2<=1'b0; end
    else begin
      if(cnt2==4) cnt2<=0; else cnt2<=cnt2+1;
      if(cnt2==2 || cnt2==4) clk_div2 <= ~clk_div2;
    end
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""
    res = GDR.repair(divider, "Divide the input clock by five.")
    assert res["defect"] == "clock-divider-phase-form", res

    edge_history = """
module edgedet(input clk, input rst_n, input sig, output wire rise);
  reg prev;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) prev <= 1'b0;
    else        prev <= sig;
  end
  assign rise = sig & ~prev;
endmodule
"""
    res2 = GDR.repair(edge_history, "Rising-edge detector.")
    assert res2["defect"] == "edge-history-reset-to-constant", res2


# ── consumer 2: the phase-2 dispatch that consults it ───────────────────────

def test_phase2_dispatch_records_the_routed_verdict(tmp_path):
    import design_one_shot_runner as R
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_DEFECT),
                                   "fifo_wptr")
    adv = (res.extras or {}).get("counter_decode_lookahead_advisory")
    assert adv is not None, res.extras
    assert adv["gate"] == "counter_decode_lookahead_phase_check"
    assert adv["verdict"] == "FINDING"
    assert adv["router_verdict"] == "ESCALATE"
    assert adv["blocking"] is False
    assert adv["files_scanned"] == 1
    assert [f["signal"] for f in adv["findings"]] == ["wptr"]
    assert [f["file"] for f in adv["findings"]] == ["fifo_wptr.v"]
    assert "ADVISORY" in res.detail


def test_the_row_is_written_on_the_clean_arm_too(tmp_path):
    """RAN-AND-FOUND-NOTHING IS NOT NEVER-CONSULTED, and telling those two
    apart is the whole finding this wiring repairs. The row appears on every
    run that had RTL to read; only its verdict moves. The step's DETAIL stays
    silent, because a clean scan is not an advisory to a human."""
    import design_one_shot_runner as R
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_CLEAN),
                                   "fifo_wptr")
    adv = (res.extras or {}).get("counter_decode_lookahead_advisory")
    assert adv is not None, res.extras
    assert adv["verdict"] == "PASS"
    assert adv["router_verdict"] == "NOT_APPLICABLE"
    assert adv["findings"] == []
    assert adv["files_scanned"] == 1
    assert "counter lookahead" not in res.detail


def test_the_row_counts_the_checker_s_own_reads_not_the_loop_s(monkeypatch, tmp_path):
    """THE ARM THAT CAUGHT THE FIRST VERSION OF THIS ROW.

    The row was keyed on the step's own file counter, so with the invocation
    DELETED the published record still read `files_scanned: 1, verdict: PASS` —
    "the checker looked and found nothing" over a checker that had not run. That
    is byte-for-byte the false record the unwired gate produced, reintroduced by
    the repair for it. MEASURED on a real project before it was keyed to the
    checker's own call site instead.

    Here the deletion is simulated by making the checker unreachable: `scan`
    raises, the call site's `except` swallows it exactly as it does for any
    other checker fault, and the row must be GONE rather than green."""
    import design_one_shot_runner as R

    def _explode(_src):
        raise RuntimeError("the checker did not run")

    monkeypatch.setattr(CDL, "scan", _explode)
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_DEFECT),
                                   "fifo_wptr")
    assert res.status == "PASS", res           # a checker fault may not block
    assert (res.extras or {}).get("counter_decode_lookahead_advisory") is None, (
        "the row survived the checker not running — it is counting the loop, "
        "not the checker")


def test_the_row_is_absent_only_when_nothing_was_scanned(tmp_path):
    """The one state that must NOT produce a row: the step never read an RTL
    file, so the checker has said nothing about anything. Without this arm the
    claim above ('the row is always there') could be satisfied by a row that is
    written unconditionally, including over a scan that never happened."""
    import design_one_shot_runner as R
    import _path_layout as _pl
    empty = tmp_path / "empty"
    _pl.rtl_dir(empty).mkdir(parents=True, exist_ok=True)
    res = R.step_determinism_gates(empty, "fifo_wptr")
    assert res.status == "SKIP", res
    assert (res.extras or {}).get("counter_decode_lookahead_advisory") is None


def test_the_advisory_can_never_move_the_determinism_verdict(tmp_path):
    """THE NO-LEAK HALF. The four blocking gates in this step are
    zero-false-positive by construction; this signature is not deciding a
    defect at all — it reports a shape whose correctness lives in the spec. A
    determinism FAIL refuses the phase-2 verdict, so the advisory arm must leave
    the status byte-identical to the arm with no advisory."""
    import design_one_shot_runner as R
    bad = R.step_determinism_gates(_write_project(tmp_path / "a", RTL_DEFECT),
                                   "fifo_wptr")
    good = R.step_determinism_gates(_write_project(tmp_path / "b", RTL_CLEAN),
                                    "fifo_wptr")
    assert bad.status == good.status == "PASS"


def test_the_dispatch_reads_the_route_from_its_owner(tmp_path):
    """SINGLE SOURCE. The step must not restate the routing text; deleting the
    register entry has to break the dispatch loudly rather than leave it
    printing a route nobody honours."""
    import design_one_shot_runner as R
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_DEFECT),
                                   "fifo_wptr")
    adv = (res.extras or {}).get("counter_decode_lookahead_advisory")
    entry = GDR.NOT_REPAIRABLE[_CLASS]
    assert adv["why_not_bucket_a"] == entry["why_not_bucket_a"]
    assert adv["escalate_to"] == entry["escalate_to"]


def test_the_two_advisory_members_do_not_displace_each_other(tmp_path):
    """Both signatures in one file: each keeps its own advisory row. A second
    member that overwrote the first would be a regression nobody would see,
    because the step's status does not move for either."""
    import design_one_shot_runner as R
    both = RTL_DEFECT + """
module edgedet(input clk, input rst_n, input sig, output wire rise);
  reg prev;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) prev <= 1'b0;
    else        prev <= sig;
  end
  assign rise = sig & ~prev;
endmodule
"""
    res = R.step_determinism_gates(_write_project(tmp_path, both), "fifo_wptr")
    extras = res.extras or {}
    assert extras.get("edge_history_reset_advisory") is not None, extras
    assert extras.get("counter_decode_lookahead_advisory") is not None, extras
    assert res.status == "PASS"


# ── the wiring itself, as the hygiene gates measure it ──────────────────────

@pytest.mark.parametrize("consumer", ["gate_directed_rtl_repair.py",
                                      "design_one_shot_runner.py"])
def test_the_reference_is_an_import_not_a_sentence(consumer):
    """`gate_is_wired_check` and `checker_execution_wiring_audit` both strip
    comments and docstrings before searching. A `# see counter_decode_...`
    would satisfy neither. Assert the reference is a real `import` statement."""
    tree = ast.parse((_PROGRAMS / consumer).read_text())
    imported = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "counter_decode_lookahead_phase_check" in imported, (
        f"{consumer} must IMPORT the checker; a mention is not a runner")


def test_the_flow_names_it_at_the_step_whose_subject_it_reads():
    """`flow/phase1_phase2_phase3.yaml` is the single source of truth for which
    programs a step runs. Step 2 is RTL validation — the step whose input is the
    authored RTL this checker reads."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(
        (_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step2 = [s for s in doc["steps"] if str(s.get("id")) == "2"]
    assert len(step2) == 1, "flow Step 2 is not uniquely identifiable"
    assert "counter_decode_lookahead_phase_check" in (step2[0].get("programs") or [])


def test_capture_routing_names_it_under_the_step_that_runs_it():
    routing = json.loads(
        (_PROGRAMS.parent / "benchmark" / "CAPTURE_ROUTING.json").read_text())

    def _walk(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from _walk(v)
        elif isinstance(node, list):
            yield from node

    assert "programs/counter_decode_lookahead_phase_check.py" in set(_walk(routing))
