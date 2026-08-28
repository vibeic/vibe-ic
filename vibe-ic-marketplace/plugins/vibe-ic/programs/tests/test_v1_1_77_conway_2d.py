"""Deterministic 2-D cellular-automaton (Conway's Game of Life-class) -> RTL synth.

The 2-D CA family is a CLOSED-FORM spec, exactly like the 1-D Wolfram Rule-N
family: once the STATED rule pins the BIRTH counts (dead -> alive) and SURVIVAL
counts (alive stays alive), plus the grid geometry (HxW), the toroidal wrap, the
row-major packed mapping, and the 8-cell (Moore) neighbourhood, the next state of
every cell is fully determined with no oracle. A blind author can transpose the
row/col map, off-by-one the wrap, or drop a survival count per round (single-shot
variance). conway_2d_synth absorbs it as a PROGRAM.

§4.05 no-leak: FIRES only on an unambiguous 2-D toroidal Moore CA spec; SKIPs
(returns None) when the grid is 1-D, dims are absent / inconsistent with the
packed width, the neighbourhood isn't 8/Moore, the boundary is zero/dead/unstated
(not toroidal), the packing isn't the stated row-major, the birth/survival rule
isn't fully recoverable, or the interface isn't the canonical clk/load/data[N]/
q[N]. It is MUTUALLY EXCLUSIVE with the 1-D cellular_automaton_synth. The NEGATIVE
cases below sit JUST OUTSIDE the boundary and MUST still skip.

POSITIVE path is host-scored end-to-end with iverilog against the real Prob144
reference + testbench ("Total mismatched samples is 0"); the GENERALITY case is
host-scored against an independent Python golden model on a different rule/dims.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import conway_2d_synth as C  # noqa: E402
import cellular_automaton_synth as C1D  # noqa: E402  (mutual-exclusion partner)
from _hostpaths import corpus_path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
_PROB144 = "Prob144_conwaylife"

# A self-contained Conway (16x16 toroidal Moore, B3/S23) prompt matching the
# VerilogEval Prob144 wording, so the positive path is testable for parsing even
# without the external dataset; the host score still uses the real ref+tb.
_CONWAY = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  load
 - input  data (256 bits)
 - output q (256 bits)

The module should implemement a "game" played on a two-dimensional grid
of cells, where each cell is either 1 (alive) or 0 (dead). At each time
step, each cell changes state depending on how many neighbours it has:

  (1) 0-1 neighbour: Cell becomes 0.
  (2) 2 neighbours: Cell state does not change.
  (3) 3 neighbours: Cell becomes 1.
  (4) 4+ neighbours: Cell becomes 0.

The game is formulated for an infinite grid. In this circuit, we will use
a 16x16 grid. To make things more interesting, we will use a 16x16
toroid, where the sides wrap around to the other side of the grid. For
example, the corner cell (0,0) has 8 neighbours: (15,1), (15,0), (15,15),
(0,1), (0,15), (1,1), (1,0), and (1,15). The 16x16 grid is represented by
a length 256 vector, where each row of 16 cells is represented by a
sub-vector: q[15:0] is row 0, q[31:16] is row 1, etc.

  (1) load: Loads data into q at the next clock edge, for loading initial
       state. Active high synchronous.
  (2) q: The 16x16 current state of the game, updated every clock cycle.

The game state should advance by one timestep every clock cycle. Assume
all sequential logic is triggered on the positive edge of the clock.
"""

# A DIFFERENT stated rule + dims (HighLife B36/S23 on a 4x4 toroid) on a synthetic
# prompt -> the synth must generalize beyond Conway/16x16/Prob144.
_HIGHLIFE_4x4 = """
Implement a module named TopModule.
 - input  clk
 - input  load
 - input  data (16 bits)
 - output q (16 bits)
This is a two-dimensional grid of cells on a 4x4 toroid, where the sides wrap
around to the other side of the grid, so each cell has 8 neighbours. The 4x4
grid is packed row-major into a length 16 vector: q[3:0] is row 0, q[7:4] is
row 1, etc. The rule is B36/S23. The state should advance by one time step
every clock cycle. load loads data into q at the next clock edge.
"""

# A plain B3/S23 (Conway) on a 4x4 toroid, for the host-scored generality sim
# against a Python golden (B36 differs from Conway only in the birth set, so the
# B3/S23 golden below validates the count-membership emit and the wrap map).
_CONWAY_4x4 = _HIGHLIFE_4x4.replace("B36/S23", "B3/S23")


