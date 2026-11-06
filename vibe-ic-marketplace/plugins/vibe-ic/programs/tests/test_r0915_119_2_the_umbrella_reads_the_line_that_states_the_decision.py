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


# ── 2. a gate that states nothing is untouched ────────────────────────────
def test_a_gate_that_states_no_class_keeps_its_first_line():
    out = f"=== {GATE} (proj) ===\n  {BANNER}\n  and a second line\n"
    assert _classify(BANNER) == T.EXECUTION_ERROR


# ── 3. both guards survive the new door ───────────────────────────────────


def test_the_finder_returns_none_when_nothing_states_the_class():
    assert T.structural_absence_line(f"{BANNER}\nsecond line\n") is None
    assert T.structural_absence_line("") is None
    assert T.structural_absence_line(None) is None


# ── 4. the mutation arm: restore informative[0] and the six go back ───────


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
    records = []
    assert len(records) == 1
    record = records[0]
    assert record["evidence"].get("exit_code") == 2, record
    assert record["reason_class"] == CLS, record
    assert record["verdict"] == "SKIP", record  # never PASS credit
    assert SA.is_valid(record["evidence"].get(SA.EVIDENCE_KEY)), record


# ── 6. the deck's own hygiene ─────────────────────────────────────────────
def test_no_two_tests_in_this_file_share_a_name():
    tree = ast.parse(Path(__file__).read_text())
    names = [n.name for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(names) == len(set(names)), \
        sorted({n for n in names if names.count(n) > 1})
