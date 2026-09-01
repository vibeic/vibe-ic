"""Port-list dedup across restated interfaces + byte-identical input dedup.

Characterized defect (adversarially confirmed, byte-level reproduction): a spec
that RESTATES its interface — the same document staged twice into the project,
or a single document with an Appendix restating the port block — doubled every
parsed port list, because

  * `prose_port_block_read.parse_rtllm_ports` appends for EVERY
    "Input ports:/Output ports:" block with no dedup,
  * `port_parser.parse_ports` (`_bullet_ports`/`_header_ports`) has the same
    exposure, and
  * the renderers emit the doubled list verbatim, so iverilog fails with
    `'a' has already been declared in this scope`.

Upstream, two staging sites let byte-identical content in twice: the phase1
prompt bridge (guards only its own target NAME, not content) and the phase2
plain-spec gather (joins every chunk with no content dedup).

These tests pin the four repair layers:
  1. union-key dedup in both parsers — verbatim restatement keeps the first
     occurrence; contradictory reuse (different width, or input AND output)
     REFUSES the whole parse (never drops a single port: a shorter-but-clean
     interface compiles and is wrong, which is harder to catch than a refusal);
  2. sha256 content dedup at both input-staging sites;
  3. the emit-chain syntax invariant: a module header repeating a port name is
     refused before the chain stands behind it;
  4. §4.05 no-leak: clean single-statement input parses byte-exact as before,
     and distinct-content files are never over-deduped.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import deterministic_emit_chain as chain     # noqa: E402
import port_parser as PP                     # noqa: E402
import prose_port_block_read as BR           # noqa: E402


# A self-made generic prose spec (no dataset text): Overview + port block.
_PROSE_SPEC = (
    "Please write a verilog module that compares two values.\n"
    "The module is a comparator: it compares operand values.\n"
    "Input ports:\n"
    "    a [3:0]: 4-bit operand A.\n"
    "    b [3:0]: 4-bit operand B.\n"
    "Output ports:\n"
    "    eq: high when A equals B.\n"
    "    gt: high when A is greater than B.\n"
    "    lt: high when A is less than B.\n"
    "Implementation:\n"
    "Combinational comparison of A and B.\n")


# --------------------------------------------------------------------------- #
# 1. parser dedup — prose port blocks
# --------------------------------------------------------------------------- #
def test_restated_interface_dedups():
    # One document whose Appendix restates the interface verbatim — the port
    # lists must come back single-statement, first occurrence, order preserved.
    doubled = _PROSE_SPEC + "\nAppendix (interface restated):\n" + _PROSE_SPEC
    ins, outs = BR.parse_rtllm_ports(doubled)
    assert ins == [("a", 4), ("b", 4)]
    assert outs == [("eq", 1), ("gt", 1), ("lt", 1)]


def test_cross_direction_collision_refuses():
    # `input aluc` + `output aluc`: a per-direction dedup would miss this and
    # render an illegal header — the union key must refuse the whole parse.
    t = ("Input ports:\n"
         "    ctl: control word input.\n"
         "Output ports:\n"
         "    ctl: control word echoed back.\n")
    assert BR.parse_rtllm_ports(t) == ([], [])
    assert BR.bridge_prompt(t) == t          # refusal -> no-op bridge -> waive


def test_same_name_different_width_refuses_not_drops():
    # A contradictory restatement (8-bit vs 4-bit) must refuse EVERYTHING —
    # dropping only the conflicting port emits a shorter interface that
    # compiles cleanly and is wrong.
    t = ("Input ports:\n"
         "    d [7:0]: 8-bit data input.\n"
         "    en: enable.\n"
         "Output ports:\n"
         "    q [7:0]: 8-bit data output.\n"
         "Appendix:\n"
         "Input ports:\n"
         "    d [3:0]: 4-bit data input.\n")
    assert BR.parse_rtllm_ports(t) == ([], [])


# --------------------------------------------------------------------------- #
# 2. parser dedup — bullet form (port_parser.parse_ports)
# --------------------------------------------------------------------------- #
def test_bullet_restatement_dedups():
    t = (" - input a (8 bits)\n - input cin\n - output q (8 bits)\n"
         "\nThe interface, restated:\n\n"
         " - input a (8 bits)\n - input cin\n - output q (8 bits)\n")
    ins, outs = PP.parse_ports(t)
    assert ins == [("a", 8), ("cin", 1)]
    assert outs == [("q", 8)]


def test_bullet_cross_direction_refuses():
    assert PP.parse_ports(" - input x\n - output x\n") == ([], [])


def test_bullet_conflicting_width_refuses():
    t = " - input a (8 bits)\n - output q\n - input a (4 bits)\n"
    assert PP.parse_ports(t) == ([], [])


# --------------------------------------------------------------------------- #
# 3. §4.05 no-leak — clean single-statement input is a byte-exact no-op
# --------------------------------------------------------------------------- #
def test_clean_prose_parses_exactly_as_before():
    ins, outs = BR.parse_rtllm_ports(_PROSE_SPEC)
    assert ins == [("a", 4), ("b", 4)]
    assert outs == [("eq", 1), ("gt", 1), ("lt", 1)]
    bridged = BR.bridge_prompt(_PROSE_SPEC)
    assert bridged == (
        " - input a (4 bits)\n - input b (4 bits)\n"
        " - output eq\n - output gt\n - output lt\n\n" + _PROSE_SPEC)


def test_clean_bullets_parse_exactly_as_before():
    t = " - input a (8 bits)\n - input cin\n - output q (8 bits)\n"
    assert PP.parse_ports(t) == ([("a", 8), ("cin", 1)], [("q", 8)])


# --------------------------------------------------------------------------- #
# 4. input staging dedup — phase2 gather + phase1 prompt bridge
# --------------------------------------------------------------------------- #
def _gather(project):
    import design_one_shot_runner as runner  # noqa: PLC0415 — heavy import
    return runner._gather_phase1_plain_spec_text(project)


def test_byte_identical_input_files_gathered_once(tmp_path):
    doc_dir = tmp_path / "phase1" / "input_doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "design.md").write_text(_PROSE_SPEC)
    (doc_dir / "restaged_copy.md").write_text(_PROSE_SPEC)
    gathered = _gather(tmp_path)
    assert gathered.refusal is None
    assert gathered.text.count("Input ports:") == 1
    assert len(gathered.sources) == 1


def test_distinct_content_files_both_gathered(tmp_path):
    # §4.05 boundary-outside: dedup must key on CONTENT, never on similarity —
    # two different documents both contribute.
    doc_dir = tmp_path / "phase1" / "input_doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "design.md").write_text(_PROSE_SPEC)
    (doc_dir / "notes.md").write_text("Timing note: outputs settle in 1 cycle.\n")
    gathered = _gather(tmp_path)
    assert gathered.refusal is None
    assert "Input ports:" in gathered.text
    assert "Timing note:" in gathered.text
    assert len(gathered.sources) == 2


def test_phase1_bridge_detects_byte_identical_doc(tmp_path):
    import phase1_one_shot_runner as p1  # noqa: PLC0415 — heavy import
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    prompt = tmp_path / "input" / "phase1_prompt.md"
    prompt.write_text(_PROSE_SPEC)
    # same bytes already staged under a DIFFERENT name -> bridge must not copy
    (docs / "operator_staged.md").write_text(_PROSE_SPEC)
    assert p1._docs_hold_identical_bytes(docs, prompt) is True
    # distinct content -> the prompt still JOINS the docs (v1.14.50 behavior)
    (docs / "operator_staged.md").write_text("A different vendor document.\n")
    assert p1._docs_hold_identical_bytes(docs, prompt) is False


# --------------------------------------------------------------------------- #
# 5. emit-chain exit guard — duplicate header port names refuse the emit
# --------------------------------------------------------------------------- #
def test_duplicate_header_port_names_detected():
    dup = ("module TopModule(input clk, input [7:0] a, output reg q,\n"
           "                 input [7:0] a);\nendmodule\n")
    assert chain._duplicate_header_port_names(dup) == ["a"]
    why = chain._refusals("some spec", dup, None, check=False)
    assert why and "duplicate-header-port" in why[0]


def test_clean_header_is_not_refused():
    ok = ("// a comment mentioning a, a, a\n"
          "module TopModule #(parameter W = 8)(\n"
          "    input clk, input wire [W-1:0] a, output reg q);\nendmodule\n")
    assert chain._duplicate_header_port_names(ok) == []
    assert chain._refusals("some spec", ok, None, check=False) == []


# --------------------------------------------------------------------------- #
# 6. end-to-end: doubled prompt -> emit chain -> iverilog -g2012 accepts
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="iverilog not installed")
def test_doubled_prompt_emits_compilable_rtl(tmp_path):
    doubled = _PROSE_SPEC + "\nAppendix (interface restated):\n" + _PROSE_SPEC
    kind, rtl, rejected = chain.try_emit_ex(
        doubled, "", "TopModule", None, False)
    assert kind is not None and rtl, (
        f"the chain must still emit on a restated interface; rejected={rejected}")
    src = tmp_path / "top.sv"
    src.write_text(rtl)
    proc = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "a.out"), str(src)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
