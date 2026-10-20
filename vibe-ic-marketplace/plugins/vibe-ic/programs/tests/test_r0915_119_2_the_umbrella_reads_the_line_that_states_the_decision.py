#!/usr/bin/env python3
"""R-0915-119(2) — the P0 umbrella must read the line that STATES the decision.

MEASURED END TO END, run26 (front door, main 1429a7752, image 0.3.67 by
digest): all seven structural checkers still reached the record as
`reason_class=EXECUTION_ERROR` and Step P0 was still `partial_population` —
after the class, after the report channel and after the general-stdout
channel were all in place and green.

The reason is a THIRD door. `_run_structural_rtl_gates` does not classify a
gate's stdout; it calls `_p0_skip_reason_from_output()`, which returns ONE
line — `informative[0]`, the first non-banner line — and passes that single
line as `message=`. Six of the seven print their old banner first and their
class second:

    arbiter_starvation_check
        picked : '[skipped] no arbitration patterns found'        -> EXECUTION_ERROR
        missed : '[NOT_APPLICABLE_BY_STRUCTURE] ... enumerated 3 RTL file(s) ...'
    break_handler_safety_check
        picked : 'SKIP @ :0: No break signals detected — not a break-based protocol.'
        missed : '[NOT_APPLICABLE_BY_STRUCTURE] ... enumerated 1 RTL source file(s) ...'

and the seventh behaved correctly for the only reason that its sentence
happened to be line one — which is what made the difference look like a
property of that checker rather than of this function.

THE FIX IS NARROW BY CONSTRUCTION AND NEITHER GUARD MOVES. The only line that
can outrank `informative[0]` is the exact shape `_structural_absence.
sentence()` writes — the class token AND a scanned count AND `found 0`
together. The taxonomy still refuses it below the scanned floor, and still
refuses the class token when it arrives without its enumeration. A gate that
states nothing keeps `informative[0]` byte for byte.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import _flow_reason_taxonomy as T      # noqa: E402
import _structural_absence as SA       # noqa: E402
import flow_compliance_check as F      # noqa: E402

CLS = SA.NOT_APPLICABLE_BY_STRUCTURE
GATE = "probe_check"
EV = SA.absence("RTL file(s) staged for this design", 3)
SENTENCE = SA.sentence(EV, GATE)
BANNER = "[skipped] no arbitration patterns found"


def _classify(line: str) -> str:
    """The umbrella's own call, with the arm's own evidence assumption."""
    return T.infer_nonverdict_reason(
        verdict="SKIP", message=line,
        evidence={"exit_code": 2, "skip_kind": "input-missing"})


# ── 1. the banner-first shape, which is what run26 measured ───────────────
def test_the_banner_first_then_the_sentence_is_decided():
    out = f"=== {GATE} (proj) ===\n  {BANNER}\n  {SENTENCE}\n"
    line = F._p0_skip_reason_from_output(GATE, out, "")
    assert CLS in line, line
    assert _classify(line) == CLS


def test_the_sentence_alone_is_decided():
    out = f"=== {GATE} (proj) ===\n  {SENTENCE}\n"
    line = F._p0_skip_reason_from_output(GATE, out, "")
    assert _classify(line) == CLS


def test_the_sentence_last_among_many_lines_is_still_found():
    out = ("=== probe ===\n" + "".join(f"  note {i}\n" for i in range(12))
           + f"  {SENTENCE}\n")
    assert _classify(F._p0_skip_reason_from_output(GATE, out, "")) == CLS


def test_the_sentence_on_stderr_is_found_when_stdout_is_empty():
    line = F._p0_skip_reason_from_output(GATE, "", f"  {SENTENCE}\n")
    assert _classify(line) == CLS


# ── 2. a gate that states nothing is untouched ────────────────────────────
def test_a_gate_that_states_no_class_keeps_its_first_line():
    out = f"=== {GATE} (proj) ===\n  {BANNER}\n  and a second line\n"
    assert F._p0_skip_reason_from_output(GATE, out, "") == BANNER
    assert _classify(BANNER) == T.EXECUTION_ERROR


@pytest.mark.parametrize("out,expect", [
    ("", ""),
    # a banner-only output is filtered to nothing and returns "", which is
    # the behaviour before this branch and must stay it.
    ("=== only a banner ===", ""),
    ("  NONE could be aged\n  second\n", "NONE could be aged"),
])
def test_the_legacy_shapes_are_byte_for_byte_unchanged(out, expect):
    assert F._p0_skip_reason_from_output("waiver_staleness_check",
                                         out, "") == expect


def test_the_gate_name_prefix_is_still_stripped():
    out = f"  {GATE}: no opcode override doc found\n"
    assert F._p0_skip_reason_from_output(GATE, out, "") == \
        "no opcode override doc found"


# ── 3. both guards survive the new door ───────────────────────────────────
def test_a_sentence_below_the_scanned_floor_is_not_decided():
    """Guard (i) at the taxonomy: the shape alone is not the claim."""
    fake = (f"[{CLS}] {GATE}: enumerated 0 RTL file(s) staged for this "
            f"design and found 0 — this design has no such subject")
    line = F._p0_skip_reason_from_output(GATE, f"  {BANNER}\n  {fake}\n", "")
    assert _classify(line) != CLS


def test_a_bare_class_token_on_a_line_is_not_decided():
    bare = f"[{CLS}] {GATE}: this design has no such subject"
    line = F._p0_skip_reason_from_output(GATE, f"  {BANNER}\n  {bare}\n", "")
    assert line == BANNER, line          # not even picked up
    assert _classify(line) != CLS


def test_a_sentence_with_a_nonzero_found_is_not_decided():
    fake = (f"[{CLS}] {GATE}: enumerated 9 RTL file(s) staged for this "
            f"design and found 4 — this design has no such subject")
    line = F._p0_skip_reason_from_output(GATE, f"  {BANNER}\n  {fake}\n", "")
    assert line == BANNER, line
    assert _classify(line) != CLS


def test_the_finder_returns_none_when_nothing_states_the_class():
    assert T.structural_absence_line(f"{BANNER}\nsecond line\n") is None
    assert T.structural_absence_line("") is None
    assert T.structural_absence_line(None) is None


# ── 4. the mutation arm: restore informative[0] and the six go back ───────
def test_restoring_informative_zero_reproduces_the_run26_defect(monkeypatch):
    """The falsifier for this whole branch. With the preference removed the
    banner-first gates land back in EXECUTION_ERROR — which is exactly what
    run26 recorded, so the measurement and the repair are about the same
    line."""
    import re as _re

    def _mutant(gate_name, stdout, stderr):
        lines = (stdout.strip() or stderr.strip()).splitlines()
        informative = [ln.strip() for ln in lines if ln.strip()
                       and not _re.match(r"^=+.*=+$", ln.strip())]
        return (informative[0] if informative else "")[:200]

    out = f"=== {GATE} (proj) ===\n  {BANNER}\n  {SENTENCE}\n"
    assert _classify(F._p0_skip_reason_from_output(GATE, out, "")) == CLS
    monkeypatch.setattr(F, "_p0_skip_reason_from_output", _mutant)
    assert _classify(F._p0_skip_reason_from_output(GATE, out, "")) == \
        T.EXECUTION_ERROR


# ── 5. the seven, through the umbrella's own door, on real output ─────────
PROJECT_CHECKERS = ["arbiter_starvation_check", "bram_pdob_combinational_check",
                    "cross_module_1cycle_handshake_check",
                    "frame_end_detection_check",
                    "l4_regmap_enumerated_values_typed_check"]
RTL_DIR_CHECKERS = ["tx_abort_during_transmission_check",
                    "break_handler_safety_check"]
PLAIN_RTL = ("module plain (input clk, input rst_n, input [7:0] d,\n"
             "              output reg [7:0] q);\n"
             "  always @(posedge clk) if (!rst_n) q <= 8'h00; else q <= d;\n"
             "endmodule\n")


@pytest.fixture(scope="module")
def plain_project(tmp_path_factory):
    import json
    p = tmp_path_factory.mktemp("plain") / "proj"
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "plain.v").write_text(PLAIN_RTL)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs" / "L4_REGMAP.json").write_text(json.dumps(
        {"schema_version": 2, "doc_class": "regmap", "ic_name": "x",
         "registers": [{"name": "CTRL", "address": "0x00", "fields": [
             {"field_name": f"BIT{i}", "bits": str(i), "lsb": i}
             for i in range(8)]}]}))
    return p


@pytest.mark.parametrize("mod", PROJECT_CHECKERS + RTL_DIR_CHECKERS)
def test_every_structural_checker_is_decided_through_the_umbrella_door(
        mod, plain_project):
    arg = (plain_project if mod in PROJECT_CHECKERS
           else plain_project / "phase2" / "stage1" / "rtl")
    r = subprocess.run([sys.executable, str(PROG / f"{mod}.py"), str(arg)],
                       capture_output=True, text=True)
    line = F._p0_skip_reason_from_output(mod, r.stdout, r.stderr)
    cls = _classify(line)
    assert cls == CLS, (mod, r.returncode, line, cls)
    assert cls in T.SKIP_ELIGIBLE


JSON_CHECKERS = [name for name in PROJECT_CHECKERS + RTL_DIR_CHECKERS
                 if name != "l4_regmap_enumerated_values_typed_check"]


@pytest.mark.parametrize("gate", JSON_CHECKERS)
def test_real_p0_dispatch_preserves_the_leaf_enumeration(tmp_path, monkeypatch, gate):
    project = tmp_path / "project"
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "plain.v").write_text(PLAIN_RTL)
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_RTL_STRUCTURE.json").write_text(json.dumps({
        "schema_version": 2, "submodules": [{"name": "plain"}],
        "memories": [{"name": "external_memory"}]}))
    (docs / "L6_CONTROL_LOGIC.json").write_text(json.dumps({
        "schema_version": 2, "fsm_states": [{"name": "IDLE"}]}))
    # Select real registered consumers; do not substitute their result or
    # bypass the umbrella's argv, subprocess, report reader or record guard.
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", (gate,))
    records = []
    F._run_structural_rtl_gates(project, records_out=records)
    assert len(records) == 1
    record = records[0]
    assert record["evidence"].get("exit_code") == 2, record
    assert record["reason_class"] == CLS, record
    assert record["verdict"] == "SKIP", record  # never PASS credit
    assert SA.is_valid(record["evidence"].get(SA.EVIDENCE_KEY)), record


@pytest.mark.parametrize("enumeration", [None, {},
    {"population": "modules", "scanned": 0, "found": 0},
    {"population": "modules", "scanned": 1, "found": 1},
    {"population": "modules", "scanned": True, "found": 0}])
def test_p0_record_still_refuses_an_unbacked_structural_class(enumeration):
    record = F._p0_gate_record(
        "probe_check", "SKIP", SENTENCE,
        {"exit_code": 2, SA.EVIDENCE_KEY: enumeration}, reason_class=CLS)
    assert record["verdict"] == "INCOMPLETE"
    assert record["reason_class"] == T.EXECUTION_ERROR


# ── 6. the deck's own hygiene ─────────────────────────────────────────────
def test_no_two_tests_in_this_file_share_a_name():
    tree = ast.parse(Path(__file__).read_text())
    names = [n.name for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(names) == len(set(names)), \
        sorted({n for n in names if names.count(n) > 1})
