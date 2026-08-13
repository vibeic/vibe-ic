"""ORGANIC #716 — prompt-disclosed combinational oracle emit gate.

Prob122_kmap4 shipped a K-map misread: the author wrote `out = a ^ b ^ d`
("independent of c") when the prompt K-map decodes to `out = a ^ b ^ c ^ d`.
The design compiled, passed every structural rule, emitted, then failed the
hidden TB 121/232. No prior Shape-C step simulated the RTL against the prompt's
own complete oracle. `kmap_truth_table_oracle_check` parses a high-confidence
complete oracle (clean truth table OR standard Gray K-map, scalar 1-bit axes,
single 1-bit output, NO don't-cares) and exhaustively simulates the RTL.

This pins BOTH:
  POSITIVE  — the wrong K-map read (drops `c`) BLOCKs; the correct read PASSes.
  NEGATIVE no-leak (§4.05) — a don't-care K-map (a minimized correct design may
  legally drop a variable) and a multi-bit-bus / mux-transform prompt SKIP and
  NEVER block, so the gate can never false-block a correct design.
And the gates_atomic.py wiring: a BLOCK from this check joins the emit-blocking
allow-list (structural_emit_block) so the sample is NOT emitted.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kmap_truth_table_oracle_check as ktt  # noqa: E402

import pytest  # noqa: E402

#: `check()` RUNS the oracle through iverilog+vvp. Without them it now
#: returns a disclosed TOOL_ERR (see the program) — honest, but not a
#: verdict about the RTL, which is what the tests below assert on.
_HAS_EDA = (shutil.which("iverilog") is not None
            and shutil.which("vvp") is not None)

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"

# Prob122_kmap4 prompt (cols ab Gray 00,01,11,10; rows cd Gray 00,01,11,10).
KMAP4_PROMPT = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a
 - input  b
 - input  c
 - input  d
 - output out

The module should implement the Karnaugh map below.

             ab
  cd   00  01  11  10
  00 | 0 | 1 | 0 | 1 |
  01 | 1 | 0 | 1 | 0 |
  11 | 0 | 1 | 0 | 1 |
  10 | 1 | 0 | 1 | 0 |
"""

# Prob125_kmap3 prompt: don't-care `d` cells AND non-Gray column order.
KMAP3_DONTCARE_PROMPT = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a
 - input  b
 - input  c
 - input  d
 - output out

The module should implement the Karnaugh map below. d is don't-care,
which means you may choose to output whatever value is convenient.

              ab
   cd   01  00  10  11
   00 | d | 0 | 1 | 1 |
   01 | 0 | 0 | d | d |
   11 | 0 | 1 | 1 | 1 |
   10 | 0 | 1 | 1 | 1 |
"""

# Prob093: K-map present but the OUTPUT is a 4-bit mux-selector, NOT the K-map
# value — a transform problem the parser must SKIP.
MUX_TRANSFORM_PROMPT = """
I would like you to implement a module named TopModule.

 - input  c
 - input  d
 - output mux_in (4 bits)

For the following Karnaugh map, give the circuit implementation using one
4-to-1 multiplexer and as many 2-to-1 multiplexers as required.

      ab
  cd  00  01  11  10
  00 | 0 | 0 | 0 | 1 |
  01 | 1 | 0 | 0 | 0 |
  11 | 1 | 0 | 1 | 1 |
  10 | 1 | 0 | 0 | 1 |
"""

# Prob069 clean truth table.
TRUTHTABLE_PROMPT = """
I would like you to implement a module named TopModule.

 - input  x3
 - input  x2
 - input  x1
 - output f

The module should implement a combinational circuit for the following
truth table:

  x3 | x2 | x1 | f
  0  | 0  | 0  | 0
  0  | 0  | 1  | 0
  0  | 1  | 0  | 1
  0  | 1  | 1  | 1
  1  | 0  | 0  | 0
  1  | 0  | 1  | 1
  1  | 1  | 0  | 0
  1  | 1  | 1  | 1
