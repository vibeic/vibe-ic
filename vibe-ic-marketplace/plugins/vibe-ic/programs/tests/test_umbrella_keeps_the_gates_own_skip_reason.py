#!/usr/bin/env python3
"""A non-decisive P0 outcome must carry the reason the gate stated.

THE DEFECT
==========
The P0 structural umbrella runs every registered gate as a subprocess and maps
its exit code onto a record.  For ``rc == 2`` — the repo's "I looked and there
was nothing of mine to check" convention — the umbrella built the record with a
hard-coded empty message and `_p0_skip_entry` rendered it as the BARE GATE NAME.

The gate had already said why.  Measured on the spm run (a serial-parallel
integer multiplier) at plugin v1.11.93, 39 of the 246 registered gates reached
the report as a bare name, among them:

  l3_opcode_response_template_check
      stdout: "[SKIP] l3_opcode_response_template_check: no opcode override
               doc found"
      report: "l3_opcode_response_template_check"

  doc_consistency_no_unresolved_conflicts_check
      stdout: "[SKIP] doc_consistency_no_unresolved_conflicts_check: no
               ADDR-limit conflict (<=1 distinct value across docs)"
      report: "doc_consistency_no_unresolved_conflicts_check"

A bare name cannot be triaged.  "This design has no opcode layer, so there is
no response template to define" and "a producer failed to emit the document
this gate reads" are opposite findings — one is a property of the design, the
other is a program defect owed a fix — and the umbrella collapsed both onto the
same line.  That is the same failure mode v1.11.92 fixed inside
``spec_review_lint``: a skip that does not state its reason is indistinguishable
from a pass, and hides that the check did not run.

Issue #1978 makes that disclosure semantic: only a declared design absence,
verified capability absence, or external work may remain SKIP.  An ambiguous
missing input or a silent rc-2 is incomplete, never silently clean.  The tests
below pin both directions — the gate's words reach the report, and an
unclassified absence cannot acquire a benign reason.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "fcc_skip_reason", PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_skip_reason"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()


def _project_with_rtl(tmp_path: Path) -> Path:
    """The minimum a project needs for the umbrella to dispatch its gates."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, output reg q);\n"
        "  always @(posedge clk) if (!rst_n) q <= 1'b0; else q <= ~q;\n"
        "endmodule\n")
    return tmp_path


def _records(project: Path):
    recs: list = []
    F._run_structural_rtl_gates(project, records_out=recs)
    return recs


def _one(recs, name):
    hit = [r for r in recs if r["name"] == name]
    assert hit, f"{name} is not among the {len(recs)} gate records"
    return hit[0]


# ── direction 1: the reason the gate stated reaches the record ───────────────

@pytest.mark.parametrize("gate,phrase", [
    ("l3_opcode_response_template_check", "override doc"),
])
def test_input_missing_record_carries_the_gates_own_words_and_is_incomplete(
        tmp_path, gate, phrase):
    """END-TO-END through the real umbrella.  Both gates self-skip on a
    project with no vendor opcode/ADDR documents, and both used to reach the
    record with `message == ""`."""
    rec = _one(_records(_project_with_rtl(tmp_path)), gate)
    assert rec["verdict"] == "BLOCKED", rec
    assert rec["reason_class"] == "BLOCKED_BY_UPSTREAM", rec
    assert rec["evidence"].get("skip_kind") == "input-missing", rec
    assert rec["message"].strip(), (
        f"{gate} stated a reason on stdout and the umbrella discarded it")
    assert phrase in rec["message"], rec


def test_input_missing_entry_names_the_reason_beside_the_gate(tmp_path):
    """The projected skip BUCKET — what a human actually reads — must show it
    too, not only the JSON record."""
    _p, _f, skips, _w = F._run_structural_rtl_gates(_project_with_rtl(tmp_path))
    for gate in ("l3_opcode_response_template_check",):
        entry = [s for s in skips if s.split(" ")[0] == gate]
        assert entry, f"{gate} produced no skip entry at all"
        assert entry[0] != gate, (
            f"{gate} reached the report as a bare name with no reason")
        assert "(SKIP:" not in entry[0], entry[0]
        assert "reason_class=" in entry[0], entry[0]
        # the gate's own "[SKIP] <name>:" prefix is not repeated inside
        assert "[SKIP]" not in entry[0], entry[0]


# ── direction 2: nothing may acquire a reason it did not state ───────────────

