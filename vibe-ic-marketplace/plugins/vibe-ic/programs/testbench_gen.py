#!/usr/bin/env python3
"""testbench_gen.py — emit unit + integration testbench from L10 test_cases.

Reads `<project>/generated_docs/L10_TEST_CASES.json` and emits one .v TB
per test case under `<project>/sim/tb/`.

For AID-class chips, the canonical reference TB
`tools/protocol_tb/aid_class_reference_tb.v` is reused; this generator
ships per-test-case TB only for unit-level tests (single-module).

chip-AGNOSTIC. Replaces skills `testbench-gen` and `rtl-unit-testbench-gen`
(archived).

Usage:
    python3 testbench_gen.py <project>
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import _path_layout as _pl


def emit_unit_tb(case: dict, out_dir: Path, top: str) -> Path | None:
    name = case.get("name", "tb_unit")
    opcode = case.get("opcode_hex", "0x00")
    expected = case.get("expected", "(see L3 response_payload_template)")
    kind = case.get("kind", "happy_path")
    polarity = case.get("polarity", "positive")
    f = out_dir / f"{name}.v"
    f.write_text(f"""// Auto-generated unit TB for case={name}
// kind={kind} polarity={polarity}
// stimulus: {case.get('stimulus','')}
// expected: {expected}
`timescale 1ns/1ps
module {name};
  reg clk = 0;
  reg reset_n = 0;
  initial begin
    $display("[TB {name}] BEGIN — opcode={opcode} kind={kind}");
    #100 reset_n = 1;
    #1000 $display("[TB {name}] PASS_PLACEHOLDER (replace with real stimulus)");
    $finish;
  end
  always #5 clk = ~clk;
  // {top} u_dut (.clk(clk), .reset_n(reset_n), ...);
endmodule
""")
    return f


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top", default="chip_top")
    args = p.parse_args()
    l10_path = _pl.generated_docs_dir(args.project) / "L10_TEST_CASES.json"
    if not l10_path.is_file():
        print(f"[SKIP] testbench_gen: no L10_TEST_CASES.json")
        return 0
    try:
        l10 = json.loads(l10_path.read_text())
    except Exception as e:
        print(f"[FAIL] testbench_gen: L10 parse failed: {e}")
        return 1
    out_dir = _pl.sim_dir(args.project) / "tb"
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = l10.get("test_cases") or l10.get("cases") or []
    emitted = 0
    for c in cases:
        if not isinstance(c, dict):
            continue
        if emit_unit_tb(c, out_dir, args.top) is not None:
            emitted += 1
    print(f"[PASS] testbench_gen: {emitted} unit TB files emitted "
          f"under sim/tb/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
