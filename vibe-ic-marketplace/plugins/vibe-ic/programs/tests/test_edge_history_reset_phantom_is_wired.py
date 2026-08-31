#!/usr/bin/env python3
"""`edge_history_reset_phantom_check` has to be REACHED, and its verdict READ.

WHAT WENT WRONG
===============
Two hygiene gates named the SAME program on the 2026-08-31 stamp, from two
different populations:

    checker execution wiring   1 checker(s) that NOTHING but their own test runs
    gates are wired to something  1 gate(s) newly consulted by no automatic verdict

`edge_history_reset_phantom_check.py` was authored, tested, and shipped, and
nothing in the tree ever handed it an artefact. Its own docstring says why that
matters more here than elsewhere: the rule was distilled once from a blind CVDP
failure, written up with this exact specification, never shipped as a dispatch —
and the same design then failed again in the next clean-room round by the
identical mechanism, byte for byte.

WHY THE OBVIOUS CONSUMER WAS REFUSED
====================================
The program's docstring names `cvdp_gate._structural_finding_gate` as the
intended consumer. That driver blocks on `severity == "ERROR"` and this checker
emits WARN and only WARN, so wiring it there is PAPER WIRING: the consumer's
verdict is provably invariant under the checker, which is exactly the defect
both hygiene gates exist to catch. `test_advisory_severity_is_still_warn_only`
below pins the premise, so the day someone escalates a finding to ERROR this
file fails and the routing gets re-argued instead of silently changing meaning.

WHERE IT IS WIRED INSTEAD, AND WHY THAT ONE IS ADMISSIBLE
=========================================================
`gate_directed_rtl_repair` is a REPAIR ROUTER, not an emit gate. Its `ESCALATE`
verdict (rc 1) discards nothing and refuses no delivery — it says a defect
stands unrepaired and names who holds the evidence to decide. A signature with a
measured false-fire rate (9 of 302 officially-PASSING deliveries) may reach that
verdict, where it may not reach `cvdp_gate`'s block or `step_determinism_gates`'
FAIL list.

BOTH DIRECTIONS, ALWAYS
=======================
The one property that separates a wiring from a label is that the consumer's
verdict MOVES. Every consumer below is driven over the same module twice, with
ONE token different — `prev <= 1'b0` vs `prev <= sig` in the reset arm:

    router, constant reset arm      -> ESCALATE, rc 1
    router, `prev <= sig`           -> NOT_APPLICABLE, rc 0
    phase-2 dispatch, constant      -> advisory recorded, router_verdict ESCALATE
    phase-2 dispatch, `prev <= sig` -> no advisory at all
    phase-2 dispatch, either arm    -> status unchanged (the advisory may NEVER
                                       move a determinism verdict)

chip-AGNOSTIC: an edge detector, a reset and a clock. No IC, vendor, SKU or
process appears here.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import edge_history_reset_phantom_check as EHR  # noqa: E402
import gate_directed_rtl_repair as GDR  # noqa: E402

_CLASS = "edge-history-reset-to-constant"

# The reset arm assigns a CONSTANT while an edge term over (sig, prev) exists.
RTL_DEFECT = """
module edgedet(input clk, input rst_n, input sig, output wire rise);
  reg prev;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) prev <= 1'b0;
    else        prev <= sig;
  end
  assign rise = sig & ~prev;
