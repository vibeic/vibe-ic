#!/usr/bin/env python3
"""ramp_waveform_oracle_check.py — deterministic gate that MEASURES a multi-bit
monotonic-ramp / triangle / sawtooth output and compares it to the bounds and
step the SPEC states, via a spec-derived self-testbench.

WHY
---
`spec_conformance_check` already carries `waveform-peak-hold-dropped` for this
design family, but it is a STRUCTURAL rule: it looks for a direction-toggle
register next to an extreme comparison and the ABSENCE of a hold/dwell keyword,
and its own docstring concedes it "cannot count the hold without simulation". It
therefore covers exactly one of the several properties a ramp spec states
plainly, and covers that one by proxy. The rest — where the ramp turns, whether
it is monotonic between turns, and how big each step is — are not checked
anywhere, so a ramp that counts to the wrong bound, or by the wrong step, passes
the flow and fails its testbench.

Those properties are not decidable from the text: the bound lives in a
comparison whose form varies (`==31`, `>=AMPL-1`, `== {WIDTH{1'b1}}`, a
parameter, a width overflow) and the step lives in an increment that may be
conditional. The representation-independent way to know where a ramp turns is to
RUN it. This is that layer, and it stands in the same relation to
`spec_conformance_check`'s structural rule as
`clock_divider_ratio_oracle_check` does to `clock_divider_phase_form_check`:
the structural gate catches a known-wrong FORM, this measures the CONTRACT.

WHAT it does — given the spec prose + the authored RTL:
  1. Derive an unambiguous ramp contract from the SPEC: the low bound, the high
     bound, and (when stated) the step size and the peak dwell.
  2. Build a self-TB that drives clk + reset and samples the multi-bit output
     every cycle for many ramp periods.
  3. iverilog/vvp it, then measure from the sampled trace:
       - the extremes the output actually reaches;
       - the step between consecutive samples inside each monotonic run;
       - the dwell at each turning point.
  4. BLOCK (rc 1) only on an UNAMBIGUOUS contract violation:
       - the output never moves, or never reverses                  -> BLOCK
       - a reached extreme differs from the spec-stated bound       -> BLOCK
       - a step inside a monotonic run differs from the stated step -> BLOCK
       - the spec states a peak dwell and the measurement differs   -> BLOCK

§4.05 SAFETY — the load-bearing half is the NEGATIVE no-leak. It SKIPs (rc 0)
unless it can build an unambiguous oracle, so it never blocks a correct design:
  - the spec does not state BOTH bounds of a ramp/triangle/sawtooth;
  - no single multi-bit output can be identified;
  - the module has a driveable input beyond clk/reset (an enable/step/load the
    TB cannot safely drive would float and mis-measure a correct design);
  - iverilog is unavailable, the TB does not elaborate, or the sim times out;
  - too few samples, or the trace never completes a full ramp period.
The verdict is read from a TB-written FILE the DUT cannot spoof via $display.
It is purely ADDITIVE: it can only add a BLOCK, never relax an existing check.

chip-AGNOSTIC, prompt-blind: reads only the spec prose the author already reads
and the authored RTL. Never the hidden testbench, the golden, or a scorer
verdict.

CLI:
    ramp_waveform_oracle_check.py --rtl <f.v> --spec <design_description.txt>
        [--top <module>] [--json OUT]
    rc 0 = clean / not-applicable (PASS/SKIP);  rc 1 = measured violation.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Reuse the divider oracle's RTL readers rather than re-implementing them — the
# port/clock/reset grammar is identical and a second copy would be a second
# source of truth.
import clock_divider_ratio_oracle_check as _C  # noqa: E402

CLKP = 10            # driven clock period, time units
MAX_CYCLES = 4000    # sampling budget
MIN_SAMPLES = 40     # below this the trace cannot show a ramp period


# ── spec reading ────────────────────────────────────────────────────────────
# Inflected forms matter: the sentence that states the bounds usually says
# "ramps up to 31", not "ramp". A bare `\bramp\b` misses it and the bounds fall
# out of scope, which silently SKIPs every real ramp spec.
_RAMP_WORD = re.compile(
    r"\b(?:triangle|triangular|ramp(?:s|ed|ing)?|sawtooth|saw-tooth|"
    r"up[-\s]?down|up\s+and\s+down)\b", re.I)

# Ramp bounds are stated as ENDPOINTS scattered through a sentence — "starting
# from 0 it ramps up to 31, then back down to 0" — so a single from-X-to-Y
# pattern misses most real prose. Collect every endpoint the prose names and
# require the distinct set to be EXACTLY two: a third value means the sentence
# names something else as well and the contract is ambiguous, which must SKIP.
_ENDPOINT_RE = [
    re.compile(r"\bfrom\s+(\d+)\b", re.I),
    re.compile(r"\bstarting\s+(?:at|from)\s+(\d+)\b", re.I),
    re.compile(r"\b(?:up\s+|down\s+|back\s+)?to\s+(\d+)\b", re.I),
    re.compile(r"\b(?:reach\w*|until)\s+(\d+)\b", re.I),
]
_BETWEEN_RE = re.compile(r"\bbetween\s+(\d+)\s+and\s+(\d+)\b", re.I)
# "increments by 1", "steps of 2", "in steps of 4"
_STEP_RE = re.compile(
    r"\b(?:increment\w*|decrement\w*|step\w*|change\w*|advanc\w*)\b"
    r"[^.!?]{0,20}?\bby\s+(\d+)\b"
    r"|\bsteps?\s+of\s+(\d+)\b", re.I)
# "held at the peak for 2 cycles", "dwells at the top for one cycle"
_DWELL_RE = re.compile(
    r"\b(?:held|holds?|hold|dwell\w*|pause\w*|stays?|remains?)\b"
    r"[^.!?]{0,40}?\b(?:peak|top|maximum|max|extreme|apex|bound)\b"
    r"[^.!?]{0,20}?\bfor\s+(\d+|one|two|three)\b[\s-]*cycles?\b"
    r"|\b(?:peak|top|maximum|max|extreme|apex)\b[^.!?]{0,30}?"
    r"\b(?:held|holds?|hold|dwell\w*)\b[^.!?]{0,20}?"
    r"\bfor\s+(\d+|one|two|three)\b[\s-]*cycles?\b", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3}


class RampContract:
    def __init__(self, lo: int, hi: int, step: Optional[int],
                 dwell: Optional[int]):
        self.lo, self.hi, self.step, self.dwell = lo, hi, step, dwell

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return (f"RampContract(lo={self.lo}, hi={self.hi}, "
                f"step={self.step}, dwell={self.dwell})")


def derive_contract(spec: str) -> Optional[RampContract]:
    """An unambiguous ramp contract, or None (→ SKIP).

    Requires the prose to name a ramp/triangle/sawtooth AND to state both
    bounds exactly once. A second, DIFFERENT bound pair makes the spec
    ambiguous and yields None rather than a guess."""
    if not _RAMP_WORD.search(spec):
        return None
    # Read endpoints ONLY from the sentences that describe the ramp. A sweep of
    # 1158 repo documents showed unrelated prose ("6400 to 8533" data rates in a
    # compliance-vector list) deriving a contract from numbers that merely
    # shared a document with a ramp word. The bounds of a ramp are stated in the
    # sentence that describes the ramp.
    ramp_sentences = [s for s in re.split(r"(?<=[.!?])\s+", spec)
                      if _RAMP_WORD.search(s)]
    if not ramp_sentences:
        return None
    scope = " ".join(ramp_sentences)

    vals = set()
    m = _BETWEEN_RE.search(scope)
    if m:
        vals.update({int(m.group(1)), int(m.group(2))})
    else:
        for rx in _ENDPOINT_RE:
            for mm in rx.finditer(scope):
                vals.add(int(mm.group(1)))
    if len(vals) != 2:
        return None            # <2 → nothing stated; >2 → ambiguous, never guess
    lo, hi = min(vals), max(vals)
    if hi - lo < 2:
        return None

    steps = {int(g) for m in _STEP_RE.finditer(spec)
             for g in m.groups() if g}
    step = steps.pop() if len(steps) == 1 else None

    dwells = set()
    for m in _DWELL_RE.finditer(spec):
        for g in m.groups():
            if not g:
                continue
            dwells.add(_WORDNUM.get(g.lower(), None)
                       if not g.isdigit() else int(g))
    dwells.discard(None)
    dwell = dwells.pop() if len(dwells) == 1 else None
    return RampContract(lo, hi, step, dwell)


def choose_output(ports: Dict[str, Tuple[str, Optional[int]]]) -> Optional[str]:
    """The single MULTI-BIT output, or None when it is not unique (→ SKIP)."""
    outs = [n for n, (d, w) in ports.items()
            if d == "output" and (w or 1) > 1]
    return outs[0] if len(outs) == 1 else None


def _extra_driveable_inputs(ports: Dict[str, Tuple[str, Optional[int]]],
                            clk: Optional[str], rst: Optional[str]) -> List[str]:
    return [n for n, (d, _w) in ports.items()
            if d == "input" and n not in (clk, rst)]


# ── simulate ────────────────────────────────────────────────────────────────
def _build_tb(module: str, outport: str, width: int, clk: str,
              rst: Optional[str], rst_pol: Optional[str],
              result_path: str) -> str:
    conns = [f".{outport}(outw)", f".{clk}(clkw)"]
    rstreg, resetseq = "", ""
    if rst:
        conns.append(f".{rst}(rstw)")
        a = "1'b0" if rst_pol == "low" else "1'b1"
        d = "1'b1" if rst_pol == "low" else "1'b0"
        rstreg = "  reg rstw;\n"
        resetseq = (f"    rstw = {a};\n"
                    f"    #{CLKP * 2 + 3} rstw = {d};\n")
    return f"""module ramp_tb;
  reg clkw = 0;
{rstreg}  wire [{width - 1}:0] outw;
  integer vf; integer n = 0; reg ready = 0;
  {module} dut({', '.join(conns)});
  always #{CLKP // 2} clkw = ~clkw;
  initial vf = $fopen("{result_path}", "w");
  always @(posedge clkw) if (ready) begin
    $fdisplay(vf, "S %0d", outw);
    n = n + 1;
    if (n >= {MAX_CYCLES}) begin
      $fdisplay(vf, "END");
      $fclose(vf);
      $finish;
    end
  end
  initial begin
{resetseq}    ready = 1;
    #{CLKP * (MAX_CYCLES + 20)};
    $fdisplay(vf, "END");
    $fclose(vf);
    $finish;
  end
