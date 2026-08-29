#!/usr/bin/env python3
"""BIDIRECTIONAL control for arith_declaration_emit `=` separator.

Run against ANY copy of arith_declaration_emit.py:

    python3 test_arith_declaration_emit_equals_separator.py <path-to-program>

Expected:
  * byte-identical PRE-FIX file  -> exit 1, prints "NEGATIVE CONTROL HELD"
  * POST-FIX file                -> exit 0, prints "ALL 3 CASES PASS"

Three cases, all synthetic. Chip name `qzr` and algorithm value
`booth_radix4_wallace` appear in no real design in this repo, and the
frequencies / widths (width 13) are deliberately unlike spm's, so a fix that
hardcodes a literal cannot pass.

  CASE A (the defect)      header spells the field `algorithm = <v>`
                           -> PRE-FIX: FAIL_CLOSED   POST-FIX: emits <v>
  CASE B (reverse, must    header spells it `Algorithm: <v>` (the form that
          STILL pass)      already worked)
                           -> PRE-FIX and POST-FIX both emit <v>, IDENTICALLY
  CASE C (reverse, must    header declares no algorithm at all
          STILL fail)      -> PRE-FIX and POST-FIX both FAIL_CLOSED rc==1,
                              banner on stderr, NO file written

CASE B and CASE C are what stop the fix from degenerating into "accept
anything": B proves the pre-existing separator is untouched, C proves the
fail-closed refusal is still reachable.

HOW THIS FILE IS EXECUTED. It is named `test_*.py` and pytest collects ZERO
tests from it, because it is a CLI parameterised by the program path and not a
pytest module — that is deliberate, and it is the only shape in which the
negative half of the contract above can be driven. It is not dead:
`test_bidirectional_controls_are_executed.py` runs it BOTH ways on every suite
run (against the shipped program, and against a copy with the fixed construct
removed), and lists it in that file's `DRIVEN` set, which
`test_no_test_file_collects_zero_tests` re-checks. Delete the entry there and
this file becomes an undeclared zero-collect module, which that test fails on.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BANNER = "arith_declaration_emit: FAIL_CLOSED"

_RTL_HEAD = """\
//==========================================================================
// qzr — {width}-bit serial-parallel product engine (synthetic test fixture)
//--------------------------------------------------------------------------
// DECLARED CHOICES:
//   bit_order        = MSB_first
//   reset_polarity   = active_high, SYNCHRONOUS
{alg_line}\
//--------------------------------------------------------------------------
module qzr #(parameter size = {width}) (
    input wire clk, input wire rst,
    input wire [size-1:0] a, input wire b, output reg q
);
    always @(posedge clk) begin
        if (rst) q <= 1'b0;
        else     q <= b ^ a[0];
    end
endmodule
"""


def _make_run_dir(root: Path, alg_line: str) -> Path:
    run = root
    rtl = run / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "qzr.v").write_text(_RTL_HEAD.format(width=13, alg_line=alg_line))

    docs = run / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps(
        {"doc_class": "frs", "ic_name": "qzr",
         "notes": ["operands are signed_2c"]}))

    scale = run / "_verify_scale"
    scale.mkdir(parents=True, exist_ok=True)
    (scale / "REPORT.md").write_text("# qzr scale\n\nCALIBRATED_LATENCY: 7\n")
    return run


def _run(program: Path, run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(program), str(run_dir)],
                          capture_output=True, text=True)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    program = Path(sys.argv[1]).resolve()
    if not program.is_file():
        print(f"ERROR: no such program: {program}", file=sys.stderr)
        return 2

    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="arith_decl_ctl_"))
    try:
        # ---- CASE A: the `=` separator (the defect) --------------------
        a_dir = _make_run_dir(tmp / "case_a",
                              "//   multiplier_algorithm = booth_radix4_wallace\n")
        a = _run(program, a_dir)
        a_file = a_dir / "plugin_output" / "declaration.json"
        if a.returncode != 0 or not a_file.exists():
            failures.append(
                "CASE A: `algorithm = <v>` was NOT derived — program refused "
                f"(rc={a.returncode}). stderr:\n{a.stderr.strip()}")
        else:
            got = json.loads(a_file.read_text()).get("multiplier_algorithm")
            if got != "booth_radix4_wallace":
                failures.append(
                    f"CASE A: derived multiplier_algorithm={got!r}, "
                    "expected 'booth_radix4_wallace'")

        # ---- CASE B (reverse): the `:` separator must STILL work -------
        b_dir = _make_run_dir(tmp / "case_b",
                              "//   Algorithm: booth radix4 wallace\n")
        b = _run(program, b_dir)
        b_file = b_dir / "plugin_output" / "declaration.json"
        if b.returncode != 0 or not b_file.exists():
            failures.append(
                "CASE B (reverse): the pre-existing `Algorithm:` form "
                f"REGRESSED — rc={b.returncode}. stderr:\n{b.stderr.strip()}")
        else:
            got = json.loads(b_file.read_text()).get("multiplier_algorithm")
            if got != "booth_radix4_wallace":
                failures.append(
                    f"CASE B (reverse): `Algorithm:` form now derives {got!r}, "
                    "expected 'booth_radix4_wallace' — the fix changed an "
                    "already-correct extraction")

        # ---- CASE C (reverse): no declaration must STILL fail closed ---
        c_dir = _make_run_dir(tmp / "case_c", "")
        c = _run(program, c_dir)
        c_file = c_dir / "plugin_output" / "declaration.json"
        if c.returncode != 1:
            failures.append(
                "CASE C (reverse): a header declaring NO algorithm must still "
                f"fail closed with rc==1, got rc={c.returncode}")
        if BANNER not in c.stderr:
            failures.append(
                "CASE C (reverse): fail-closed banner missing from stderr — "
                "the refusal contract broke")
        if c_file.exists():
            failures.append(
                "CASE C (reverse): a partial declaration.json was written on "
                "the fail-closed path")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"NEGATIVE CONTROL HELD — {len(failures)} case(s) failed against "
              f"{program}:", file=sys.stderr)
        for f in failures:
            print(f"  * {f}", file=sys.stderr)
        return 1

    print(f"ALL 3 CASES PASS against {program}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