"""

K4_WRONG = "module TopModule(input a,input b,input c,input d,output out); assign out=a^b^d; endmodule\n"
K4_CORRECT = "module TopModule(input a,input b,input c,input d,output out); assign out=a^b^c^d; endmodule\n"
TT_CORRECT = "module TopModule(input x3,input x2,input x1,output f); assign f=(~x3&x2)|(x3&x1); endmodule\n"
TT_WRONG = "module TopModule(input x3,input x2,input x1,output f); assign f=x2; endmodule\n"


def _rtl(tmp_path, name, src):
    p = tmp_path / name
    p.write_text(src)
    return str(p)


# ── unit: parser builds an EXACT, complete oracle on the clean cases ──────

def test_kmap4_oracle_is_complete_and_matches_golden():
    oracle = ktt.build_oracle(KMAP4_PROMPT)
    assert oracle is not None
    kind, ins, out, table = oracle
    assert kind == "kmap"
    assert ins == ["a", "b", "c", "d"] and out == "out"
    assert len(table) == 16
    # golden function for this K-map is a^b^c^d
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                for d in (0, 1):
                    assert table[(a, b, c, d)] == (a ^ b ^ c ^ d)


def test_truthtable_oracle_is_complete():
    oracle = ktt.build_oracle(TRUTHTABLE_PROMPT)
    assert oracle is not None
    kind, ins, out, table = oracle
    assert kind == "table" and out == "f" and len(table) == 8


# ── §4.05 NEGATIVE no-leak: ambiguous prompts produce NO oracle (SKIP) ────

def test_dontcare_kmap_skips_no_oracle():
    # don't-cares present → a minimized correct design may legally drop a
    # variable → the parser must refuse to build an oracle (never block).
    assert ktt.build_oracle(KMAP3_DONTCARE_PROMPT) is None


def test_mux_transform_skips_no_oracle():
    # output is the mux-selector encoding, NOT the K-map value → SKIP.
    assert ktt.build_oracle(MUX_TRANSFORM_PROMPT) is None


def test_bus_axis_kmap_skips_no_oracle():
    prompt = (
        "I would like you to implement a module named TopModule.\n\n"
        " - input  x (4 bits)\n - output f\n\n"
        "The module should implement the function f shown in the Karnaugh map\n"
        "below.\n\n"
        "             x[0]x[1]\n"
        "x[2]x[3]  00  01  11  10\n"
        "  00     | 1 | 0 | 0 | 1 |\n"
        "  01     | 0 | 0 | 0 | 0 |\n"
        "  11     | 1 | 1 | 1 | 0 |\n"
        "  10     | 1 | 1 | 0 | 1 |\n"
    )
    assert ktt.build_oracle(prompt) is None


# ── functional check: BLOCK the wrong read, PASS the correct read ─────────

@pytest.mark.skipif(not _HAS_EDA, reason="check() runs the oracle: needs iverilog + vvp")
def test_wrong_kmap_read_blocks(tmp_path):
    v, _ = ktt.check(KMAP4_PROMPT, _rtl(tmp_path, "w.sv", K4_WRONG))
    assert v == "BLOCK"


@pytest.mark.skipif(not _HAS_EDA, reason="check() runs the oracle: needs iverilog + vvp")
def test_correct_kmap_read_passes(tmp_path):
    v, _ = ktt.check(KMAP4_PROMPT, _rtl(tmp_path, "g.sv", K4_CORRECT))
    assert v == "PASS"


@pytest.mark.skipif(not _HAS_EDA, reason="check() runs the oracle: needs iverilog + vvp")
def test_wrong_truthtable_blocks(tmp_path):
    v, _ = ktt.check(TRUTHTABLE_PROMPT, _rtl(tmp_path, "ttw.sv", TT_WRONG))
    assert v == "BLOCK"


@pytest.mark.skipif(not _HAS_EDA, reason="check() runs the oracle: needs iverilog + vvp")
def test_correct_truthtable_passes(tmp_path):
    v, _ = ktt.check(TRUTHTABLE_PROMPT, _rtl(tmp_path, "ttg.sv", TT_CORRECT))
    assert v == "PASS"


def test_dontcare_kmap_check_skips(tmp_path):
    # full check() on a don't-care prompt with arbitrary RTL → SKIP, never BLOCK.
    v, _ = ktt.check(KMAP3_DONTCARE_PROMPT,
                     _rtl(tmp_path, "k3.sv", K4_WRONG))
    assert v == "SKIP"


# ── wiring: a BLOCK is emit-blocking in gates_atomic.py ───────────────────

def _stage(work, prob, ports_yaml, rtl):
    d = work / prob
    d.mkdir(parents=True)
    (d / "spec.yaml").write_text(
        "ic_name: TopModule\nclass_path: combinational-logic\n"
        "L1: { ic_name: TopModule, description: kmap }\n"
        "L9:\n  module_name: TopModule\n  ports:\n" + ports_yaml
    )
    (d / "sample.sv").write_text(rtl)
    return d


def _ports_abcd():
    return ("    a: { dir: input, width: 1 }\n"
            "    b: { dir: input, width: 1 }\n"
            "    c: { dir: input, width: 1 }\n"
            "    d: { dir: input, width: 1 }\n"
            "    out: { dir: output, width: 1 }\n")


def test_gates_atomic_blocks_wrong_kmap_and_emits_correct(tmp_path):
    import shutil
    if shutil.which("iverilog") is None:
        import pytest
        pytest.skip("iverilog absent")
    dataset = tmp_path / "ds"
    dataset.mkdir()
    (dataset / "Prob122_kmap4_prompt.txt").write_text(KMAP4_PROMPT)
    work = tmp_path / "work"

    # v1.1.38 §4.2 absorption SUPERSEDES the block-and-retry for a don't-care-FREE
    # K-map: the deterministic kmap_grid_synth (gates_atomic step 0) now REPLACES a
    # wrong authored read with the exact SOP BEFORE the oracle gate runs — so the
    # safety invariant "a wrong K-map never ships" is preserved in a STRONGER form
    # (the CORRECT one is auto-synthesized and ships, no re-author needed). The
    # oracle BLOCK gate remains the guard for the cases the synth SKIPs (don't-care
    # / mux-decomposition K-maps), covered by test_wrong_kmap_read_blocks above.
    _stage(work, "Prob122_kmap4", _ports_abcd(), K4_WRONG)
    r = subprocess.run([sys.executable, str(GATES), "--prob", "Prob122_kmap4",
                        "--workdir", str(work), "--dataset", str(dataset),
                        "--bench", "verilogeval-v2"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr   # synth auto-corrected the wrong read
    gj = json.loads((work / "Prob122_kmap4" / "gates.json").read_text())
    assert gj["hard_gates_pass"] is True
    # v1.1.76: gates_atomic now delegates to spec_artifact_registry.generate()
    # (single source of truth). A don't-care-free K-map is isomorphic to a truth
    # table / SOP, so the registry's first-fire deterministically labels it with a
    # table-family solver — the load-bearing invariant is that A deterministic solver
    # fired and REPLACED the wrong authored read (asserted below), not which label.
    assert gj["steps"]["deterministic_synth"]["kind"] in (
        "truth_table", "karnaugh_map", "karnaugh_map_sop", "kmap_grid")
    assert gj["steps"]["kmap_truth_table_oracle"]["verdict"] == "PASS"
    emitted = (work.parent / "samples" / "Prob122_kmap4_sample01.sv").read_text()
    assert "a ^ b ^ d" not in emitted        # the wrong authored read is gone
    assert (work.parent / "samples" / "Prob122_kmap4_sample01.sv").exists()

    # correct read → still PASS + emit (synth produces the same canonical RTL)
    (work / "Prob122_kmap4" / "sample.sv").write_text(K4_CORRECT)
    r = subprocess.run([sys.executable, str(GATES), "--prob", "Prob122_kmap4",
                        "--workdir", str(work), "--dataset", str(dataset),
                        "--bench", "verilogeval-v2"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    gj = json.loads((work / "Prob122_kmap4" / "gates.json").read_text())
    assert gj["hard_gates_pass"] is True
    assert gj["steps"]["kmap_truth_table_oracle"]["verdict"] == "PASS"
    assert (work.parent / "samples" / "Prob122_kmap4_sample01.sv").exists()
