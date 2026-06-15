#!/usr/bin/env python3
"""spec_example_smoke_tb.py — ORGANIC #728 [P1, chip-AGNOSTIC]

EXECUTE THE PROMPT'S OWN GOLDEN EXAMPLE as a deterministic, blind-safe,
scorer-independent pre-emit gate.

WHY
  On v1.0.77 convergence forward-verify a functionally-WRONG first draft
  (a MAC that computed 0x0) passed EVERY shipped deterministic gate
  (interface / hygiene / spec-coverage / iverilog-compile / verilator) —
  yet the prompt LITERALLY carried a worked-example table
  (`op_a/op_b -> Expected Result`). No shipped gate extracted those
  example rows and RAN them, so the deterministic chain could not catch a
  first-draft functional miss and leaned on the hidden scorer.

  `spec_coverage_check.py` (#697) LISTS the requirements a prompt states.
  THIS gate EXECUTES the prompt's own worked examples: it drives the exact
  stated input values and asserts the exact stated output value, so a
  prompt-stated golden example becomes a real, blind (prompt-only),
  scorer-independent functional gate.

WHAT IT DOES
  INPUT : --prompt PROMPT  (USER station — the only source of golden rows)
          --rtl    RTL      (the authored RTL under test)
          --top    NAME     (optional; otherwise the RTL's first module)
  STEP 1: parse the RTL ports (name / direction / width) — DETERMINISTIC,
          reusing `_specrtl_common.parse_rtl_ports`.
  STEP 2: extract from the prompt the explicit worked-example rows:
            * markdown table rows  `a | b | sum` with a header row whose
              cells name actual RTL ports;
            * inline sentences  `a=3, b=4 -> sum=7`,
              `for input a=1 b=2 output is sum=3`,
              `a=3,b=4 => sum=7`;
          A row is KEPT only when EVERY left-hand `name=value` resolves to
          an RTL INPUT port AND the right-hand `name=value` resolves to an
          RTL OUTPUT port (names + values unambiguously parsed). Anything
          ambiguous is DROPPED (conservative — never invent a row).
  STEP 3: auto-generate a directed smoke testbench that, for each kept row,
          drives the inputs, waits for combinational settle, and asserts
          the output equals the stated value; compile + run with iverilog.
  STEP 4: BLOCK (exit 1) on a real extracted-example mismatch; PASS (exit 0)
          when all rows match.

§4.05 ASYMMETRY (no false-block — the hard guarantee)
  This gate only ever BLOCKs on a REAL extracted-example mismatch. It exits
  0 (NOT-APPLICABLE, never blocking) when:
    * iverilog is not on PATH (cannot run — not our place to block); OR
    * NO example rows are extractable from the prompt (there is no golden
      example to execute, so there is nothing to fail).
  A prompt that states no worked example, or whose example names/values
  don't resolve to RTL ports, is NEVER charged as a failure.

chip-AGNOSTIC: pure prompt-example extraction + structural RTL port parse +
TB generation. NO chip / vendor / SKU literal (enforced by
`programs/source_chip_agnostic_check.py .`).

CLI
    python3 spec_example_smoke_tb.py --prompt PROMPT --rtl RTL [--top NAME]
                                     [--warn] [--json OUT]

Exit codes:
    0  PASS / NOT-APPLICABLE (no rows, or iverilog absent, or --warn)
    1  BLOCK — a real extracted-example row mismatched the RTL output
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
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Reuse the canonical Spec<->RTL port parser (module name + port
# direction + width). STRUCTURAL only — same primitive spec_coverage_check
# and spec_rtl_port_fidelity_check use.
try:
    import _specrtl_common as _SRC
except ImportError:  # packaged
    from . import _specrtl_common as _SRC  # type: ignore


# ---------------------------------------------------------------------------
# Example-row extraction (prompt-only, conservative)
# ---------------------------------------------------------------------------
# A `name = value` assignment. value: hex / bin / decimal (optional sign).
_ASSIGN_RE = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*"
    r"((?:[+-]?0[xX][0-9A-Fa-f_]+)"
    r"|(?:[+-]?\d+'[sS]?[bBhHdDoO][0-9A-Fa-fxXzZ_]+)"
    r"|(?:[+-]?0[bB][01_]+)"
    r"|(?:[+-]?\d+))"
)

# Separator between the input (driven) side and the output (asserted) side
# of a worked example. Accept the common arrows + a few English phrasings.
_ARROW_RE = re.compile(
    r"(?:->|→|=>|\bgives?\b|\byields?\b|\bproduces?\b|\bbecomes?\b|"
    r"\bresults?\s+in\b|\boutput\s+is\b|\bexpected(?:\s+result)?\s*:?)",
    re.I,
)


def _norm_value(raw: str) -> Optional[int]:
    """Parse a stated example value into a Python int. Returns None if the
    value is not unambiguously parseable (conservative -> drop the row)."""
    s = raw.strip().replace("_", "")
    neg = False
    if s and s[0] in "+-":
        neg = s[0] == "-"
        s = s[1:]
    try:
        # Verilog-sized literal: <size>'<base><digits>
        m = re.match(r"^\d+'[sS]?([bBhHdDoO])([0-9A-Fa-fxXzZ]+)$", s)
        if m:
            base_ch, digits = m.group(1).lower(), m.group(2)
            if any(c in "xXzZ" for c in digits):
                return None  # x/z value — not a concrete golden number
            base = {"b": 2, "o": 8, "d": 10, "h": 16}[base_ch]
            val = int(digits, base)
        elif s.lower().startswith("0x"):
            val = int(s, 16)
        elif s.lower().startswith("0b"):
            val = int(s, 2)
        else:
            val = int(s, 10)
    except (ValueError, KeyError):
        return None
    return -val if neg else val


@dataclass
class ExampleRow:
    inputs: Dict[str, int]   # input-port name -> driven value
    output: str              # output-port name
    expected: int            # asserted value
    source: str              # 'table' / 'inline'
    raw: str                 # the source text fragment (for the report)


def _line_segments(text: str) -> List[str]:
    """Split the prompt into candidate fragments that may hold one example
    each. A fragment is bounded by line breaks AND sentence terminators so a
    multi-row prose paragraph still yields one row per sentence."""
    segs: List[str] = []
    for line in text.splitlines():
        # split on sentence/clause terminators but keep arrows intact
        for piece in re.split(r"(?<=[.;])\s+|(?<=\))\s+(?=[A-Za-z])", line):
            piece = piece.strip()
            if piece:
                segs.append(piece)
    return segs


def _resolve_row(in_assigns: List[Tuple[str, str]],
                 out_assigns: List[Tuple[str, str]],
                 in_ports: Dict[str, int],
                 out_ports: Dict[str, int],
                 source: str, raw: str) -> Optional[ExampleRow]:
    """Build an ExampleRow ONLY if every LHS name is a real INPUT port, the
    single RHS name is a real OUTPUT port, and all values parse. Else None."""
    if not in_assigns or len(out_assigns) != 1:
        return None
    inputs: Dict[str, int] = {}
    for nm, val in in_assigns:
        if nm not in in_ports:
            return None  # ambiguous / not a driven port -> drop
        v = _norm_value(val)
        if v is None:
            return None
        inputs[nm] = v
    out_nm, out_val = out_assigns[0]
    if out_nm not in out_ports:
        return None
    exp = _norm_value(out_val)
    if exp is None:
        return None
    # Guard: a name can't be both side; require disjoint sets (it already is,
    # by the in/out port classification, but keep it explicit).
    if out_nm in inputs:
        return None
    return ExampleRow(inputs=inputs, output=out_nm, expected=exp,
                      source=source, raw=raw.strip()[:200])


def _extract_inline(text: str, in_ports: Dict[str, int],
                    out_ports: Dict[str, int]) -> List[ExampleRow]:
    rows: List[ExampleRow] = []
    for seg in _line_segments(text):
        m = _ARROW_RE.search(seg)
        if not m:
            continue
        left, right = seg[: m.start()], seg[m.end():]
        in_assigns = _ASSIGN_RE.findall(left)
        out_assigns = _ASSIGN_RE.findall(right)
        row = _resolve_row(in_assigns, out_assigns, in_ports, out_ports,
                           "inline", seg)
        if row:
            rows.append(row)
    return rows


def _split_md_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_md_delim(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def _extract_table(text: str, in_ports: Dict[str, int],
                   out_ports: Dict[str, int]) -> List[ExampleRow]:
    """Markdown example tables whose header cells name RTL ports, e.g.

        | a | b | sum |
        |---|---|-----|
        | 3 | 4 | 7   |
    """
    rows: List[ExampleRow] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if "|" not in lines[i]:
            i += 1
            continue
        header = _split_md_row(lines[i])
        # need a delimiter row right after the header
        if i + 1 >= len(lines) or "|" not in lines[i + 1] \
                or not _is_md_delim(_split_md_row(lines[i + 1])):
            i += 1
            continue
        # Map each header cell (stripped of markdown emphasis) to a port.
        col_role: List[Optional[str]] = []  # 'in' | 'out' | None
        col_name: List[str] = []
        for cell in header:
            nm = re.sub(r"[*_`]", "", cell).strip()
            col_name.append(nm)
            if nm in in_ports:
                col_role.append("in")
            elif nm in out_ports:
                col_role.append("out")
            else:
                col_role.append(None)
        n_in = col_role.count("in")
        n_out = col_role.count("out")
        # require at least one input column and exactly one output column,
        # and EVERY column resolves to a port (no stray columns -> ambiguity).
        if n_in >= 1 and n_out == 1 and all(r is not None for r in col_role):
            j = i + 2
            while j < len(lines) and "|" in lines[j]:
                cells = _split_md_row(lines[j])
                if _is_md_delim(cells):
                    j += 1
                    continue
                if len(cells) == len(header):
                    in_assigns: List[Tuple[str, str]] = []
                    out_assigns: List[Tuple[str, str]] = []
                    ok = True
                    for role, nm, cell in zip(col_role, col_name, cells):
                        v = re.sub(r"[*_`]", "", cell).strip()
                        if role == "in":
                            in_assigns.append((nm, v))
                        else:
                            out_assigns.append((nm, v))
                    if ok:
                        row = _resolve_row(in_assigns, out_assigns,
                                           in_ports, out_ports, "table",
                                           lines[j])
                        if row:
                            rows.append(row)
                j += 1
            i = j
        else:
            i += 1
    return rows


def extract_example_rows(prompt_text: str,
                         in_ports: Dict[str, int],
                         out_ports: Dict[str, int]) -> List[ExampleRow]:
    """All conservatively-resolvable golden rows from the prompt."""
    rows = _extract_table(prompt_text, in_ports, out_ports)
    rows.extend(_extract_inline(prompt_text, in_ports, out_ports))
    # de-dup identical rows (same inputs + output + expected)
    seen = set()
    uniq: List[ExampleRow] = []
    for r in rows:
        key = (tuple(sorted(r.inputs.items())), r.output, r.expected)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


# ---------------------------------------------------------------------------
# Testbench generation
# ---------------------------------------------------------------------------
def _mask(width: int) -> str:
    """Verilog-safe expected value masked to the port width (so a stated
    sum=7 on a 9-bit port compares against the low 9 bits)."""
    return str(width)


def build_testbench(top: str, rows: List[ExampleRow],
                    in_ports: Dict[str, int],
                    out_ports: Dict[str, int]) -> str:
    """Emit a self-checking directed TB string. Drives each row's inputs,
    settles combinationally (#1), and asserts the masked output."""
    driven = sorted({nm for r in rows for nm in r.inputs})
    checked = sorted({r.output for r in rows})
    lines: List[str] = []
    lines.append("`timescale 1ns/1ps")
    lines.append("module tb_spec_example_smoke;")
    lines.append("  integer __errors = 0;")
    for nm in driven:
        w = in_ports.get(nm, 1)
        rng = "" if w <= 1 else f"[{w-1}:0] "
        lines.append(f"  reg {rng}{nm};")
    for nm in checked:
        w = out_ports.get(nm, 1)
        rng = "" if w <= 1 else f"[{w-1}:0] "
        lines.append(f"  wire {rng}{nm};")
    # DUT instantiation — named port connections (only driven + checked).
    conns = ", ".join(f".{nm}({nm})" for nm in (driven + checked))
    lines.append(f"  {top} dut({conns});")
    lines.append("  initial begin")
    for idx, r in enumerate(rows):
        for nm in driven:
            if nm in r.inputs:
                lines.append(f"    {nm} = {r.inputs[nm]};")
        lines.append("    #1;")
        ow = out_ports.get(r.output, 1)
        # mask the expected value to the output width
        exp_masked = r.expected & ((1 << ow) - 1)
        in_str = ", ".join(f"{nm}={r.inputs[nm]}" for nm in sorted(r.inputs))
        lines.append(
            f"    if ({r.output} !== {ow}'d{exp_masked}) begin")
        lines.append(
            f'      $display("SPEC_EXAMPLE_FAIL row {idx}: {in_str} -> '
            f'expected {r.output}={exp_masked} got %0d (0x%0h)", '
            f"{r.output}, {r.output});")
        lines.append("      __errors = __errors + 1;")
        lines.append("    end else begin")
        lines.append(
            f'      $display("SPEC_EXAMPLE_PASS row {idx}: {in_str} -> '
            f'{r.output}={exp_masked}");')
        lines.append("    end")
    lines.append("    if (__errors != 0)")
    lines.append('      $display("SPEC_EXAMPLE_SMOKE_RESULT=FAIL errors=%0d", __errors);')
    lines.append("    else")
    lines.append('      $display("SPEC_EXAMPLE_SMOKE_RESULT=PASS");')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
@dataclass
class Result:
    verdict: str             # PASS / BLOCK / NOT_APPLICABLE
    reason: str
    rows: List[dict]
    sim_log: str = ""


def _run(prompt: Path, rtl: Path, top: Optional[str],
         warn: bool) -> Result:
    prompt_text = prompt.read_text(errors="replace")
    rtl_text = rtl.read_text(errors="replace")

    mod_name, ports = _SRC.parse_rtl_ports(rtl_text, top)
    chosen_top = top or mod_name
    in_ports = {p.name: max(1, p.width) for p in ports if p.direction == "input"}
    out_ports = {p.name: max(1, p.width) for p in ports if p.direction == "output"}

    rows = extract_example_rows(prompt_text, in_ports, out_ports)
    rows_json = [asdict(r) for r in rows]

    if not rows:
        return Result("NOT_APPLICABLE",
                      "no extractable golden example rows in the prompt "
                      "(no input=val ... -> output=val row whose names "
                      "resolve to RTL ports) — nothing to execute",
                      rows_json)

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return Result("NOT_APPLICABLE",
                      "iverilog/vvp not on PATH — cannot run the example "
                      f"smoke TB ({len(rows)} row(s) were extractable)",
                      rows_json)

    tb_text = build_testbench(chosen_top, rows, in_ports, out_ports)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        tb_path = tdp / "tb_spec_example_smoke.v"
        rtl_copy = tdp / ("dut" + (rtl.suffix or ".v"))
        out_vvp = tdp / "smoke.vvp"
        tb_path.write_text(tb_text)
        rtl_copy.write_text(rtl_text)
        comp = subprocess.run(
            ["iverilog", "-g2012", "-o", str(out_vvp),
             str(tb_path), str(rtl_copy)],
            capture_output=True, text=True)
        if comp.returncode != 0:
            # A genuine compile failure of the example TB+RTL is a real
            # mismatch between the stated interface and the RTL -> BLOCK
            # (unless --warn). The compile log is the evidence.
            log = (comp.stdout + comp.stderr).strip()
            verdict = "BLOCK" if not warn else "PASS"
            return Result(verdict,
                          "example smoke TB failed to compile against the RTL "
                          "(stated example ports do not connect) — see sim_log",
                          rows_json, sim_log=log)
        sim = subprocess.run(["vvp", str(out_vvp)],
                             capture_output=True, text=True)
        log = (sim.stdout + sim.stderr).strip()

    if "SPEC_EXAMPLE_SMOKE_RESULT=PASS" in log:
        return Result("PASS",
                      f"all {len(rows)} prompt golden example row(s) match "
                      "the RTL output", rows_json, sim_log=log)
    # any FAIL marker (or missing PASS marker) -> mismatch
    verdict = "BLOCK" if not warn else "PASS"
    return Result(verdict,
                  "at least one prompt golden example row mismatched the RTL "
                  "output (functionally-wrong RTL) — see sim_log",
                  rows_json, sim_log=log)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Execute the prompt's own golden example rows as a "
                    "directed smoke TB (blind, scorer-independent).")
    ap.add_argument("--prompt", required=True,
                    help="USER prompt text file (the ONLY source of golden rows)")
    ap.add_argument("--rtl", required=True, help="authored RTL under test")
    ap.add_argument("--top", default=None,
                    help="top module name (default: first module in the RTL)")
    ap.add_argument("--warn", action="store_true",
                    help="WARN-only: report a mismatch but exit 0")
    ap.add_argument("--json", default=None, help="write the result JSON here")
    args = ap.parse_args(argv)

    prompt = Path(args.prompt)
    rtl = Path(args.rtl)
    if not prompt.is_file():
        print(f"[spec_example_smoke_tb] ERROR: prompt not found: {prompt}",
              file=sys.stderr)
        return 2
    if not rtl.is_file():
        print(f"[spec_example_smoke_tb] ERROR: rtl not found: {rtl}",
              file=sys.stderr)
        return 2

    res = _run(prompt, rtl, args.top, args.warn)

    if args.json:
        try:
            Path(args.json).write_text(json.dumps(asdict(res), indent=2))
        except OSError as e:
            print(f"[spec_example_smoke_tb] WARN: could not write json: {e}",
                  file=sys.stderr)

    tag = {"PASS": "PASS", "BLOCK": "BLOCK",
           "NOT_APPLICABLE": "NOT-APPLICABLE"}[res.verdict]
    print(f"[spec_example_smoke_tb] {tag}: {res.reason}")
    if res.rows:
        print(f"[spec_example_smoke_tb] extracted {len(res.rows)} golden "
              f"example row(s):")
        for r in res.rows:
            ins = ", ".join(f"{k}={v}" for k, v in sorted(r["inputs"].items()))
            print(f"    [{r['source']}] {ins} -> {r['output']}={r['expected']}")
    if res.sim_log:
        # echo only the result lines, not the whole dump
        for ln in res.sim_log.splitlines():
            if "SPEC_EXAMPLE" in ln or "error" in ln.lower():
                print(f"    | {ln}")

    return 1 if res.verdict == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
