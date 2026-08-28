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

WHO CALLS IT
-----------
`tb_vcs_only_construct_detect.py` — the detector whose FLOOR-D verdict this
adjudicates. Given `--golden --tb-top --dut-name` it imports :func:`adjudicate`
and records the result as its report's `floor_proof`, in place of the
`floor_proof_required` string that used to ask a reader to run this by hand.

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
                            stands (needs VCS); OR Verilator cannot build the
                            TB. BOTH are MEASURED: the tool ran to completion
                            and said no. A timeout is rc 2, never this.
  2  CANNOT ADJUDICATE     — verilator not on PATH, an argument / file error,
                            OR the build / sim was STALLED (its process tree
                            made no forward progress at all across the grace).
                            In every case the FLOOR-D stands and no claim is
                            made about the golden. A run that was wedged is not
                            a run that failed, and rc 1 is reserved for what was
                            actually observed. NOTE: neither the build nor the
                            sim is bounded by RUNTIME. A build or a simulation
                            that is still working runs to completion, however
                            long that legitimately takes.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _watchdog as _wd            # noqa: E402  progress supervision
from typing import List

# Defaults MIRROR the authoritative official RTLLM scorer
# (benchmark-data/evaluation/rtllm/score_rtllm.py): PASS iff "Your Design Passed"
# is present AND no real failure marker "Test failed" / "Your Design Failed"
# appears. The scorer DELIBERATELY TOLERATES a zero-count summary line
# ("0/100 failures", "Error count: 0", "No mismatch") on a pass — so the fail
# veto must be the SPECIFIC failure verdict, NOT the generic words
# "failures"/"Error"/"mismatch" (over-flooring those would mis-classify a
# genuinely-recoverable floor as unrecoverable, contradicting the official
# scorer). §4.05: the pass token is the specific phrase (word-boundary, not a
# generic "PASS"/"successful" that matches "bypass"/"unsuccessful"). A non-RTLLM
# benchmark supplies its own --pass-token / --fail-token.
#: Grace windows: how long the tree may be COMPLETELY IDLE, never how long the
#: work may take. Reusing the numbers the old runtime caps used means this can
#: only ever kill LESS than they did — a strict subset.
_STALL_GRACE_S = 300
_SIM_STALL_GRACE_S = 120

_DEFAULT_PASS = ("Your Design Passed",)
_DEFAULT_FAIL = ("Test failed", "Your Design Failed")


def verilator_available() -> bool:
    return shutil.which("verilator") is not None