# ===========================================================================
# POSITIVE — the synth fires and is structurally correct
# ===========================================================================
def test_conway_fires_and_interface_is_correct():
    rtl = C.synth(_CONWAY, "TopModule")
    assert rtl is not None
    assert "output reg [255:0] q" in rtl
    assert "q <= data" in rtl and "q <= nxt" in rtl


def test_conway_parses_b3_s23():
    low = C._flat(_CONWAY)
    bs = C._extract_birth_survival(low)
    assert bs is not None
    birth, survive = bs
    assert birth == {3}            # only a dead cell with 3 neighbours is born
    assert survive == {2, 3}       # a live cell survives on 2 or 3


def test_conway_dims_packing_wrap():
    low = C._flat(_CONWAY)
    assert C._extract_dims(low) == (16, 16)
    assert C._neighbourhood_is_moore(low)
    assert C._boundary_is_toroidal(low)
    assert C._packing_is_row_major(low, 16)
    rtl = C.synth(_CONWAY, "TopModule")
    # toroidal wrap arithmetic + row-major bit index present in the emit
    assert "% 16" in rtl
    assert "q[up*16 + lf]" in rtl and "q[dn*16 + rt]" in rtl


def test_rule_is_general_not_keyed():
    # B36/S23 must emit a DIFFERENT birth set than B3/S23 (the rule drives the
    # emitted membership test, not a problem name / Conway hard-coding).
    r_conway = C.synth(_CONWAY_4x4, "TopModule")
    r_high = C.synth(_HIGHLIFE_4x4, "TopModule")
    assert r_conway is not None and r_high is not None
    assert "BIRTH counts {3}" in r_conway
    assert "BIRTH counts {3,6}" in r_high
    assert r_conway != r_high


# ===========================================================================
# MUTUAL EXCLUSION with the 1-D cellular_automaton_synth
# ===========================================================================
def test_two_d_skips_one_d_rule90():
    # The canonical 1-D Rule-90 prompt: the 2-D synth must SKIP it (only the 1-D
    # synth owns it), so at most one CA synth fires per prompt.
    rule90 = """
    Implement a module named TopModule.
     - input  clk
     - input  load
     - input  data (512 bits)
     - output q (512 bits)
    Implement Rule 90, a one-dimensional cellular automaton. At each time step
    the next state of each cell is the XOR of the cell's two current neighbours.
    Advance by one time step each clock cycle. Assume the boundaries (q[-1] and
    q[512]) are both zero (off).
    """
    assert C.synth(rule90, "TopModule") is None
    assert C1D.synth(rule90, "TopModule") is not None  # 1-D owns it


def test_one_d_skips_conway():
    # Symmetric: the 1-D synth must SKIP the 2-D Conway prompt.
    assert C1D.synth(_CONWAY, "TopModule") is None
    assert C.synth(_CONWAY, "TopModule") is not None  # 2-D owns it


# ===========================================================================
# §4.05 NEGATIVE no-leak — JUST outside the boundary, MUST return None (>=5)
# ===========================================================================
def test_skip_when_boundary_unstated():
    # (1) Boundary convention not stated (no toroid/wrap/zero) -> neighbour wiring
    #     unknown -> SKIP. Remove every wrap/toroid mention.
    bad = _CONWAY.replace(
        "To make things more interesting, we will use a 16x16\n"
        "toroid, where the sides wrap around to the other side of the grid. ", "")
    bad = re.sub(r"toroid[^.]*\.", "grid.", bad)
    bad = bad.replace("16x16\ntoroid", "16x16 grid").replace("wrap around", "")
    assert C._boundary_is_toroidal(C._flat(bad)) is False
    assert C.synth(bad, "TopModule") is None


def test_skip_when_boundary_is_zero_not_toroidal():
    # (2) A STATED finite/zero (dead off-array) boundary is NOT toroidal -> the
    #     wrap wiring this synth emits is wrong -> SKIP.
    bad = _CONWAY.replace(
        "we will use a 16x16\ntoroid, where the sides wrap around to the other "
        "side of the grid",
        "we will use a 16x16 finite grid where boundary cells are dead")
    bad = re.sub(r"toroid.*?grid\.", "finite grid where boundary cells are dead.",
                 bad, flags=re.S)
    assert C.synth(bad, "TopModule") is None


