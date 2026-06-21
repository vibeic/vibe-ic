#!/usr/bin/env python3
"""verilator_timing_fallback_check.py — golden-self-test-guarded Verilator fallback
for testbenches iverilog cannot compile.

WHY (the false-FLOOR-D this closes)
-----------------------------------
`tb_vcs_only_construct_detect.py` flags a testbench as FLOOR-D (tool-substitution
gap) when it uses a SystemVerilog construct iverilog 12 rejects — e.g. an
array-aggregate / assignment-pattern init `reg [7:0] d[0:9] = {…}`, or `break;`.
Under the VCS→iverilog substitution that TB will not compile, so a failing design
looks like an unsatisfiable floor. But that is only true if NO acceptable OSS
simulator can run the TB. **Verilator 5.x with `--timing` IS an event-driven OSS
simulator that supports those constructs** — so a "FLOOR-D" purely from an
iverilog-12 frontend gap is NOT a real floor: the design is scorable under
Verilator.

The catch: Verilator's scheduling is not identical to VCS, and an event-driven TB
(especially a clock-domain-crossing design like an async FIFO) can behave
DIFFERENTLY under Verilator than under VCS. So a blind "just use Verilator" would
itself be unfaithful. This program adds the FAITHFULNESS GUARD: run the dataset's
OWN GOLDEN through the TB under Verilator first —

  * golden PASSES its own TB under Verilator  → Verilator is FAITHFUL for this TB;
    it is NOT a tool-gap floor — score candidates under Verilator (disclose it).
  * golden FAILS  its own TB under Verilator   → Verilator is UNFAITHFUL here
    (scheduling/CDC mismatch with VCS); the FLOOR-D stands (needs real VCS).
  * Verilator absent                            → cannot adjudicate; FLOOR-D stands.

This is general (any benchmark TB), no-cheat (the golden-self-test never fakes a
pass — a genuinely-unsatisfiable TB still floors), and §4.05-tight (a TB Verilator
runs unfaithfully is NOT waved through).

CLI
---
  verilator_timing_fallback_check.py --tb <tb.v> --golden <golden.v>
      --tb-top <tb_module> --dut-name <name-the-TB-instantiates>
      [--golden-top <golden's current top module name; default = --dut-name>]
      [--data-dir <dir holding $readmemh data files>]
      [--pass-token T ...] [--fail-token T ...]

EXIT CODES
  0  VERILATOR_FAITHFUL    — golden passes its own TB under Verilator → NOT a
                            tool-gap floor; score under Verilator (disclose).
  1  VERILATOR_UNFAITHFUL  — golden fails its own TB under Verilator → FLOOR-D
                            stands (needs VCS); OR Verilator cannot build the TB.
  2  VERILATOR_ABSENT / IO — verilator not on PATH (cannot adjudicate; FLOOR-D
                            stands), or an argument / file error.

chip-AGNOSTIC: reasons over a TB, a golden, module names, and sim output tokens.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

_DEFAULT_PASS = ("Your Design Passed", "PASS", "Passed", "successful")
_DEFAULT_FAIL = ("Failed", "failures", "Error", "ERROR", "mismatch", "WRONG", "incorrect")


def verilator_available() -> bool:
    return shutil.which("verilator") is not None


def _rename_top(golden_src: str, golden_top: str, dut_name: str) -> str:
    """Rename the golden's top module to the name the TB instantiates (only the
    whole-word module identifier; submodules with other names are untouched)."""
    if golden_top == dut_name:
        return golden_src
    return re.sub(rf"\b{re.escape(golden_top)}\b", dut_name, golden_src)


def adjudicate(tb: Path, golden: Path, tb_top: str, dut_name: str,
               golden_top: str, data_dir: Path | None,
               pass_tokens: List[str], fail_tokens: List[str]) -> tuple[int, str]:
    if not verilator_available():
        return 2, ("VERILATOR_ABSENT: verilator not on PATH — cannot adjudicate; "
                   "the iverilog tool-gap (FLOOR-D) stands under our substitution.")
    if not tb.is_file() or not golden.is_file():
        return 2, f"IO: missing tb ({tb}) or golden ({golden})."

    work = Path(tempfile.mkdtemp())
    try:
        shutil.copy(tb, work / "testbench.v")
        gsrc = _rename_top(golden.read_text(errors="replace"), golden_top, dut_name)
        (work / "golden.v").write_text(gsrc)
        # stage $readmemh/$readmemb data files (never the golden) if a dir is given
        if data_dir and data_dir.is_dir():
            for f in data_dir.iterdir():
                if f.suffix.lower() in (".txt", ".dat", ".mem", ".hex", ".data", ".bin") and f.is_file():
                    shutil.copy(f, work / f.name)
        build = subprocess.run(
            ["verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint",
             "-Wno-PINNOTFOUND", "-Wno-WIDTH", "--top-module", tb_top,
             "golden.v", "testbench.v", "-o", "sim"],
            cwd=work, capture_output=True, text=True)
        if build.returncode != 0:
            tailerr = "\n".join(
                ln for ln in build.stderr.splitlines() if "%Error" in ln)[:400]
            return 1, ("VERILATOR_BUILD_FAIL: Verilator cannot build this TB either "
                       "→ genuine FLOOR-D.\n" + tailerr)
        simbin = work / "obj_dir" / "sim"
        if not simbin.exists():
            # some verilator versions place the -o binary at work/sim
            alt = work / "sim"
            simbin = alt if alt.exists() else simbin
        run = subprocess.run([str(simbin)], cwd=work, capture_output=True, text=True)
        out = run.stdout + run.stderr
        # The SUCCESS token is the decisive verdict: RTLLM testbenches print it
        # ONLY when their error counter is zero. Per-sample diagnostic lines like
        # "Failed at i=0 …" (a tolerated reset/first-cycle artifact) must NOT
        # override a final success token — so the success token, when present,
        # decides PASS. Absence of it = the golden did not pass under Verilator.
        has_pass = any(t.lower() in out.lower() for t in pass_tokens)
        decisive = [ln for ln in out.splitlines()
                    if any(t.lower() in ln.lower() for t in (*pass_tokens, *fail_tokens))][:4]
        if has_pass:
            return 0, ("VERILATOR_FAITHFUL: the golden PASSES its own TB under "
                       "Verilator --timing → NOT a tool-gap floor. Score candidates "
                       "under Verilator (disclose the iverilog→Verilator substitution).\n"
                       + "\n".join(decisive))
        return 1, ("VERILATOR_UNFAITHFUL: the golden FAILS its own TB under Verilator "
                   "(scheduling/CDC mismatch with VCS) → FLOOR-D stands (needs VCS).\n"
                   + "\n".join(decisive or out.splitlines()[-3:]))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tb", required=True)
    ap.add_argument("--golden", required=True)
    ap.add_argument("--tb-top", required=True, help="the testbench's top module name")
    ap.add_argument("--dut-name", required=True,
                    help="the module name the TB instantiates (the golden is renamed to this)")
    ap.add_argument("--golden-top", help="golden's current top module name (default = --dut-name)")
    ap.add_argument("--data-dir", help="dir holding $readmemh/$readmemb data files")
    ap.add_argument("--pass-token", action="append", default=[])
    ap.add_argument("--fail-token", action="append", default=[])
    a = ap.parse_args(argv)
    rc, msg = adjudicate(
        Path(a.tb), Path(a.golden), a.tb_top, a.dut_name,
        a.golden_top or a.dut_name,
        Path(a.data_dir) if a.data_dir else None,
        a.pass_token or list(_DEFAULT_PASS),
        a.fail_token or list(_DEFAULT_FAIL))
    print(msg)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