endmodule
"""

# The SAME module with the fix the checker's own message names, and nothing
# else. Any verdict difference below is attributable to this one token.
RTL_CLEAN = RTL_DEFECT.replace("prev <= 1'b0;", "prev <= sig;")

SPEC = ("Rising-edge detector. On each clock, sample sig and assert rise for "
        "one cycle when sig goes from 0 to 1.")


def _write_project(tmp_path: Path, rtl: str) -> Path:
    import _path_layout as _pl
    project = tmp_path / "proj"
    rtl_dir = _pl.rtl_dir(project)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "edgedet.v").write_text(rtl)
    return project


# ── the premise the routing rests on ────────────────────────────────────────

def test_advisory_severity_is_still_warn_only():
    """Every finding is WARN. If this ever fails, the `cvdp_gate` refusal above
    stops being true and the whole routing decision must be re-made — which is
    the point of asserting it here rather than trusting the docstring."""
    findings, status = EHR.check_text(RTL_DEFECT)
    assert findings, "the defect fixture must fire the signature"
    assert status == "FAIL"
    assert {f.severity for f in findings} == {"WARN"}


def test_clean_arm_produces_no_finding():
    findings, status = EHR.check_text(RTL_CLEAN)
    assert findings == []
    assert status == "PASS"


# ── consumer 1: the router's VERDICT, both directions ───────────────────────

def test_router_escalates_on_the_defect_and_not_on_the_fix():
    bad = GDR.repair(RTL_DEFECT, SPEC)
    good = GDR.repair(RTL_CLEAN, SPEC)
    assert bad["verdict"] == "ESCALATE", bad
    assert bad["defect"] == _CLASS
    assert good["verdict"] == "NOT_APPLICABLE", good
    assert good.get("defect") is None


def test_router_evidence_names_the_gate_and_the_symbol():
    res = GDR.repair(RTL_DEFECT, SPEC)
    ev = res["evidence"]
    assert ev["gate"] == "edge_history_reset_phantom_check"
    assert ev["finding"]["symbol"] == "prev"
    assert ev["finding"]["rule"] == "EDGE_HISTORY_RESET_TO_CONSTANT"
    # The route has to name what a human is supposed to DO with it.
    assert "stimulus" in res["why_not_bucket_a"].lower()
    assert "prev <= sig" in res["escalate_to"]


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
    """The bar this module already sets for its other non-repairable class."""
    entry = GDR.NOT_REPAIRABLE[_CLASS]
    assert entry["gate"] == "edge_history_reset_phantom_check"
    assert len(entry["why_not_bucket_a"]) >= 120
    assert len(entry["escalate_to"]) >= 60
    # The measured sweep, not an argument from first principles.
    assert "302" in entry["why_not_bucket_a"]


def test_router_does_not_disturb_the_class_that_was_here_first():
    """The divider branch is ordered BEFORE the new one and must still win."""
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


# ── consumer 2: the phase-2 dispatch that consults it ───────────────────────

def test_phase2_dispatch_records_the_routed_verdict(tmp_path):
    import design_one_shot_runner as R
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_DEFECT),
                                   "edgedet")
    adv = (res.extras or {}).get("edge_history_reset_advisory")
    assert adv is not None, res.extras
    assert adv["gate"] == "edge_history_reset_phantom_check"
    assert adv["router_verdict"] == "ESCALATE"
    assert adv["blocking"] is False
    assert [f["symbol"] for f in adv["findings"]] == ["prev"]
    assert "ADVISORY" in res.detail


def test_phase2_dispatch_is_silent_on_the_fixed_arm(tmp_path):
    import design_one_shot_runner as R
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_CLEAN),
                                   "edgedet")
    assert (res.extras or {}).get("edge_history_reset_advisory") is None
    assert "ADVISORY" not in res.detail


def test_the_advisory_can_never_move_the_determinism_verdict(tmp_path):
    """THE NO-LEAK HALF. The four gates in this step are zero-false-positive
    and this signature is not (9 of 302 officially-PASSING deliveries fire).
    A determinism FAIL refuses the phase-2 verdict, so the advisory arm must
    leave the status byte-identical to the arm with no advisory at all."""
    import design_one_shot_runner as R
    bad = R.step_determinism_gates(_write_project(tmp_path / "a", RTL_DEFECT),
                                   "edgedet")
    good = R.step_determinism_gates(_write_project(tmp_path / "b", RTL_CLEAN),
                                    "edgedet")
    assert bad.status == good.status == "PASS"


def test_the_dispatch_reads_the_route_from_its_owner(tmp_path):
    """SINGLE SOURCE. The step must not restate the routing text; deleting the
    register entry has to break the dispatch loudly rather than leave it
    printing a route nobody honours."""
    import design_one_shot_runner as R
    res = R.step_determinism_gates(_write_project(tmp_path, RTL_DEFECT),
                                   "edgedet")
    adv = (res.extras or {}).get("edge_history_reset_advisory")
    entry = GDR.NOT_REPAIRABLE[_CLASS]
    assert adv["why_not_bucket_a"] == entry["why_not_bucket_a"]
    assert adv["escalate_to"] == entry["escalate_to"]


# ── the wiring itself, as the two hygiene gates measure it ──────────────────

@pytest.mark.parametrize("consumer", ["gate_directed_rtl_repair.py",
                                      "design_one_shot_runner.py"])
def test_the_reference_is_an_import_not_a_sentence(consumer):
    """Both hygiene gates strip comments and docstrings before searching, and
    `checker_execution_wiring_audit` additionally decides INVOCATION vs MENTION
    on the raw source. A `# see edge_history_reset_phantom_check` would satisfy
    neither. Assert the reference is a real `import` statement."""
    tree = ast.parse((_PROGRAMS / consumer).read_text())
    imported = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "edge_history_reset_phantom_check" in imported, (
        f"{consumer} must IMPORT the checker; a mention is not a runner")