def test_skip_when_packing_unstated():
    # (3) Row-major packed mapping not stated -> the bit<->(row,col) map is a
    #     guess -> SKIP.
    bad = re.sub(
        r"The 16x16 grid is represented by.*?q\[31:16\] is row 1, etc\.",
        "The 16x16 grid is stored in a length 256 vector.",
        _CONWAY, flags=re.S)
    assert C._packing_is_row_major(C._flat(bad), 16) is False
    assert C.synth(bad, "TopModule") is None


def test_skip_when_one_dimensional():
    # (4) A 1-D CA (Rule 90) must defer to the 1-D synth -> 2-D SKIP.
    one_d = """
    Implement a module named TopModule.
     - input  clk
     - input  load
     - input  data (256 bits)
     - output q (256 bits)
    Implement Rule 90, a one-dimensional cellular automaton over a 256-cell row.
    Advance one time step each clock cycle; boundaries q[-1] and q[256] are zero.
    """
    assert C.synth(one_d, "TopModule") is None


def test_skip_on_wrong_neighbourhood_von_neumann():
    # (5) A 4-cell von Neumann neighbourhood is NOT the 8-cell Moore one -> SKIP.
    bad = _CONWAY.replace(
        "the corner cell (0,0) has 8 neighbours",
        "each cell has 4 nearest neighbours (von Neumann)")
    bad = re.sub(r"has 8 neighbours.*?and \(1,15\)\.",
                 "has 4 nearest neighbours (von Neumann).", bad, flags=re.S)
    assert C._neighbourhood_is_moore(C._flat(bad)) is False
    assert C.synth(bad, "TopModule") is None


def test_skip_on_dims_width_mismatch():
    # (6) H*W must equal the packed q width: 16x16 stated but q is 128 bits -> SKIP.
    bad = _CONWAY.replace("data (256 bits)", "data (128 bits)") \
                 .replace("q (256 bits)", "q (128 bits)")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_absent_dims():
    # (7) No HxW dimensions stated -> grid geometry unknown -> SKIP.
    bad = re.sub(r"16x16", "square", _CONWAY)
    bad = bad.replace("16-by-16", "square")
    assert C._extract_dims(C._flat(bad)) is None
    assert C.synth(bad, "TopModule") is None


def test_skip_on_missing_load_port():
    # (8) Interface mismatch (no load) -> not the canonical CA interface -> SKIP.
    bad = _CONWAY.replace(" - input  load\n", "")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_extra_port():
    # (9) An unexpected extra port -> interface isn't the canonical CA one -> SKIP.
    bad = _CONWAY.replace(" - input  load\n", " - input  load\n - input  rst\n")
    assert C.synth(bad, "TopModule") is None


def test_skip_on_incomplete_rule_table():
    # (10) The count table must classify every count 0..8; drop the "2 neighbours"
    #      row -> count 2 is unclassified -> SKIP (never guess survival).
    bad = _CONWAY.replace("  (2) 2 neighbours: Cell state does not change.\n", "")
    assert C._extract_birth_survival(C._flat(bad)) is None
    assert C.synth(bad, "TopModule") is None


# ===========================================================================
# HOST-SCORE — end-to-end iverilog 0-mismatch
# ===========================================================================
def _iverilog_available() -> bool:
    from shutil import which
    return which("iverilog") is not None and which("vvp") is not None


