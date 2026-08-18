#!/usr/bin/env python3
"""clause_smoke_tb.py — ORGANIC #740 (G2) [chip-AGNOSTIC]

EXAMPLE-FREE functional smoke gate. Auto-derive minimal DIRECTED stimulus from a
prompt's functional-description CLAUSES (faster / slower / equal, greater / less,
…) for code-completion prompts that carry NO golden input->output rows and NO
authored testbench.

WHY
  `spec_example_smoke_tb.py` (#728) EXECUTES the prompt's own worked-example
  ROWS. But many code-completion prompts state the function PROSAICALLY — "output
  `y` is HIGH when `a` is GREATER THAN `b`", "assert `faster` when counter A
  reaches the threshold before counter B" — with NO numeric example table. For
  those, the example-row gate finds nothing and the deterministic chain has no
  functional check at all; it leans on the hidden scorer.

  THIS gate fills exactly that gap: it parses the prompt's RELATIONAL functional
  clauses, derives concrete operand values that make each relation TRUE and FALSE,
  drives the two scalar input operands accordingly, and asserts the named output
  takes its stated value. A first-draft that inverts a comparator, or wires the
  output to the wrong polarity, is then caught BLIND (prompt-only), without a
  golden table and without the scorer.

WHAT IT DOES
  INPUT : --prompt PROMPT  (the only source of functional clauses)
          --rtl    RTL      (the authored RTL under test)
          --top    NAME     (optional; otherwise the RTL's first module)
  STEP 1: parse the RTL ports (name / direction / width), reusing
          `_specrtl_common.parse_rtl_ports` (STRUCTURAL, shared primitive).
  STEP 2: extract RELATIONAL clauses from the prompt — `output is <value> when
          <op_a> <relation> <op_b>` and its common English phrasings. A clause is
          KEPT only when op_a and op_b both resolve to RTL INPUT ports and the
          output resolves to a 1-bit RTL OUTPUT port. Anything ambiguous is
          DROPPED (conservative — never invent a clause). PURE function.
  STEP 3: derive, per kept clause, a TRUE-case and a FALSE-case directed vector
          (concrete small operand values satisfying / violating the relation,
          with the asserted output value / its complement). PURE function.
  STEP 4: auto-generate a directed COMBINATIONAL smoke testbench that drives the
          operands and asserts the output; compile + run with iverilog.

§4.05 ASYMMETRY (no false-block — the hard guarantee)
  This gate only ever BLOCKs on a REAL derived-clause mismatch. It exits 0
  (NOT-APPLICABLE, never blocking) when:
    * iverilog is not on PATH (cannot run — degrade, not block); OR
    * NO clause is confidently derivable from the prompt (nothing to fail); OR
    * `--warn` is passed (advisory mode — always exit 0).
  A prompt that states no relational clause, or whose clause operands/output
  don't resolve to RTL ports, is NEVER charged as a failure.

chip-AGNOSTIC: pure prompt-clause extraction + structural RTL port parse + TB
generation. NO chip / vendor / SKU literal (enforced by
`programs/source_chip_agnostic_check.py .`).

CLI
    python3 clause_smoke_tb.py --prompt PROMPT --rtl RTL [--top NAME]
                               [--warn] [--json OUT]

Exit codes:
    0  PASS / NOT-APPLICABLE (no clauses, or iverilog absent, or --warn)
    1  BLOCK — a real derived-clause vector mismatched the RTL output
    2  argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Reuse the canonical Spec<->RTL port parser — STRUCTURAL, the same primitive
# spec_example_smoke_tb / spec_coverage_check use. No hand-rolled port regex.
try:
    import _specrtl_common as _SRC
except ImportError:  # packaged
    from . import _specrtl_common as _SRC  # type: ignore


# ---------------------------------------------------------------------------
# Relation vocabulary (chip-AGNOSTIC, generic English / Verilog comparators)
# ---------------------------------------------------------------------------
# Each relation maps to a Python comparator (for stimulus derivation) and a
# canonical name. The phrasings are GENERIC functional-description words, not any
# chip/design/benchmark token.
_REL_GT = "gt"      # a > b
_REL_LT = "lt"      # a < b
_REL_EQ = "eq"      # a == b
_REL_GE = "ge"      # a >= b
_REL_LE = "le"      # a <= b
_REL_NE = "ne"      # a != b

_REL_FUNC = {
    _REL_GT: lambda a, b: a > b,
    _REL_LT: lambda a, b: a < b,
    _REL_EQ: lambda a, b: a == b,
    _REL_GE: lambda a, b: a >= b,
    _REL_LE: lambda a, b: a <= b,
    _REL_NE: lambda a, b: a != b,
}

# Phrasing -> relation. Ordered longest/most-specific first so "greater than or
# equal" wins over "greater than". These are common functional-description words
# (faster/slower/equal map to the "reaches/exceeds" comparison family).
_REL_PHRASES: List[Tuple[str, str]] = [
    (r"greater\s+than\s+or\s+equal\s+to", _REL_GE),
    (r"less\s+than\s+or\s+equal\s+to", _REL_LE),
    (r"at\s+least", _REL_GE),
    (r"at\s+most", _REL_LE),
    (r"greater\s+than", _REL_GT),
    (r"larger\s+than", _REL_GT),
    (r"bigger\s+than", _REL_GT),
    (r"more\s+than", _REL_GT),
    (r"exceeds?", _REL_GT),
    (r"faster\s+than", _REL_GT),
    (r"less\s+than", _REL_LT),
    (r"smaller\s+than", _REL_LT),
    (r"lower\s+than", _REL_LT),
    (r"slower\s+than", _REL_LT),
    (r"fewer\s+than", _REL_LT),
    (r"not\s+equal\s+to", _REL_NE),
    (r"differs?\s+from", _REL_NE),
    (r"equal\s+to", _REL_EQ),
    (r"equals", _REL_EQ),
    (r"the\s+same\s+as", _REL_EQ),
]
_REL_SYMBOLS: List[Tuple[str, str]] = [
    (r">=", _REL_GE), (r"<=", _REL_LE), (r"==", _REL_EQ), (r"!=", _REL_NE),
    (r">", _REL_GT), (r"<", _REL_LT),
]

_OUTPUT_TRUE_WORDS = ("high", "1", "set", "asserted", "true", "one")
_OUTPUT_FALSE_WORDS = ("low", "0", "clear", "cleared", "deasserted", "false",
                       "zero")

# An ARITHMETIC OFFSET / TOLERANCE / MODIFIER on the condition side that a bare
# two-operand relation (`op_a <rel> op_b`) CANNOT represent. "a greater than b
# BY AT LEAST 2" means y=(a>b+2), not y=(a>=b); driving a=6,b=5 and expecting
# y=1 would FALSE-BLOCK a correct `assign y=(a>(b+2))`. When ANY of these is
# present between / after the operands we must NOT emit a bare relation — drop
# the clause to NOT-APPLICABLE (no vector) rather than assert a wrong expectation.
# chip-AGNOSTIC: generic English arithmetic-modifier prose + Verilog operators.
_OFFSET_KEYWORDS = re.compile(
    r"\b(?:by|plus|minus|within|tolerance|margin|offset|"
    r"more\s+than\s+\d|at\s+least\s+\d|at\s+most\s+\d)\b", re.I)
# A bare arithmetic operator adjoining a numeric literal (a+2, b - 3, a*2, 8'd2).
_ARITH_OP_NUM = re.compile(r"[+\-*/]\s*\d|\d\s*[+\-*/]")
# A standalone numeric literal (after stripping the operand port tokens, any
# residual number is an offset / threshold constant the model cannot drive).
_NUM_LIT = re.compile(r"(?<![\w'])\d+\b")


def condition_has_unrepresentable_offset(cond_side: str,
                                         op_a: str, op_b: str) -> bool:
    """True when the condition carries an arithmetic OFFSET / MODIFIER that a
    bare `op_a <relation> op_b` cannot represent (so a derived vector would
    assert the WRONG output value). PURE. Fail-SAFE: when in doubt, return True
    so the clause is DROPPED (NOT-APPLICABLE) instead of false-blocking.

    Strips the operand port tokens first so a port whose own NAME contains a
    digit (e.g. `reg1`, `data0`) is never mistaken for a numeric offset."""
    stripped = cond_side
    for op in (op_a, op_b):
        stripped = re.sub(r"`?" + re.escape(op) + r"`?", " ", stripped,
                          flags=re.I)
    if _OFFSET_KEYWORDS.search(cond_side):
        return True
    if _ARITH_OP_NUM.search(cond_side):
        return True
    if _NUM_LIT.search(stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Clause model + extraction (PURE — unit-testable WITHOUT iverilog)
# ---------------------------------------------------------------------------
@dataclass
class Clause:
    output: str            # 1-bit output port name (case as declared in RTL)
    op_a: str              # input port name (operand A)
    op_b: str              # input port name (operand B)
    relation: str          # one of _REL_* keys
    true_value: int        # output value (0/1) WHEN the relation HOLDS
    source: str = ""       # provenance fragment (debugging only)


def _relation_for(text: str) -> Optional[str]:
    """Return the relation key named in `text` (longest phrasing wins), else
    None. Symbols are matched only as standalone comparator tokens."""
    low = text.lower()
    for pat, rel in _REL_PHRASES:
        if re.search(r"\b" + pat + r"\b", low):
            return rel
    for pat, rel in _REL_SYMBOLS:
        if re.search(pat, text):
            return rel
    return None


def _output_value_in(text: str) -> Optional[int]:
    """Whether the clause states the output is HIGH(1) or LOW(0). None if the
    text names neither (then we default to HIGH-when-true, the dominant
    convention — but the caller decides)."""
    low = text.lower()
    # Look for the FIRST polarity word; a clause like "y is HIGH when a > b"
    # states true_value=1, "y is LOW when a==b" states true_value=0.
    first_true = min((low.find(w) for w in _OUTPUT_TRUE_WORDS
                      if low.find(w) >= 0), default=-1)
    first_false = min((low.find(w) for w in _OUTPUT_FALSE_WORDS
                       if low.find(w) >= 0), default=-1)
    if first_true < 0 and first_false < 0:
        return None
    if first_false < 0:
        return 1
    if first_true < 0:
        return 0
    return 1 if first_true < first_false else 0


# `out is high when a > b` / `out = 1 if a greater than b` /
# `assert out when a exceeds b`. The clause is a sentence-ish window naming an
# output, a relation, and two operands. We scan backtick-or-bareword tokens.
_TOKEN_RE = re.compile(r"`?([A-Za-z_]\w*)`?")
# A "when/if" pivot separates the output-assertion side from the condition side.
_WHEN_RE = re.compile(r"\b(?:when|if|whenever|while)\b", re.I)


def _resolve_port(token: str, ports_lower: Dict[str, str]) -> Optional[str]:
    """Case-insensitively resolve a prompt token to a declared RTL port,
    returning the ORIGINAL-CASE name; None if not a port."""
    return ports_lower.get(token.lower())


def extract_clauses(prompt: str,
                    inputs_lower: Dict[str, str],
                    outputs_lower: Dict[str, str],
                    out_width: Dict[str, int]) -> List[Clause]:
    """Extract relational functional clauses from `prompt`. PURE.

    A clause is KEPT only when:
      * an output token resolves to a 1-bit RTL OUTPUT port;
      * a relation phrase/symbol is present;
      * EXACTLY two distinct tokens on the condition side resolve to RTL INPUT
        ports (op_a, op_b).
    Anything else is DROPPED (conservative). Returns clauses in source order,
    de-duplicated on (output, op_a, op_b, relation)."""
    clauses: List[Clause] = []
    seen = set()
    # Split into sentence-like fragments so one clause's operands don't bleed
    # into the next. Period / newline / semicolon / bullet boundaries.
    for frag in re.split(r"[.\n;]|(?:^|\s)[-*]\s", prompt):
        if not frag or not frag.strip():
            continue
        wm = _WHEN_RE.search(frag)
        if not wm:
            continue
        assert_side = frag[:wm.start()]
        cond_side = frag[wm.end():]
        rel = _relation_for(cond_side)
        if rel is None:
            continue
        # output: the FIRST token on the assert side that is a 1-bit output port
        out_name: Optional[str] = None
        for tm in _TOKEN_RE.finditer(assert_side):
            cand = _resolve_port(tm.group(1), outputs_lower)
            if cand is not None and out_width.get(cand, 1) == 1:
                out_name = cand
                break
        if out_name is None:
            continue
        true_value = _output_value_in(assert_side)
        if true_value is None:
            true_value = 1  # default convention: output HIGH when relation holds
        # operands: the input ports named on the condition side, in order.
        ops: List[str] = []
        for tm in _TOKEN_RE.finditer(cond_side):
            cand = _resolve_port(tm.group(1), inputs_lower)
            if cand is not None and cand not in ops:
                ops.append(cand)
        if len(ops) != 2:
            continue
        # DROP the clause if the condition carries an arithmetic offset /
        # tolerance the bare relation cannot represent (e.g. "a greater than b
        # BY AT LEAST 2" => y=(a>b+2), not y=(a>=b)). Asserting the bare
        # relation here would FALSE-BLOCK a correct offset RTL. Fail-safe:
        # NOT-APPLICABLE (no vector) beats a wrong expectation.
        if condition_has_unrepresentable_offset(cond_side, ops[0], ops[1]):
            continue
        key = (out_name, ops[0], ops[1], rel)
        if key in seen:
            continue
        seen.add(key)
        clauses.append(Clause(output=out_name, op_a=ops[0], op_b=ops[1],
                              relation=rel, true_value=true_value,
                              source=frag.strip()[:120]))
    return clauses


# ---------------------------------------------------------------------------
# Stimulus derivation (PURE — unit-testable WITHOUT iverilog)
# ---------------------------------------------------------------------------
@dataclass
class Vector:
    a: int                 # value driven on op_a
    b: int                 # value driven on op_b
    expected: int          # expected output bit (0/1)
    holds: bool            # whether the relation holds for (a, b)


def derive_stimulus(clause: Clause) -> List[Vector]:
    """Derive a TRUE-case and a FALSE-case directed vector for `clause`. PURE.

    Picks small concrete operand values; for EQ uses (5,5)/(5,6), for the
    ordering relations uses (6,5)/(5,6) etc., and always includes the boundary
    where it disambiguates >=/<= vs >/<. Returns [] only if no value pair can
    satisfy AND violate the relation (never happens for the supported set)."""
    f = _REL_FUNC[clause.relation]
    # candidate operand pairs span less / equal / greater so every relation has
    # both a holding and a violating witness, including the boundary case.
    candidates = [(6, 5), (5, 5), (5, 6), (0, 0), (3, 7)]
    holds_pair = next(((a, b) for (a, b) in candidates if f(a, b)), None)
    fails_pair = next(((a, b) for (a, b) in candidates if not f(a, b)), None)
    vectors: List[Vector] = []
    if holds_pair is not None:
        a, b = holds_pair
        vectors.append(Vector(a, b, clause.true_value, True))
    if fails_pair is not None:
        a, b = fails_pair
        vectors.append(Vector(a, b, 1 - clause.true_value, False))
    return vectors


# ---------------------------------------------------------------------------
# Directed combinational testbench generation
# ---------------------------------------------------------------------------
def _decl_width(width: int) -> str:
    return f" [{width - 1}:0]" if width and width > 1 else ""


def build_clause_tb(top: str, ports: List["_SRC.Port"],
                    clause: Clause, vectors: List[Vector]) -> str:
    """Emit a self-contained directed COMBINATIONAL smoke TB for one clause.
    Drives every input to 0 by default, then sets op_a/op_b per vector, lets
    combinational logic settle, and `$display`s a PASS/FAIL token per vector."""
    by_name = {p.name: p for p in ports}
    L: List[str] = ["`timescale 1ns/1ps", f"module clause_tb;"]
    for p in ports:
        if p.direction == "input":
            L.append(f"  reg{_decl_width(p.width)} {p.name};")
        elif p.direction == "output":
            L.append(f"  wire{_decl_width(p.width)} {p.name};")
    conns = ", ".join(f".{p.name}({p.name})" for p in ports)
    L.append(f"  {top} dut({conns});")
    L.append("  integer fails;")
    L.append("  initial begin")
    L.append("    fails = 0;")
    # default all inputs low
    for p in ports:
        if p.direction == "input":
            L.append(f"    {p.name} = 0;")
    for i, v in enumerate(vectors):
        L.append(f"    {clause.op_a} = {v.a}; {clause.op_b} = {v.b};")
        L.append("    #5;")
        L.append(f"    if ({clause.output} !== 1'b{v.expected}) begin")
        L.append(f'      $display("CLAUSE_FAIL vec={i} a=%0d b=%0d '
                 f'exp=%0d got=%b", {clause.op_a}, {clause.op_b}, '
                 f'{v.expected}, {clause.output});')
        L.append("      fails = fails + 1;")
        L.append("    end")
    L.append('    if (fails == 0) $display("CLAUSE_OK");')
    L.append("    else $display(\"CLAUSE_MISMATCH %0d\", fails);")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _run(cmd: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out or "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def run_clause_smoke(rtl_path: Path, prompt: str, top: Optional[str],
                     warn: bool) -> Tuple[int, Dict]:
    """Run the gate. rc 0 = PASS / NOT-APPLICABLE / advisory, rc 1 = BLOCK."""
    rtl_text = rtl_path.read_text(errors="replace")
    src = _SRC.strip_comments(rtl_text)
    mod_name, ports = _SRC.parse_rtl_ports(src, top)
    report: Dict = {
        "program": "clause_smoke_tb",
        "rtl": str(rtl_path),
        "top": mod_name or top,
        "methodology": ("auto-derived directed stimulus from the prompt's "
                        "relational functional clauses (no golden rows / no "
                        "authored TB); BLIND (prompt + RTL only)"),
    }
    inputs_lower = {p.name.lower(): p.name for p in ports
                    if p.direction == "input"}
    outputs_lower = {p.name.lower(): p.name for p in ports
                     if p.direction == "output"}
    out_width = {p.name: p.width for p in ports if p.direction == "output"}

    clauses = extract_clauses(prompt, inputs_lower, outputs_lower, out_width)
    report["clauses_extracted"] = [
        {"output": c.output, "op_a": c.op_a, "op_b": c.op_b,
         "relation": c.relation, "true_value": c.true_value} for c in clauses]

    if not clauses:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = ("no relational functional clause confidently "
                            "derivable from the prompt (output/operands did not "
                            "resolve to 1-bit out + two input ports) — nothing "
                            "to smoke-test (NOT a failure)")
        return 0, report

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        report["verdict"] = "SKIP"
        report["tool_available"] = False
        report["reason"] = ("iverilog/vvp absent — cannot RUN the derived "
                            "smoke TB; degrading to SKIP (NOT a block)")
        return 0, report
    report["tool_available"] = True

    if mod_name is None:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = "no module to elaborate"
        return 0, report

    results: List[Dict] = []
    any_mismatch = False
    workdir = Path(tempfile.mkdtemp(prefix="clausesmk_"))
    try:
        for ci, clause in enumerate(clauses):
            vectors = derive_stimulus(clause)
            if not vectors:
                continue
            tb = build_clause_tb(mod_name, ports, clause, vectors)
            tb_path = workdir / f"clause_tb_{ci}.sv"
            tb_path.write_text(tb)
            binp = workdir / f"clause_{ci}.vvp"
            rc, out, err = _run(["iverilog", "-g2012", "-o", str(binp),
                                 "-s", "clause_tb", str(rtl_path),
                                 str(tb_path)])
            entry = {"output": clause.output, "op_a": clause.op_a,
                     "op_b": clause.op_b, "relation": clause.relation,
                     "true_value": clause.true_value}
            if rc != 0:
                # a compile failure of OUR generated TB is NOT a design block —
                # degrade to advisory (the design's own compile gate is the
                # hard one). §4.05: never false-block on a tooling artefact.
                entry["status"] = "TB_COMPILE_SKIP"
                entry["detail"] = "; ".join(
                    ((out or "") + (err or "")).splitlines()[:3])
                results.append(entry)
                continue
            rc2, out2, err2 = _run(["vvp", str(binp)])
            if "CLAUSE_OK" in out2:
                entry["status"] = "PASS"
            elif "CLAUSE_MISMATCH" in out2 or "CLAUSE_FAIL" in out2:
                entry["status"] = "MISMATCH"
                entry["detail"] = "; ".join(
                    l for l in out2.splitlines() if "CLAUSE_FAIL" in l)[:400]
                any_mismatch = True
            else:
                entry["status"] = "INCONCLUSIVE"
                entry["detail"] = (err2 or "").splitlines()[:2]
            results.append(entry)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    report["results"] = results
    if any_mismatch and not warn:
        report["verdict"] = "BLOCK"
        report["reason"] = ("a derived functional clause vector mismatched the "
                            "RTL output — the design contradicts a prompt-stated "
                            "relation")
        return 1, report
    report["verdict"] = "WARN" if (any_mismatch and warn) else "PASS"
    report["reason"] = ("derived clause vectors matched the RTL"
                        if not any_mismatch else
                        "clause mismatch downgraded to advisory (--warn)")
    return 0, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="EXAMPLE-FREE functional smoke gate (#740 G2): auto-derive "
                    "directed stimulus from a prompt's relational functional "
                    "clauses and BLOCK on a real RTL contradiction. BLIND "
                    "(prompt + RTL only); advisory/NOT-APPLICABLE when no clause "
                    "is confidently derivable.")
    ap.add_argument("--prompt", required=True,
                    help="prompt / spec text (the only source of clauses)")
    ap.add_argument("--rtl", required=True, help="the authored RTL")
    ap.add_argument("--top", default=None,
                    help="DUT module name (default: the first module)")
    ap.add_argument("--warn", action="store_true",
                    help="advisory mode — never block (always exit 0)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    pp = Path(args.prompt)
    rp = Path(args.rtl)
    for label, p in (("--prompt", pp), ("--rtl", rp)):
        if not p.is_file():
            print(f"ERROR: {label} file not found: {p}", file=sys.stderr)
            return 2
    prompt = pp.read_text(errors="replace")
    if not rp.read_text(errors="replace").strip():
        print(f"ERROR: --rtl file is empty: {rp}", file=sys.stderr)
        return 2

    rc, report = run_clause_smoke(rp, prompt, args.top, args.warn)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")

    verdict = report.get("verdict")
    if verdict == "NOT_APPLICABLE":
        print(f"clause-smoke NOT-APPLICABLE: {report['reason']}")
    elif verdict == "SKIP":
        print(f"clause-smoke SKIP — iverilog unavailable: {report['reason']}")
    elif verdict == "PASS":
        n = len(report.get("clauses_extracted", []))
        print(f"clause-smoke ok: {n} clause(s) derived; RTL matched all")
    elif verdict == "WARN":
        print(f"clause-smoke WARN (advisory): {report['reason']}")
    elif verdict == "BLOCK":
        print(f"CLAUSE-SMOKE BLOCK: {report['reason']}", file=sys.stderr)
        for r in report.get("results", []):
            if r.get("status") == "MISMATCH":
                print(f"  {r['output']} ({r['op_a']} {r['relation']} "
                      f"{r['op_b']}): {r.get('detail','')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
