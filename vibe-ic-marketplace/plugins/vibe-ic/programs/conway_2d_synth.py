#!/usr/bin/env python3
"""conway_2d_synth.py — DETERMINISTIC 2-D cellular-automaton (Conway's Game of
Life-class) -> RTL synth.

THE GAP THIS CLOSES
-------------------
The 2-D cellular-automaton family (Conway's "Game of Life" and its B.../S...
generalizations) is a CLOSED-FORM spec, exactly like the 1-D Wolfram Rule-N
family that `cellular_automaton_synth` already covers — but over a 2-D grid with
an 8-cell (Moore) neighbourhood instead of a 1-D 3-cell one. Once the STATED
rule pins which neighbour-counts cause BIRTH (a dead cell turning alive) and
which cause SURVIVAL (a live cell staying alive), the next state of every cell is
fully determined with zero ambiguity and no hidden oracle:

    next(cell) = 1   iff   (cell alive   and  count in SURVIVAL)
                       or   (cell dead    and  count in BIRTH)

where `count` is the number of live cells among the cell's 8 neighbours.

A blind RTL author has to, by eye: derive the packed-vector <-> (row,col) index
map, wire all 8 toroidal-wrapped neighbours (row+-1 mod H, col+-1 mod W), sum
them, AND transcribe the birth/survival sets — any one of which can flip per
round (single-shot variance: a transposed row/col map, an off-by-one wrap, a
survival count dropped). Per open-benchmark-methodology §4.2 a GENERAL no-cheat
recovery MUST be absorbed as a deterministic PROGRAM. This is that absorption: it
reads the grid geometry (HxW), the row-major packed-vector mapping, the toroidal
boundary, the 8-neighbour (Moore) neighbourhood, the birth/survival sets, and the
clk/load/data[N]/q[N] interface STRAIGHT from the prompt and emits exact RTL.

It is chip-AGNOSTIC and name-AGNOSTIC: it keys on the STATED rule (the
neighbour-count -> next-state table the prompt spells out), grid dimensions,
packed mapping and boundary — NOT on any problem name ("conwaylife", "Prob144",
"Game of Life"). Any HxW toroidal Moore CA with a row-major packed grid and a
clearly stated B/S rule synthesizes; the canonical Conway rule (B3 / S23) is just
one point in that envelope.

§4.05 NO-LEAK — EXACT, UNAMBIGUOUS 2-D CA SPECS ONLY
---------------------------------------------------
Wrong RTL is far worse than a SKIP. This synthesizer FIRES only when EVERY one of
these is unambiguously stated, and SKIPs (returns None / exit 2) otherwise:
  * a 2-D grid with explicit H x W dimensions whose product equals the packed
    vector width -> SKIP if the grid is 1-D, the dims are absent, or H*W != N;
  * an 8-cell / Moore (the 8 surrounding) neighbourhood -> SKIP on a 4-cell von
    Neumann / k-neighbour / 1-D 3-cell neighbourhood;
  * a TOROIDAL (wrap-around / cyclic / periodic) boundary -> SKIP on a zero/dead
    (finite, off-array=0) or unstated boundary, because the neighbour wiring then
    differs and we will not guess;
  * a ROW-MAJOR packed mapping that the prompt spells out (q[W-1:0] is row 0,
    next W bits row 1, ...) -> SKIP if the packing is column-major / unstated /
    a 2-D port array (not a single packed vector);
  * a stated birth set and survival set, recoverable from the prompt's
    neighbour-count -> next-state table; every count 0..8 must be unambiguously
    assigned BIRTH-or-not / SURVIVE-or-not -> SKIP on any gap or contradiction;
  * the canonical clk/load/data[N]/q[N] sequential interface with a single
    matched N, a per-clock single-step advance, and synchronous active-high load.
So it can never ship an under-determined or mis-wired guess. It is also
MUTUALLY EXCLUSIVE with the 1-D `cellular_automaton_synth`: that one rejects any
"two-dimensional" / non-3-cell / wrap-around prompt, this one rejects any 1-D /
3-cell / non-toroidal / Rule-N prompt, so at most one fires on any prompt.

USAGE
-----
    python3 conway_2d_synth.py --prompt <prompt.txt> --top TopModule [--out s.sv]

EXIT CODES
----------
    0  synthesized + emitted (exact, unambiguous 2-D CA spec)
    2  SKIP — outside the proven-faithful 2-D CA envelope
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from port_parser import parse_ports  # noqa: E402  (shared interface reader)


# --------------------------------------------------------------------------- #
# text helpers
# --------------------------------------------------------------------------- #
def _flat(prompt: str) -> str:
    """Lower-case + whitespace-collapsed view, so line-wrapped phrases (e.g.
    'two-dimensional\\ngrid') still match the text gates."""
    return re.sub(r"\s+", " ", prompt.lower())


_NUMWORD = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _as_int(tok: str) -> Optional[int]:
    tok = tok.strip().lower()
    if tok.isdigit():
        return int(tok)
    return _NUMWORD.get(tok)


# --------------------------------------------------------------------------- #
# gate 1 — 2-D family
# --------------------------------------------------------------------------- #
def _is_two_dimensional(low: str) -> bool:
    """Positive 2-D grid evidence; reject explicit 1-D wording."""
    if "one-dimensional" in low or "1-dimensional" in low or "1d grid" in low:
        return False
    return any(p in low for p in (
        "two-dimensional", "2-dimensional", "two dimensional", "2d grid",
        "2-d grid", "two-dimensional grid",
    ))


# --------------------------------------------------------------------------- #
# gate 2 — grid dimensions H x W
# --------------------------------------------------------------------------- #
def _extract_dims(low: str) -> Optional[Tuple[int, int]]:
    """Extract a single, consistent (H, W) grid dimension. Matches `16x16`,
    `16 x 16`, `16-by-16`, `16 by 16`. Returns None on absent / conflicting."""
    pairs: Set[Tuple[int, int]] = set()
    for m in re.finditer(r"\b(\d{1,4})\s*(?:x|by|-by-)\s*(\d{1,4})\b", low):
        pairs.add((int(m.group(1)), int(m.group(2))))
    # collapse identical pairs; a single distinct pair is required
    if len(pairs) != 1:
        return None
    h, w = next(iter(pairs))
    if h < 2 or w < 2:
        return None
    return (h, w)


# --------------------------------------------------------------------------- #
# gate 3 — 8-cell (Moore) neighbourhood
# --------------------------------------------------------------------------- #
def _neighbourhood_is_moore(low: str) -> bool:
    """True only for the 8-cell (Moore) neighbourhood. Reject an explicitly
    4-cell von Neumann / other-than-8 *neighbourhood-size* statement.

    NOTE: the prompt's birth/survival rule mentions counts like "2 neighbours" /
    "3 neighbours" — those are RULE COUNTS, not the neighbourhood SIZE, so they
    must NOT reject. We therefore reject only an explicit von-Neumann/4-cell
    neighbourhood declaration, and require positive 8/Moore evidence."""
    # explicit non-Moore neighbourhood declarations -> reject
    if any(b in low for b in (
        "von neumann", "von-neumann", "4-cell neighbourhood",
        "4-cell neighborhood", "four-cell neighbourhood",
        "four-cell neighborhood", "4 nearest neighbours",
        "4 nearest neighbors", "four nearest neighbours",
        "four nearest neighbors", "orthogonal neighbours only",
        "orthogonal neighbors only",
    )):
        return False
    # positive evidence: "8 neighbours" / "eight neighbours" / Moore / an
    # explicit "has 8 neighbours" corner example / "8 surrounding".
    if "moore" in low:
        return True
    if re.search(r"\b(?:8|eight)\s+neighbou?rs?\b", low):
        return True
    if re.search(r"\b(?:8|eight)\s+(?:surrounding|adjacent|nearest|cells)\b", low):
        return True
    return False


# --------------------------------------------------------------------------- #
# gate 4 — toroidal boundary
# --------------------------------------------------------------------------- #
def _boundary_is_toroidal(low: str) -> bool:
    """True only for a stated toroidal / wrap-around boundary. Reject a stated
    finite/zero/dead boundary; SKIP (handled by caller) if simply unstated."""
    # Reject a STATED finite/zero/dead boundary. Anchor "finite grid" so the
    # phrase "infinite grid" (the prompt's framing sentence) does NOT trip it.
    if re.search(r"\bfinite grid\b", low) or any(b in low for b in (
        "zero boundary", "dead boundary", "off-array are zero",
        "boundaries are zero", "boundary cells are dead",
    )):
        return False
    return any(t in low for t in (
        "toroid", "toroidal", "wrap around", "wrap-around", "wraparound",
        "wraps around", "wrap to the other side", "cyclic", "periodic boundary",
    ))


# --------------------------------------------------------------------------- #
# gate 5 — row-major packed mapping
# --------------------------------------------------------------------------- #
def _packing_is_row_major(low: str, w: int) -> bool:
    """True only when the prompt states the row-major packed mapping: the first W
    bits are row 0, the next W bits are row 1, etc. Reject column-major /
    unstated. Generic over the stated width w."""
    if "column-major" in low or "column major" in low:
        return False
    # The canonical statement: "q[W-1:0] is row 0, q[2W-1:W] is row 1, etc." We
    # look for "row 0" tied to a low bit-slice of q and an "etc."/"next" cadence,
    # OR an explicit "row-major" statement, OR the W-1..0 / 2W-1..W pattern.
    if "row-major" in low or "row major" in low:
        return True
    hi0 = w - 1
    hi1 = 2 * w - 1
    # q[15:0] is row 0  ... q[31:16] is row 1  (generic on w)
    pat0 = re.search(rf"q\[{hi0}:0\].{{0,40}}row\s*0", low)
    pat1 = re.search(rf"q\[{hi1}:{w}\].{{0,40}}row\s*1", low)
    if pat0 and pat1:
        return True
    # "each row of W cells is represented by a sub-vector" + "row 0 ... row 1 ... etc"
    if re.search(rf"each row of {w} cells", low) and re.search(r"row\s*0.{0,80}row\s*1", low):
        return True
    return False


# --------------------------------------------------------------------------- #
# gate 6 — birth / survival rule from the stated count table
# --------------------------------------------------------------------------- #
def _extract_birth_survival(low: str) -> Optional[Tuple[Set[int], Set[int]]]:
    """Recover (BIRTH, SURVIVAL) sets from the stated neighbour-count rule.

    Accepts two stated forms, both unambiguous, and SKIPs (None) on any gap:

    (A) Explicit B.../S... shorthand: "B3/S23", "B36/S23".

    (B) The canonical Conway count table the prompt spells out, classifying
        every neighbour count by its effect on the cell:
          * "<=1 neighbour -> cell becomes 0/dead"
          * "2 neighbours -> state does not change / unchanged"
          * "3 neighbours -> cell becomes 1/alive"
          * ">=4 neighbours -> cell becomes 0/dead"
        From which BIRTH = counts that turn a dead cell alive (becomes 1),
        SURVIVAL = counts that keep a live cell alive (becomes 1 OR unchanged).
        Every count 0..8 must be covered exactly once, with no contradiction.
    """
    # ---- form (A): B.../S... shorthand --------------------------------------
    m = re.search(r"\bb([0-8]+)\s*/\s*s([0-8]+)\b", low)
    if m:
        birth = {int(c) for c in m.group(1)}
        survive = {int(c) for c in m.group(2)}
        if birth and survive and birth <= set(range(9)) and survive <= set(range(9)):
            return (birth, survive)
        return None

    # ---- form (B): the count -> effect table --------------------------------
    # Classify each count 0..8 into one of: DIE (becomes 0/dead), STAY (no
    # change), BORN (becomes 1/alive). A count may be given as a single number,
    # a range "0-1", a "<=1"/"4+" bound, or a number word.
    effect: dict[int, str] = {}

    def _set(counts, eff: str) -> bool:
        for c in counts:
            if not (0 <= c <= 8):
                continue
            if c in effect and effect[c] != eff:
                return False  # contradiction
            effect[c] = eff
        return True

    # Split into clauses around the count phrases. We scan for each count phrase
    # paired with its stated effect within a short window.
    DIE = ("becomes 0", "becomes dead", "dies", "die", "turns 0",
           "set to 0", "becomes 0 (dead)", "0 (dead)")
    STAY = ("does not change", "state does not change", "unchanged",
            "stays the same", "no change", "remains")
    BORN = ("becomes 1", "becomes alive", "turns 1", "comes alive",
            "set to 1", "becomes 1 (alive)", "1 (alive)", "is born")

    def _effect_of(window: str) -> Optional[str]:
        if any(k in window for k in BORN):
            return "BORN"
        if any(k in window for k in DIE):
            return "DIE"
        if any(k in window for k in STAY):
            return "STAY"
        return None

    # Find each "<count clause> ... <effect>" by walking count-phrases.
    # Count-phrase grammar:
    #   "N neighbour(s)" | "N-M neighbour(s)" | "N+ neighbour(s)" |
    #   "N or more neighbours" | "<=N" | "at least N"
    found_any = False
    for cm in re.finditer(
        r"(\d+\s*[-–]\s*\d+|\d+\s*\+|\d+ or more|\d+ or fewer|"
        r"at least \d+|at most \d+|\d+)\s*neighbou?rs?", low
    ):
        spec = cm.group(1)
        # The effect is stated AFTER this count phrase, but MUST be read only
        # from THIS clause — the window is cut at the next clause boundary (the
        # next "neighbour(s)" mention or the next enumerated "(N)" / "(N+1)"
        # marker) so e.g. "2 neighbours: state does not change. (3) 3 neighbours:
        # cell becomes 1" does NOT leak "becomes 1" back onto the count-2 clause.
        tail = low[cm.end(): cm.end() + 120]
        cut = len(tail)
        nb = re.search(r"neighbou?rs?", tail)
        if nb:
            cut = min(cut, nb.start())
        en = re.search(r"\(\s*\d+\s*\)", tail)
        if en:
            cut = min(cut, en.start())
        tail = tail[:cut]
        eff = _effect_of(tail)
        if eff is None:
            continue
        counts: Set[int] = set()
        rng = re.match(r"(\d+)\s*[-–]\s*(\d+)", spec)
        if rng:
            counts = set(range(int(rng.group(1)), int(rng.group(2)) + 1))
        elif re.match(r"\d+\s*\+$", spec.strip()) or "or more" in spec or "at least" in spec:
            lo = int(re.search(r"\d+", spec).group(0))
            counts = set(range(lo, 9))
        elif "or fewer" in spec or "at most" in spec:
            hi = int(re.search(r"\d+", spec).group(0))
            counts = set(range(0, hi + 1))
        else:
            counts = {int(spec.strip())}
        if not _set(counts, eff):
            return None  # contradiction
        found_any = True

    if not found_any:
        return None
    # Every count 0..8 must be classified exactly once.
    if set(effect.keys()) != set(range(9)):
        return None

    birth = {c for c, e in effect.items() if e == "BORN"}
    # SURVIVAL: a LIVE cell stays alive on counts that keep it 1, i.e. BORN
    # (becomes 1, applies regardless of current) or STAY (no change keeps a live
    # cell live). DIE always kills.
    survive = {c for c, e in effect.items() if e in ("BORN", "STAY")}
    if not birth:
        return None
    return (birth, survive)


# --------------------------------------------------------------------------- #
# gate 7 — per-clock single-step advance + sync active-high load
# --------------------------------------------------------------------------- #
def _control_ok(low: str) -> bool:
    advance = ("each clock cycle" in low or "every clock cycle" in low
               or "per clock" in low or "one timestep every clock" in low
               or "one time step every clock" in low
               or "advance by one time step" in low
               or "advance by one timestep" in low)
    # The prompt may say "updated every clock cycle" / "advance by one timestep
    # every clock cycle"; require both a step notion and a per-clock notion.
    step = ("time step" in low or "timestep" in low or "advance" in low
            or "next state" in low or "next step" in low)
    return advance and step


# --------------------------------------------------------------------------- #
# synth
# --------------------------------------------------------------------------- #
def synth(prompt: str, top: str = "TopModule") -> Optional[str]:
    """Emit synthesizable RTL for an unambiguous 2-D CA spec, else None (SKIP)."""
    low = _flat(prompt)

    # Coarse family gate: must look like a 2-D cellular-automaton / Game-of-Life
    # grid spec. (We do NOT key on the name; this is generic 2-D-grid wording.)
    grid_words = ("grid of cells", "two-dimensional grid", "2-dimensional grid",
                  "cellular automaton", "cellular-automaton", "game of life",
                  "grid", "toroid")
    if not any(g in low for g in grid_words):
        return None

    if not _is_two_dimensional(low):
        return None

    dims = _extract_dims(low)
    if dims is None:
        return None
    h, w = dims

    if not _neighbourhood_is_moore(low):
        return None
    if not _boundary_is_toroidal(low):
        return None
    if not _packing_is_row_major(low, w):
        return None

    bs = _extract_birth_survival(low)
    if bs is None:
        return None
    birth, survive = bs

    if not _control_ok(low):
        return None

    # ---- interface ----------------------------------------------------------
    ins, outs = parse_ports(prompt)
    in_map = dict(ins)
    out_map = dict(outs)
    if "clk" not in in_map or "load" not in in_map:
        return None
    if "data" not in in_map or "q" not in out_map:
        return None
    if in_map["clk"] != 1 or in_map["load"] != 1:
        return None
    n = out_map["q"]
    if n != h * w:
        return None  # packed width must equal grid area
    if in_map["data"] != n:
        return None
    # exactly the four canonical ports
    if set(in_map) != {"clk", "load", "data"} or set(out_map) != {"q"}:
        return None

    return _emit(top, h, w, birth, survive)


def _emit(top: str, h: int, w: int, birth: Set[int], survive: Set[int]) -> str:
    """Emit the clocked 2-D toroidal Moore CA. Row-major packed: bit i*W+j is
    cell (row i, col j). Toroidal wrap: (i+-1) mod H, (j+-1) mod W. The
    birth/survival sets become an explicit count-membership test, so the rule is
    exactly the stated one (no Conway hard-coding)."""
    n = h * w
    msb = n - 1
    born = sorted(birth)
    surv = sorted(survive)

    L: List[str] = []
    L.append(f"module {top} (")
    L.append("    input clk,")
    L.append("    input load,")
    L.append(f"    input [{msb}:0] data,")
    L.append(f"    output reg [{msb}:0] q")
    L.append(");")
    L.append("")
    L.append(f"    // {h}x{w} toroidal Moore (8-neighbour) cellular automaton.")
    L.append(f"    // Row-major packing: cell (row i, col j) -> bit i*{w}+j.")
    L.append(f"    // BIRTH counts {{{','.join(map(str, born))}}} : dead -> alive.")
    L.append(f"    // SURVIVE counts {{{','.join(map(str, surv))}}} : alive stays alive.")
    L.append("")
    L.append(f"    reg [{msb}:0] nxt;")
    L.append("    integer i, j;")
    L.append("    integer up, dn, lf, rt;        // wrapped neighbour row/col")
    L.append("    integer cnt;                   // live neighbour count (0..8)")
    L.append("    always @(*) begin")
    L.append(f"        for (i = 0; i < {h}; i = i + 1) begin")
    L.append(f"            for (j = 0; j < {w}; j = j + 1) begin")
    L.append(f"                up = (i + {h} - 1) % {h};")
    L.append(f"                dn = (i + 1) % {h};")
    L.append(f"                lf = (j + {w} - 1) % {w};")
    L.append(f"                rt = (j + 1) % {w};")
    L.append("                cnt =")
    L.append(f"                    q[up*{w} + lf] + q[up*{w} + j] + q[up*{w} + rt] +")
    L.append(f"                    q[ i*{w} + lf]                + q[ i*{w} + rt] +")
    L.append(f"                    q[dn*{w} + lf] + q[dn*{w} + j] + q[dn*{w} + rt];")
    # birth term: cell dead AND cnt in birth
    birth_test = " || ".join(f"(cnt == {c})" for c in born)
    surv_test = " || ".join(f"(cnt == {c})" for c in surv)
    L.append(f"                if (q[i*{w} + j])")
    L.append(f"                    nxt[i*{w} + j] = ({surv_test}) ? 1'b1 : 1'b0;")
    L.append("                else")
    L.append(f"                    nxt[i*{w} + j] = ({birth_test}) ? 1'b1 : 1'b0;")
    L.append("            end")
    L.append("        end")
    L.append("    end")
    L.append("")
    L.append("    always @(posedge clk) begin")
    L.append("        if (load)")
    L.append("            q <= data;")
    L.append("        else")
    L.append("            q <= nxt;")
    L.append("    end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: outside the unambiguous 2-D cellular-automaton synth envelope",
              file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