def test_host_score_prob144_zero_mismatch(tmp_path):
    if not _iverilog_available():
        pytest.skip("iverilog/vvp not available")
    prompt = _DS / f"{_PROB144}_prompt.txt"
    ref = _DS / f"{_PROB144}_ref.sv"
    tb = _DS / f"{_PROB144}_test.sv"
    if not (prompt.exists() and ref.exists() and tb.exists()):
        pytest.skip("Prob144 dataset files not present")
    rtl = C.synth(prompt.read_text(errors="replace"), "TopModule")
    assert rtl is not None, "Prob144 must FIRE"
    dut = tmp_path / "dut.sv"
    dut.write_text(rtl)
    vvp = tmp_path / "a.vvp"
    comp = subprocess.run(
        ["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(tb)],
        capture_output=True, text=True)
    assert comp.returncode == 0, f"compile failed:\n{comp.stderr}"
    run = _pr.run(["vvp", str(vvp)], capture_output=True, text=True)
    out = run.stdout + run.stderr
    m = re.search(r"mismatched samples is (\d+)", out)
    assert m is not None, f"no mismatch line in vvp output:\n{out}"
    assert int(m.group(1)) == 0, f"Prob144 had {m.group(1)} mismatches:\n{out}"


def _python_golden_b3s23_4x4(seed: int, steps: int) -> int:
    """Independent reference: B3/S23 on a 4x4 toroid, row-major bit i*4+j."""
    H = W = 4
    g = [(seed >> k) & 1 for k in range(H * W)]
    for _ in range(steps):
        n = [0] * (H * W)
        for i in range(H):
            for j in range(W):
                c = 0
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        if di == 0 and dj == 0:
                            continue
                        c += g[((i + di) % H) * W + ((j + dj) % W)]
                alive = g[i * W + j]
                n[i * W + j] = 1 if ((alive and c in (2, 3))
                                     or ((not alive) and c == 3)) else 0
        g = n
    return sum(b << k for k, b in enumerate(g))


def test_host_score_generality_4x4_b3s23(tmp_path):
    # GENERALITY: a DIFFERENT dims (4x4) + rule (B3/S23) prompt, host-scored
    # against an independent Python golden across several seeds x 2 steps. This
    # proves the wrap map / packing / count-membership generalize beyond Prob144.
    if not _iverilog_available():
        pytest.skip("iverilog/vvp not available")
    rtl = C.synth(_CONWAY_4x4, "TopModule")
    assert rtl is not None, "synthetic 4x4 B3/S23 must FIRE"
    seeds = [0x0007, 0x0231, 0xFFFF, 0x1248, 0xA5A5, 0x8001]
    g1 = {s: _python_golden_b3s23_4x4(s, 1) for s in seeds}
    g2 = {s: _python_golden_b3s23_4x4(s, 2) for s in seeds}
    checks = "\n".join(
        f'    chk(16\'h{s:04x},16\'h{g1[s]:04x},16\'h{g2[s]:04x});' for s in seeds)
    tb = f"""module tb;
  reg clk=0, load; reg [15:0] data; wire [15:0] q;
  TopModule d(.clk(clk),.load(load),.data(data),.q(q));
  always #5 clk=~clk;
  integer errors=0;
  task chk(input [15:0] seed, input [15:0] s1, input [15:0] s2);
    begin
      @(negedge clk); load=1'b1; data=seed; @(posedge clk);
      @(negedge clk); load=1'b0;            @(posedge clk); #1;
      if (q!==s1) begin errors=errors+1; $display("STEP1 seed=%04h got=%04h exp=%04h",seed,q,s1); end
      @(posedge clk); #1;
      if (q!==s2) begin errors=errors+1; $display("STEP2 seed=%04h got=%04h exp=%04h",seed,q,s2); end
    end
  endtask
  initial begin
{checks}
    if (errors==0) $display("Total mismatched samples is 0"); else $display("FAIL %0d", errors);
    $finish;
  end
endmodule
"""
    dut = tmp_path / "dut.sv"
    dut.write_text(rtl)
    (tmp_path / "tb.sv").write_text(tb)
    vvp = tmp_path / "a.vvp"
    comp = subprocess.run(
        ["iverilog", "-g2012", "-o", str(vvp), str(dut), str(tmp_path / "tb.sv")],
        capture_output=True, text=True)
    assert comp.returncode == 0, f"compile failed:\n{comp.stderr}"
    run = _pr.run(["vvp", str(vvp)], capture_output=True, text=True)
    out = run.stdout + run.stderr
    assert "Total mismatched samples is 0" in out, \
        f"generality 4x4 B3/S23 mismatched:\n{out}"


# ===========================================================================
# CORPUS no-leak sweep — conway_2d fires ONLY where appropriate, never collides
# with the 1-D synth, across the whole VerilogEval corpus (if present).
# ===========================================================================
def test_corpus_no_leak_and_no_collision_with_1d():
    if not _DS.exists():
        pytest.skip("VerilogEval dataset not present")
    prompts = sorted(_DS.glob("*_prompt.txt"))
    if not prompts:
        pytest.skip("no prompts in dataset")
    collide = []
    fired_2d = []
    for p in prompts:
        t = p.read_text(errors="replace")
        r2 = C.synth(t, "TopModule") is not None
        r1 = C1D.synth(t, "TopModule") is not None
        if r2:
            fired_2d.append(p.name)
        if r2 and r1:
            collide.append(p.name)
    # never fires on the same prompt as the 1-D synth
    assert collide == [], f"2-D/1-D CA collision on: {collide}"
    # the only known 2-D CA in this corpus is Prob144
    assert fired_2d == [f"{_PROB144}_prompt.txt"], \
        f"unexpected 2-D fires: {fired_2d}"