def test_a_gate_that_stated_nothing_is_loudly_incomplete():
    """Silence cannot be promoted to a declaration-derived absence."""
    rec = F._p0_gate_record(
        "silent_check", "INCOMPLETE", "",
        {"exit_code": 2, "skip_kind": "input-missing"})
    assert rec["reason_class"] == "EXECUTION_ERROR"
    assert F._p0_skip_entry(rec) == (
        "silent_check (INCOMPLETE: reason_class=EXECUTION_ERROR: )")


@pytest.mark.parametrize("raw,expect", [
    # the marker and the gate's own name carry nothing the record lacks
    ("[SKIP] g_check: no opcode override doc found",
     "no opcode override doc found"),
    ("g_check: single-clock topology", "single-clock topology"),
    # a reason with no house prefix survives untouched
    ("no analog blocks declared", "no analog blocks declared"),
    # stripping must never leave nothing: the raw line comes back instead
    ("[SKIP] g_check", "[SKIP] g_check"),
    # a gate that printed nothing gets no message at all
    ("", ""),
])
def test_the_reason_is_normalised_but_never_manufactured(raw, expect):
    assert F._p0_skip_reason_from_output("g_check", raw, "") == expect


def test_the_reason_falls_back_to_stderr_when_stdout_is_empty():
    assert F._p0_skip_reason_from_output(
        "g_check", "", "[SKIP] g_check: nothing staged") == "nothing staged"


def test_a_not_invocable_gate_is_still_not_an_input_missing_skip():
    """rc 2 keeps its two separated meanings: an argv rejection is a CALLER
    defect and must not be laundered into a benign skip with a reason."""
    rec = F._p0_gate_record("bad_argv_check", "NOT_INVOCABLE",
                            "argparse rejected: --rtl-dir is required",
                            {"exit_code": 2})
    entry = F._p0_skip_entry(rec)
    assert rec["reason_class"] == "EXECUTION_ERROR"
    assert "--rtl-dir" in entry
    assert entry != "bad_argv_check"


# ── direction 2: both gates still say NO on an input that has the flaw ───────

def _run_gate(gate: str, project: Path, env_extra=None):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_extra or {})
    return _pr.run(
        [sys.executable, str(PROGRAMS / f"{gate}.py"), str(project)],
        capture_output=True, text=True, env=env)


def test_l3_response_template_gate_still_fails_a_project_that_has_the_flaw(
        tmp_path):
    """A vendor opcode-override doc WITH byte-pattern templates, and an L3 that
    carries no `response_payload_template` for them: the exact defect this gate
    exists to catch.  It must still exit 1."""
    doc = tmp_path / "phase1" / "input_doc"
    doc.mkdir(parents=True)
    (doc / "opcode_detail_vendor.txt").write_text(
        "opcode 0x73 GET_STATE\n"
        "response frame: 73 A5 00 04\n")
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    (gen / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
        {"opcodes": [{"hex": "0x73", "name": "GET_STATE"}]}))

    r = _run_gate("l3_opcode_response_template_check", tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "response_payload_template" in r.stdout


def test_doc_consistency_gate_still_reports_a_real_cross_doc_conflict(
        tmp_path):
    """Two vendor documents stating different ADDR ceilings, and no resolution
    document.  The gate must still detect it and name both values; under the
    blocking switch it must still exit 1."""
    doc = tmp_path / "phase1" / "input_doc"
    doc.mkdir(parents=True)
    (doc / "vendor_a.txt").write_text("ADDR max 0x7f\n")
    (doc / "vendor_b.txt").write_text("address range 0x3f\n")

    warn = _run_gate("doc_consistency_no_unresolved_conflicts_check", tmp_path)
    assert warn.returncode == 0, (warn.returncode, warn.stdout, warn.stderr)
    assert "0x7f" in warn.stdout and "0x3f" in warn.stdout

    hard = _run_gate("doc_consistency_no_unresolved_conflicts_check", tmp_path,
                     {"VIBE_IC_DOC_CONFLICT_BLOCKING": "1"})
    assert hard.returncode == 1, (hard.returncode, hard.stdout, hard.stderr)


def test_doc_consistency_clean_completion_is_a_pass_not_a_skip(tmp_path):
    r = _run_gate("doc_consistency_no_unresolved_conflicts_check", tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "[PASS]" in r.stdout


def test_umbrella_still_records_a_failing_gate_as_a_fail(tmp_path):
    """The rc-1 arm is untouched: a gate that fails is still a FAIL record with
    the gate's own first line, never a skip carrying a reason."""
    rec = F._p0_gate_record("some_check", "FAIL", "[FAIL] some_check: nope",
                            {"exit_code": 1})
    fails, skips, _w = F._p0_buckets_from_records([rec])
    assert fails and not skips
    assert "some_check" in fails[0]