def _rename_top(golden_src: str, golden_top: str, dut_name: str) -> str:
    """Rename the golden's top module to the name the TB instantiates. Step-2.7:
    rename ONLY the module DECLARATION header (and a named `endmodule : <top>`),
    NOT every whole-word occurrence — a blanket `\\b<top>\\b` sub also rewrote the
    name inside string literals / comments / a same-named signal, corrupting the
    golden. A single-module golden's declaration is the only site the TB's
    instantiation needs renamed."""
    if golden_top == dut_name:
        return golden_src
    src = re.sub(rf"\bmodule\s+{re.escape(golden_top)}\b",
                 f"module {dut_name}", golden_src)
    src = re.sub(rf"\bendmodule\s*:\s*{re.escape(golden_top)}\b",
                 f"endmodule : {dut_name}", src)
    return src


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
        # SUPERVISED BY PROGRESS, never by runtime. A 300 s cap on a Verilator
        # build kills a build that is compiling — on a large golden, or on a
        # loaded host — and no relabelling of that kill helps: the work is
        # destroyed either way. `run_host_supervised` reads CPU and I/O out of
        # /proc across the whole tree, so a build that is doing anything runs to
        # completion, and 300 becomes the grace: how long the tree may be
        # entirely idle before it is called wedged.
        build_argv = ["verilator", "--binary", "--timing", "-Wno-fatal",
                      "-Wno-lint", "-Wno-PINNOTFOUND", "-Wno-WIDTH",
                      "--top-module", tb_top, "golden.v", "testbench.v",
                      "-o", "sim"]
        _res = _wd.run_host_supervised(build_argv, stall_grace_s=_STALL_GRACE_S,
                                       cwd=str(work))
        if _res.outcome in ("stalled", "ceiling"):
            # rc 2 is this file's "cannot adjudicate", and after the watchdog
            # that is a MEASURED statement rather than a shrug: the adjudicator
            # itself is wedged, so it made no finding about the golden. rc 1
            # would have accused the golden of failing a build that never ran.
            return 2, (f"VERILATOR_BUILD_STALLED: the Verilator build made no "
                       f"forward progress — no CPU, no I/O anywhere in its "
                       f"process tree — for {_STALL_GRACE_S}s and was stopped "
                       f"after {_res.elapsed_s:.0f}s. It was not slow; it was "
                       f"doing nothing. Cannot adjudicate; the FLOOR-D stands. "
                       f"This is NOT a finding about the golden.")
        build = _wd.completed_process(build_argv, _res)
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
        # Same replacement as the build above. A TB that is SIMULATING is
        # progressing however many cycles it has left; only one that is wedged
        # has stopped, and only that is a fact worth acting on.
        _res = _wd.run_host_supervised([str(simbin)],
                                       stall_grace_s=_SIM_STALL_GRACE_S,
                                       cwd=str(work))
        if _res.outcome in ("stalled", "ceiling"):
            return 2, (f"VERILATOR_SIM_STALLED: the golden's TB made no forward "
                       f"progress under Verilator for {_SIM_STALL_GRACE_S}s and "
                       f"was stopped after {_res.elapsed_s:.0f}s. It was not "
                       f"slow; it was doing nothing. Cannot adjudicate; the "
                       f"FLOOR-D stands. This is NOT a finding about the "
                       f"golden: a TB that was wedged did not fail.")
        run = _wd.completed_process([str(simbin)], _res)
        out = run.stdout + run.stderr
        # §4.05 — the DANGEROUS direction is FALSE-FAITHFUL (declare a golden a
        # pass when it did not cleanly pass → recover a NON-real floor → inflate
        # the published number). So FAITHFUL requires ALL THREE, and any ambiguity
        # falls to FLOOR-stands (the safe, conservative direction):
        #   (1) the sim EXITED CLEANLY (returncode 0) — a TB that prints a pass
        #       token then $fatal/$stop/segfaults exits non-zero and is NOT a pass;
        #   (2) a SUCCESS token is present (word-boundary, not substring — else a
        #       FAIL line "Test unsuccessful"/"bypass"/"surpassed" would substring-
        #       match "successful"/"PASS"); the default token is the SPECIFIC RTLLM
        #       verdict phrase, not a generic status word;
        #   (3) NO real FAILURE marker co-occurs — mirroring the official scorer
        #       (score_rtllm.py): when "Your Design Passed" is present it is a PASS
        #       UNLESS a real "Test failed"/"Your Design Failed" appears. A zero-
        #       count summary ("0/100 failures", "Error count: 0", "No mismatch")
        #       is DELIBERATELY TOLERATED — vetoing on it would mis-floor a
        #       genuinely-recoverable design, contradicting the official scorer.
        # (1) is a Verilator-substitution safety the official scorer does not need
        # (a Verilator-specific crash where VCS would not crash = unfaithful → floor);
        # an operator widens --fail-token for a non-RTLLM benchmark's failure marker.
        def _tok_re(t: str):
            return re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)
        pass_res = [_tok_re(t) for t in pass_tokens]
        fail_res = [_tok_re(t) for t in fail_tokens]
        has_pass = any(r.search(out) for r in pass_res)
        has_fail = any(r.search(out) for r in fail_res)
        decisive = [ln for ln in out.splitlines()
                    if any(r.search(ln) for r in (*pass_res, *fail_res))][:4]
        if run.returncode == 0 and has_pass and not has_fail:
            return 0, ("VERILATOR_FAITHFUL: the golden cleanly PASSES its own TB under "
                       "Verilator --timing (exit 0, success token, no failure token) → "
                       "NOT a tool-gap floor. Score candidates under Verilator (disclose "
                       "the iverilog→Verilator substitution).\n" + "\n".join(decisive))
        if run.returncode != 0:
            why = f"the sim exited NON-ZERO ({run.returncode}) — not a clean pass"
        elif has_fail:
            why = "a FAILURE token co-occurs with the success token — not a clean pass"
        else:
            why = "no success token in the sim output"
        return 1, ("VERILATOR_UNFAITHFUL: the golden did not cleanly pass its own TB "
                   "under Verilator (" + why + ") → FLOOR-D stands (needs VCS).\n"
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
