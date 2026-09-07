#!/usr/bin/env python3
"""#2087 — ``no_fsm_in_input`` is a claim about the INPUT, not about the design.

THE DEFECT, measured on a ``processor_cpu`` project (``rtl_gen=null``, so
``design_one_shot_runner.step_rtl_gen`` WAIVES to ``spec-to-rtl`` and the author
writes the RTL):

  Run 1, before the author writes anything — correct, and it says the right
  thing::

      [SKIP] L6 positively declares no FSM in the input and declares no
             reject_rules[] — nothing this gate can hold it to

  Run 2, same L6, same input, the only change being the RTL the runner asked
  for::

      [FAIL] BLOCKING EXTRACTION_APPLICABILITY_CONTRADICTION:
             L6_CONTROL_LOGIC.json:no-FSM=true vs <authored>.v:FSM-next=3

The field's name is the contract. ``no_fsm_in_input`` says the INPUT DOCUMENTS
carry no FSM; an input-level claim can only be contradicted by input-level
evidence. RTL the FLOW authored is not evidence about the input — for these
classes the input deliberately leaves the control structure free, so an authored
FSM is the CONFORMING outcome.

WHAT MUST NOT MOVE, and is asserted here in the same file so the two halves
cannot drift apart: #1977's finding. When the RTL under ``phase2/stage1/rtl``
came FROM the input — a reused-IP design, keystone
``SOURCE_MANIFEST.json{reused_ip:true}``, or RTL staged in
``input/vendor_rtl/`` — a no-FSM declaration over it is still a BLOCKING
contradiction at rc 1. The discriminator is the tree's PROVENANCE and nothing
else, read through the one shared predicate (``_reused_ip_predicate``).

Synthesized neutral data throughout: no benchmark name, no chip name, no vendor
literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "l6_fsm_scaffold_actionable_check.py"

#: An FSM the flow AUTHORS: an integer state register with real movement.
#: Verilog-2001 shape, which is what ``spec-to-rtl`` writes for these classes.
AUTHORED_FSM = """\
module core_ctrl (input wire clk, input wire rst_n, output reg done);
  reg [2:0] state;
  always @(posedge clk) begin
    if (!rst_n) state <= 3'd0;
    else case (state)
      3'd0: state <= 3'd1;
      3'd1: state <= 3'd2;
      3'd2: state <= 3'd0;
      default: state <= 3'd0;
    endcase
  end
  always @(posedge clk) done <= (state == 3'd2);
endmodule
"""

#: L1+L2 that make ``ic_class_profile`` resolve ``processor_cpu`` — the class
#: the issue was measured on. Structural ISA prose only; no core name.
L1_CPU = {
    "ic_name": "synth_core",
    "description": ("A 32-bit RV32I soft-core processor. The instruction set "
                    "is fixed by the input; the program counter and the "
                    "register file are architectural state."),
    "interface": "wishbone",
}
L2_CPU = {"architecture": ("bit-serial datapath; instruction fetch over the "
                           "memory bus. The micro-architecture, including any "
                           "control structure, is left to the implementer.")}

#: L6 as the producer honestly writes it for such an input.
L6_SILENT_INPUT = {
    "fsm_states": [], "fsm_machines": [], "fsm_states_source": [],
    "no_fsm_in_input": True, "no_fsm_states_in_input": True,
}


def _run(project: Path, json_out: Path | None = None):
    argv = [sys.executable, str(PROG), str(project)]
    if json_out is not None:
        argv.extend(["--json", str(json_out)])
    return subprocess.run(argv, capture_output=True, text=True)


def _cpu_project(tmp_path: Path, name: str, l6: dict | None = None) -> Path:
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(L1_CPU), encoding="utf-8")
    (gd / "L2_ARCHITECTURE.json").write_text(json.dumps(L2_CPU),
                                             encoding="utf-8")
    (gd / "L6_CONTROL_LOGIC.json").write_text(
        json.dumps(L6_SILENT_INPUT if l6 is None else l6), encoding="utf-8")
    return proj


def _author_rtl(project: Path, filename: str = "core_ctrl.v") -> Path:
    """Write RTL the way the FLOW does: into phase2, with no staging record."""
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    path = rtl / filename
    path.write_text(AUTHORED_FSM, encoding="utf-8")
    return path


def _stage_rtl_from_input(project: Path,
                          filename: str = "core_ctrl.v") -> Path:
    """Write RTL the way a REUSED-IP design does: it arrives in the input."""
    vdir = project / "input" / "vendor_rtl"
    vdir.mkdir(parents=True, exist_ok=True)
    path = vdir / filename
    path.write_text(AUTHORED_FSM, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# THE DEFECT — the two runs of the issue, in one test.
# ---------------------------------------------------------------------------

def test_the_two_runs_of_the_issue_give_the_same_verdict_class(tmp_path):
    """Authoring the RTL the runner asked for must not change the verdict.

    This is the whole issue: run 1 and run 2 differ ONLY in whether the author
    has written the RTL yet. Before #2087 run 1 was rc 2 SKIP and run 2 was
    rc 1 BLOCKING."""
    before = _cpu_project(tmp_path, "before")
    r1 = _run(before)

    after = _cpu_project(tmp_path, "after")
    _author_rtl(after)
    r2 = _run(after)

    assert r1.returncode == 2, r1.stdout + r1.stderr
    assert r2.returncode == r1.returncode, r2.stdout + r2.stderr
    assert "[SKIP]" in r1.stdout
    assert "[SKIP]" in r2.stdout
    assert "nothing this gate can hold it to" in r2.stdout
    assert "EXTRACTION_APPLICABILITY_CONTRADICTION" not in r2.stdout


def test_an_authored_fsm_is_reported_as_an_advisory_not_a_contradiction(
        tmp_path):
    """The observation is kept — it is just not called a contradiction."""
    proj = _cpu_project(tmp_path, "advisory")
    _author_rtl(proj)
    report = tmp_path / "advisory.json"
    r = _run(proj, report)

    assert r.returncode == 2, r.stdout + r.stderr
    assert "AUTHORED_FSM_NO_INPUT_SCAFFOLD" in r.stdout
    assert "[WARN]" in r.stdout
    assert "authored FSM with no input scaffold" in r.stdout

    res = json.loads(report.read_text(encoding="utf-8"))
    assert res["applicability_findings"] == []
    assert res["failures"] == []
    advisory = res["authored_fsm_advisories"][0]
    assert advisory["name"] == "AUTHORED_FSM_NO_INPUT_SCAFFOLD"
    assert advisory["severity"] == "ADVISORY"
    assert advisory["declaration"]["fields"] == {
        "no_fsm_in_input": True, "no_fsm_states_in_input": True}
    evidence = advisory["authored_rtl_evidence"]
    assert [e["provenance"] for e in evidence] == ["authored"]
    assert evidence[0]["rtl_path"] == "phase2/stage1/rtl/core_ctrl.v"


# ---------------------------------------------------------------------------
# #1977 MUST NOT MOVE — the SAME RTL, arriving from the INPUT, still blocks.
# This pair is the negative control: only the provenance differs.
# ---------------------------------------------------------------------------

def test_the_same_fsm_staged_from_the_input_still_blocks(tmp_path):
    """Byte-identical RTL, staged in input/vendor_rtl instead of authored."""
    proj = _cpu_project(tmp_path, "staged")
    _stage_rtl_from_input(proj)
    report = tmp_path / "staged.json"
    r = _run(proj, report)

    assert r.returncode == 1, r.stdout + r.stderr
    assert "BLOCKING EXTRACTION_APPLICABILITY_CONTRADICTION" in r.stdout
    assert "input/vendor_rtl/core_ctrl.v" in r.stdout
    finding = json.loads(report.read_text(
        encoding="utf-8"))["applicability_findings"][0]
    assert finding["severity"] == "BLOCKING"
    assert [e["provenance"]
            for e in finding["staged_rtl_evidence"]] == ["input"]


def test_a_reused_ip_manifest_makes_the_phase2_tree_input_side(tmp_path):
    """The other real staging path: the tree is populated FROM the input and
    the keystone manifest records it. Same file, same place as the authored
    case — only the manifest differs, and it flips the verdict back to red."""
    proj = _cpu_project(tmp_path, "consumed")
    _author_rtl(proj)                       # same bytes, same path
    (proj / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"reused_ip": True}), encoding="utf-8")
    r = _run(proj)

    assert r.returncode == 1, r.stdout + r.stderr
    assert "BLOCKING EXTRACTION_APPLICABILITY_CONTRADICTION" in r.stdout
    assert "phase2/stage1/rtl/core_ctrl.v" in r.stdout


def test_a_design_that_stages_rtl_keeps_its_whole_phase2_tree_input_side(
        tmp_path):
    """THE COARSENESS, ASSERTED SO IT IS A DECISION AND NOT AN ACCIDENT.

    Provenance is answered PER TREE, not per file, because on the catalog-pull
    staging path the input-side files are copied straight into
    ``phase2/stage1/rtl`` and never appear under ``input/vendor_rtl`` at all —
    there is no per-file record to read. So once a design has staged ANY reused
    RTL, every FSM in its phase-2 tree stays input-side and stays BLOCKING,
    including the glue the author wrote beside it. That is the fail-closed
    direction: a design that brings its own implementation keeps #1977's
    finding whole. Only a design that stages NOTHING — the ``rtl_gen=null`` +
    ``spec-to-rtl`` shape #2087 is about — gets the advisory."""
    proj = _cpu_project(tmp_path, "both")
    _stage_rtl_from_input(proj, "staged_ctrl.v")
    _author_rtl(proj, "authored_ctrl.v")
    report = tmp_path / "both.json"
    r = _run(proj, report)

    assert r.returncode == 1, r.stdout + r.stderr
    res = json.loads(report.read_text(encoding="utf-8"))
    finding = res["applicability_findings"][0]
    assert [e["rtl_path"] for e in finding["staged_rtl_evidence"]] == [
        "input/vendor_rtl/staged_ctrl.v",
        "phase2/stage1/rtl/authored_ctrl.v"]
    assert {e["provenance"] for e in finding["staged_rtl_evidence"]} == {
        "input"}
    assert res["authored_fsm_advisories"] == []


# ---------------------------------------------------------------------------
# The advisory disarms NOTHING that was a real finding.
# ---------------------------------------------------------------------------

def test_an_unscaffoldable_declared_fsm_still_fails_beside_authored_rtl(
        tmp_path):
    """L6 DOES declare an FSM, and it is not actionable. Authored RTL sitting
    next to it must not turn that into a skip."""
    l6 = {
        "fsm_states": [{"name": "ST_A", "transitions": [{"to": "ST_GHOST"}]},
                       {"name": "ST_B", "transitions": [{"to": "ST_A"}]}],
        "no_fsm_in_input": False, "no_fsm_states_in_input": False,
    }
    proj = _cpu_project(tmp_path, "dangling", l6=l6)
    _author_rtl(proj)
    r = _run(proj)

    assert r.returncode == 1, r.stdout + r.stderr
    assert "not in the derived state set" in r.stdout


def test_a_single_state_declaration_still_fails_beside_authored_rtl(tmp_path):
    l6 = {
        "fsm_states": [{"name": "ST_ONLY", "transitions": []}],
        "no_fsm_in_input": False, "no_fsm_states_in_input": False,
    }
    proj = _cpu_project(tmp_path, "single", l6=l6)
    _author_rtl(proj)
    r = _run(proj)

    assert r.returncode == 1, r.stdout + r.stderr
    assert "1 FSM state" in r.stdout


# ---------------------------------------------------------------------------
# The provenance reader itself, in both directions, and fail-closed.
# ---------------------------------------------------------------------------

def test_phase2_tree_provenance_answers_both_ways(tmp_path):
    sys.path.insert(0, str(PROGRAMS))
    import l6_fsm_scaffold_actionable_check as gate

    authored = _cpu_project(tmp_path, "prov_authored")
    _author_rtl(authored)
    assert gate._phase2_tree_provenance(authored) == gate.PROV_AUTHORED

    consumed = _cpu_project(tmp_path, "prov_input")
    _author_rtl(consumed)
    (consumed / "phase2" / "stage1" / "rtl"
     / "SOURCE_MANIFEST.json").write_text(json.dumps({"reused_ip": True}),
                                          encoding="utf-8")
    assert gate._phase2_tree_provenance(consumed) == gate.PROV_INPUT


def test_an_unreadable_provenance_predicate_keeps_the_finding_blocking(
        tmp_path, monkeypatch):
    """FAIL-CLOSED, in the direction the rest of this gate already fails in: a
    provenance we cannot read is treated as INPUT-side, so #1977's finding
    survives a broken probe rather than evaporating into an advisory."""
    sys.path.insert(0, str(PROGRAMS))
    import l6_fsm_scaffold_actionable_check as gate

    proj = _cpu_project(tmp_path, "failclosed")
    _author_rtl(proj)
    assert gate._phase2_tree_provenance(proj) == gate.PROV_AUTHORED

    monkeypatch.setattr(gate, "_reused_ip", None)
    assert gate._phase2_tree_provenance(proj) == gate.PROV_INPUT

    class _Raises:
        @staticmethod
        def staged_rtl_is_reused_ip(_project):
            raise RuntimeError("probe is broken")

        @staticmethod
        def staged_vendor_rtl_files(_project):
            raise RuntimeError("probe is broken")

    monkeypatch.setattr(gate, "_reused_ip", _Raises)
    assert gate._phase2_tree_provenance(proj) == gate.PROV_INPUT
    groups = gate._rtl_files_by_provenance(proj)
    assert [g[0] for g in groups] == [gate.PROV_INPUT]


def test_a_design_that_stages_nothing_and_authors_nothing_is_untouched(
        tmp_path):
    """The plain honest case stays exactly what it was."""
    r = _run(_cpu_project(tmp_path, "bare"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout
    assert "AUTHORED_FSM_NO_INPUT_SCAFFOLD" not in r.stdout


def test_authored_rtl_with_no_fsm_raises_no_advisory(tmp_path):
    """The advisory is about a STRUCTURAL FSM, not about the presence of RTL."""
    proj = _cpu_project(tmp_path, "comb")
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "comb.v").write_text(
        "module comb(input wire a, b, output wire y); assign y = a ^ b; "
        "endmodule\n", encoding="utf-8")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "AUTHORED_FSM_NO_INPUT_SCAFFOLD" not in r.stdout