endmodule
"""


def _simulate(rtl: str, module: str, outport: str, width: int, clk: str,
              rst: Optional[str], pol: Optional[str]) -> Optional[List[int]]:
    """Return the sampled output trace, or None on any tool failure (→ SKIP).

    The TB is built HERE so the verdict file gets an ABSOLUTE path inside the
    temp dir — vvp runs in the caller's cwd, so a relative path would drop the
    trace somewhere else and every design would silently SKIP."""
    if not _C._iverilog():
        return None
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "dut.v").write_text(rtl)
        res = d / "ramp_result.txt"
        (d / "tb.v").write_text(
            _build_tb(module, outport, width, clk, rst, pol, str(res)))
        try:
            # watchdog-exempt: bounded two-file iverilog compile of a generated
            # TB against one module's RTL — a fixed, small elaboration, not an
            # open-ended EDA run. The sibling oracle checks carry the same
            # marker for the same shape.
            b = subprocess.run(
                ["iverilog", "-g2012", "-o", str(d / "a.out"),
                 str(d / "dut.v"), str(d / "tb.v")],
                capture_output=True, text=True, timeout=120)
            if b.returncode != 0:
                return None
            subprocess.run(["vvp", str(d / "a.out")],
                           capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.SubprocessError):
            return None
        if not res.is_file():
            return None
        trace = []
        for line in res.read_text(errors="replace").splitlines():
            if line.startswith("S "):
                try:
                    trace.append(int(line[2:].strip()))
                except ValueError:
                    return None
        return trace


# ── measure ─────────────────────────────────────────────────────────────────
def measure(trace: List[int]) -> Optional[dict]:
    """Extremes, step sizes and turn dwells from a sampled ramp trace.

    Drops the leading segment before the first turning point, so a reset ramp-in
    from an arbitrary start value cannot be read as a bound."""
    if len(trace) < MIN_SAMPLES:
        return None
    # indices where the direction changes
    turns = []
    prev_dir = 0
    for i in range(1, len(trace)):
        d = (trace[i] > trace[i - 1]) - (trace[i] < trace[i - 1])
        if d == 0:
            continue
        if prev_dir and d != prev_dir:
            turns.append(i - 1)
        prev_dir = d
    if len(turns) < 2:
        return None                       # never reversed twice → no ramp period
    body = trace[turns[0]:turns[-1] + 1]
    if len(body) < 4:
        return None
    steps, dwells = set(), []
    run = 0
    for i in range(1, len(body)):
        d = body[i] - body[i - 1]
        if d == 0:
            run += 1
            continue
        if run:
            dwells.append(run + 1)        # cycles the value was held
            run = 0
        steps.add(abs(d))
    return {"min": min(body), "max": max(body),
            "steps": sorted(steps), "dwells": sorted(set(dwells)),
            "samples": len(body), "turns": len(turns)}


# ── the gate ────────────────────────────────────────────────────────────────
def analyze(rtl: str, spec: str, top: Optional[str] = None) -> dict:
    res: dict = {"applicable": False, "verdict": "SKIP", "reason": "",
                 "evidence": {}}
    c = derive_contract(spec)
    if c is None:
        res["reason"] = ("spec does not state an unambiguous ramp contract "
                         "(a ramp/triangle/sawtooth with exactly one bound pair)")
        return res
    mods = _C._all_modules(rtl)
    if not mods:
        res["reason"] = "no module found"
        return res
    module = top if (top and top in mods) else (mods[-1] if len(mods) == 1
                                                else (top or ""))
    if module not in mods:
        res["reason"] = "top module not identifiable among several (skip, never guess)"
        return res
    ports = _C._ports_of(rtl, module)
    outport = choose_output(ports)
    if not outport:
        res["reason"] = "no single multi-bit output to measure"
        return res
    width = ports[outport][1] or 1
    clk = _C._find_clk(ports)
    if not clk:
        res["reason"] = "no clock input to drive"
        return res
    rst, pol = _C._find_reset(ports)
    extra = _extra_driveable_inputs(ports, clk, rst)
    if extra:
        res["reason"] = (f"module has driveable input(s) {extra} beyond "
                         f"clk/reset — driving them blind could mis-measure a "
                         f"correct design (skip)")
        return res

    res["applicable"] = True
    res["contract"] = {"lo": c.lo, "hi": c.hi, "step": c.step, "dwell": c.dwell}
    res["module"], res["outport"] = module, outport

    trace = _simulate(rtl, module, outport, width, clk, rst, pol)
    if trace is None:
        res.update(verdict="SKIP",
                   reason="oracle build/sim unavailable or failed (skip, not block)")
        return res
    m = measure(trace)
    if m is None:
        res.update(verdict="SKIP",
                   reason="trace does not contain a complete ramp period (skip)")
        return res
    res["evidence"] = m

    problems = []
    if m["max"] != c.hi:
        problems.append(f"the ramp turns at {m['max']} but the spec states an "
                        f"upper bound of {c.hi}")
    if m["min"] != c.lo:
        problems.append(f"the ramp turns at {m['min']} but the spec states a "
                        f"lower bound of {c.lo}")
    if c.step is not None and m["steps"] and m["steps"] != [c.step]:
        problems.append(f"the measured step size(s) {m['steps']} do not match "
                        f"the spec-stated step of {c.step}")
    if c.dwell is not None:
        measured = m["dwells"] or [1]
        if measured != [c.dwell]:
            problems.append(f"the measured dwell at the turning point(s) "
                            f"{measured} does not match the spec-stated "
                            f"{c.dwell} cycle(s)")
    if problems:
        res.update(verdict="BLOCK", reason="; ".join(problems))
    else:
        res.update(verdict="PASS",
                   reason="measured ramp matches the spec-stated contract")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rtl", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--top")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not a.rtl.is_file() or not a.spec.is_file():
        print("ERROR: --rtl and --spec must both exist", file=sys.stderr)
        return 2
    r = analyze(a.rtl.read_text(errors="replace"),
                a.spec.read_text(errors="replace"), a.top)
    if a.json:
        a.json.write_text(json.dumps(r, indent=1))
    if r["verdict"] == "BLOCK":
        print(f"BLOCK: ramp waveform does not match the spec — {r['reason']} "
              f"(measured {r['evidence']}).")
        return 1
    print(f"PASS/SKIP: {r['verdict']} — {r.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
