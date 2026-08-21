#!/usr/bin/env python3
"""clock_divider_ratio_oracle_check.py — deterministic emit gate that MEASURES a
clock divider / generator's produced waveform and compares it to the ratio the
SPEC states, via a spec-derived self-testbench (no hidden TB, no golden).

WHY (benchmark close-loop — freq_divbyeven / freq_divbyfrac false certificates):
A frequency divider's ONLY externally-observable contract is its waveform: it
must divide the input clock by the ratio the spec states, with the stated duty
and reset value. Two RTLLM dividers were CERTIFIED PASS_WITH_WAIVERS by our own
flow yet FAIL their hidden testbench — because every gate we run is STRUCTURAL
(port names, reset spelling, self-toggle form) and NONE of them MEASURES the one
thing the TB checks: "the spec says divide by N with ~50%% duty; does this RTL
actually produce period N and duty ~50%%?".

The pre-existing `clock_divider_period_check.py` DOES check divide ratio, but only
when an L8 doc declares ABSOLUTE source+target frequencies (the FPGA/SoC-integration
case); for a standalone RTLLM divider whose ratio lives in the spec prose + the
RTL's own parameter it SKIPs, and a static regex cannot even match the golden's
`if (cnt < NUM_DIV/2 - 1)` compare form nor the double-edge fractional / free-running
generator forms. The only representation-independent way to know the produced
period/duty is to MEASURE it — i.e. simulate. This gate is the measurement layer;
it complements (does not replace) the structural
`clock_divider_phase_form_check.py` (which catches the odd two-edge-OR self-toggle
PHASE bug — a wrong FIRST-CYCLE phase at a CORRECT period, invisible to a period
measurement).

WHAT it does — given the spec prose + the authored RTL:
  1. Derive from the SPEC an unambiguous expected waveform contract:
       - "frequency divider ... by even/odd numbers ... NUM_DIV"  -> integer divide,
         ratio = the RTL's OWN default of the spec-named divisor parameter (the RTL
         must actually divide by the factor it declares); ~50%% duty (toggle);
       - "fractional ... 3.5x / by 3.5"                            -> divide, ratio 3.5;
       - "clock generator ... PERIOD"  (no clk input)             -> free-running,
         output period == PERIOD (in time units).
  2. Build a tiny self-TB that drives clk+reset (or, for a generator, just runs),
     time-stamps every output edge, and lets the sim run for many output periods.
  3. iverilog/vvp it, measure steady-state period + duty (+ reset value when the
     spec states it), and BLOCK (rc 1) on an UNAMBIGUOUS mismatch:
       - the output never produces a periodic waveform (stuck)            -> BLOCK
       - measured divide ratio differs from spec by > RATIO_TOL           -> BLOCK
       - a toggle divider's duty leaves [DUTY_LO, DUTY_HI]                -> BLOCK
       - spec states the output's reset value and the RTL contradicts it  -> BLOCK

§4.05 SAFETY — the load-bearing half is the NEGATIVE no-leak: the gate SKIPs
(rc 0, advisory) unless it can build an UNAMBIGUOUS oracle. It never BLOCKs a
correct design, because it SKIPs when:
  - the spec is not clearly a divider/generator with a single derivable ratio;
  - the divisor parameter / ratio cannot be resolved to ONE value;
  - the module has an extra driveable input beyond clk/reset (an enable/mode the TB
    cannot safely drive would float and mis-measure a correct design);
  - iverilog is unavailable, the TB does not elaborate, or the sim times out
    (a submodule-instantiating top whose children were not passed elaborates-fails
    -> SKIP, never BLOCK);
  - too few output edges are captured to measure a steady period.
It BLOCKs ONLY on a clean, simulated, unambiguous contract violation, and the
verdict is read from a TB-written FILE the DUT cannot spoof via $display.
It is purely ADDITIVE: it can only add a BLOCK, never relax an existing check, so
it can never turn a currently-failing design green.

chip-AGNOSTIC, prompt-blind (reads only the spec the author already reads + the
authored RTL; never the hidden testbench / golden), deterministic.

CLI:
    clock_divider_ratio_oracle_check.py --rtl <f.v> --spec <design_description.txt>
        [--top <module>] [--json OUT]
    rc 0 = clean / not-applicable (SKIP/PASS); rc 1 = measured contract violation.
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

# ── measurement constants (deterministic) ───────────────────────────────────
CLKP = 10          # driven input-clock period, time units (posedge every CLKP)
RATIO_TOL = 0.30   # a true off-by-one integer divide (ratio N±1) or an integer
                   # substitute for a half-integer (3 vs 3.5, diff .5) exceeds this;
                   # a correct design measures 0 error, so this never false-fires.
DUTY_LO, DUTY_HI = 0.30, 0.70   # a correct 50%%-toggle divider sits at 0.5 exactly;
                                # a 1/4- or 3/4-duty bug leaves this band.
MIN_STEADY_PERIODS = 3          # need at least this many measured periods
MAX_RATIO = 512                 # a larger declared ratio -> SKIP (bounded sim)


def _strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


# ── RTL structural parsing ──────────────────────────────────────────────────
def _all_modules(rtl: str) -> List[str]:
    return re.findall(r"\bmodule\s+([A-Za-z_]\w*)", _strip(rtl))


def _module_span(rtl_stripped: str, module: str) -> str:
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", rtl_stripped)
    if not m:
        return ""
    me = re.search(r"\bendmodule\b", rtl_stripped[m.end():])
    return rtl_stripped[m.start():m.end() + me.start()] if me else rtl_stripped[m.start():]


def _ports_of(rtl: str, module: str) -> Dict[str, Tuple[str, Optional[int]]]:
    """Map port name -> (dir, width) for `module`. width is bit-count for a literal
    [msb:lsb] range, else None (unknown/1-bit scalar treated as 1)."""
    src = _strip(rtl)
    span = _module_span(src, module)
    if not span:
        return {}
    ports: Dict[str, Tuple[str, Optional[int]]] = {}

    def _w(rng: Optional[str]) -> Optional[int]:
        if not rng:
            return 1
        mm = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", rng.strip())
        if not mm:
            return None
        return abs(int(mm.group(1)) - int(mm.group(2))) + 1

    # ANSI header + body declarations both use `input/output [range]? name[,name]`
    for pm in re.finditer(
            r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(signed\s+)?"
            r"(\[[^\]]+\])?\s*([A-Za-z_][\w\s,]*?)\s*(?=[;,)]|input|output|inout)",
            span):
        d, rng, names = pm.group(1), pm.group(3), pm.group(4)
        for nm in re.findall(r"[A-Za-z_]\w*", names):
            ports.setdefault(nm, (d, _w(rng)))
    return ports


def _param_defaults(rtl: str, module: str) -> Dict[str, int]:
    """Map PARAM -> integer default for `module` (best-effort; only integer-valued)."""
    src = _strip(rtl)
    span = _module_span(src, module)
    out: Dict[str, int] = {}
    for pm in re.finditer(
            r"\bparameter\b\s*(?:integer|int|signed|\[[^\]]+\])?\s*"
            r"([A-Za-z_]\w*)\s*=\s*([^,;)]+)", span):
        name, val = pm.group(1), pm.group(2).strip()
        iv = _int_literal(val)
        if iv is not None:
            out.setdefault(name, iv)
    return out


def _int_literal(tok: str) -> Optional[int]:
    """Parse a Verilog integer literal: `10`, `4'd10`, `4'b1010`, `8'hA`, `5`."""
    tok = tok.strip()
    m = re.fullmatch(r"(?:\d+)?\s*'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F_]+)", tok)
    if m:
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(1).lower()]
        try:
            return int(m.group(2).replace("_", ""), base)
        except ValueError:
            return None
    if re.fullmatch(r"[+-]?\d+", tok):
        return int(tok)
    return None


_CLK_RE = re.compile(r"^(clk|clock|clk_in|clkin|clk_i|i_clk)$", re.I)


def _find_clk(ports: Dict[str, Tuple[str, Optional[int]]]) -> Optional[str]:
    for p, (d, _w) in ports.items():
        if d == "input" and _CLK_RE.fullmatch(p):
            return p
    return None


def _find_reset(ports: Dict[str, Tuple[str, Optional[int]]]) -> Tuple[Optional[str], Optional[str]]:
    for p, (d, _w) in ports.items():
        if d == "input" and re.fullmatch(r"rst_n|reset_n|resetn|rstn|n_reset|nrst|arst_n",
                                         p, re.I):
            return p, "low"
    for p, (d, _w) in ports.items():
        if d == "input" and re.fullmatch(r"rst|reset|arst", p, re.I):
            return p, "high"
    return None, None


def _is_1bit(ports: Dict[str, Tuple[str, Optional[int]]], p: str) -> bool:
    w = ports.get(p, (None, None))[1]
    return w in (1, None)


def _choose_output(ports: Dict[str, Tuple[str, Optional[int]]], spec: str
                   ) -> Optional[str]:
    """Resolve the single divided-clock / generated-clock OUTPUT (1-bit)."""
    outs = [p for p, (d, _w) in ports.items() if d == "output" and _is_1bit(ports, p)]
    if not outs:
        return None
    if len(outs) == 1:
        return outs[0]
    # multiple 1-bit outputs — prefer one named for a divided/generated clock and
    # mentioned in the spec; only accept a UNIQUE such match (else ambiguous).
    clk_named = [p for p in outs
                 if re.search(r"clk|clock|div", p, re.I)]
    named_in_spec = [p for p in clk_named if re.search(rf"\b{re.escape(p)}\b", spec)]
    if len(named_in_spec) == 1:
        return named_in_spec[0]
    if len(clk_named) == 1:
        return clk_named[0]
    return None


# ── spec → expected-waveform contract ───────────────────────────────────────
def _spec_fraction(spec: str) -> Optional[float]:
    """A single unambiguous half-/fractional divide factor stated in the spec
    (e.g. `3.5x`, `by 3.5`, `divide ... 2.5`). None if zero or >1 distinct."""
    low = spec.lower()
    if not re.search(r"frac|half[- ]?integer|\bx\b|non[- ]?integer", low) \
            and "divi" not in low:
        return None
    cands = set()
    for m in re.finditer(r"(\d+\.\d+)\s*[x×]?", spec):
        v = float(m.group(1))
        if v != int(v) and 1.0 < v <= MAX_RATIO:
            cands.add(round(v, 3))
    return next(iter(cands)) if len(cands) == 1 else None


def _spec_int_divisor(spec: str) -> Optional[int]:
    """A single explicit integer division factor in the spec ('divide ... by 8').
    None if zero or ambiguous (>1 distinct)."""
    cands = set()
    for m in re.finditer(r"divid\w*\s+(?:the\s+)?(?:input\s+)?(?:clock\s+)?"
                         r"(?:frequency\s+)?by\s+(\d+)\b", spec, re.I):
        v = int(m.group(1))
        if 1 < v <= MAX_RATIO:
            cands.add(v)
    return next(iter(cands)) if len(cands) == 1 else None


def _resolve_divisor_param(spec: str, params: Dict[str, int]) -> Optional[str]:
    """Pick the divisor parameter: a param whose NAME is mentioned in the spec and
    reads like a divide factor. Only a UNIQUE resolution is accepted."""
    if not params:
        return None
    in_spec = [p for p in params if re.search(rf"\b{re.escape(p)}\b", spec)]
    pool = in_spec or list(params)
    divlike = [p for p in pool if re.search(r"div|num|ratio|factor", p, re.I)]
    if len(divlike) == 1:
        return divlike[0]
    if len(pool) == 1:
        return pool[0]
    return None


def _resolve_period_param(spec: str, params: Dict[str, int]) -> Optional[str]:
    if not params:
        return None
    per = [p for p in params if re.search(r"period", p, re.I)]
    if len(per) == 1:
        return per[0]
    in_spec = [p for p in params if re.search(rf"\b{re.escape(p)}\b", spec)]
    if len(in_spec) == 1:
        return in_spec[0]
    if len(params) == 1:
        return next(iter(params))
    return None


def _spec_reset_value(spec: str, outport: str) -> Optional[int]:
    """If the spec UNAMBIGUOUSLY states the output's reset value, return 0/1, else None.
    Tight: the output name and a reset verb and a 0/1 word within one short clause."""
    low = spec.lower()
    op = outport.lower()
    # e.g. "divided clock signal (clk_div) are initialized to zero"
    for m in re.finditer(
            rf"{re.escape(op)}[^.\n]{{0,60}}?\b(initiali[sz]ed|reset|set|cleared|"
            rf"start\w*)\b[^.\n]{{0,20}}?\b(zero|0|one|1|low|high)\b", low):
        word = m.group(2)
        return 0 if word in ("zero", "0", "low") else 1
    return None


class Contract:
    def __init__(self, kind: str, ratio: float, duty_check: bool,
                 param: Optional[str], param_val: Optional[int],
                 reset_val: Optional[int], note: str):
        self.kind = kind            # 'divider' | 'generator'
        self.ratio = ratio          # divide ratio (input clocks) | absolute period (gen)
        self.duty_check = duty_check
        self.param = param
        self.param_val = param_val
        self.reset_val = reset_val
        self.note = note


def derive_contract(spec: str, ports: Dict[str, Tuple[str, Optional[int]]],
                    params: Dict[str, int], outport: str,
                    has_clk: bool) -> Optional[Contract]:
    low = spec.lower()
    divider_words = bool(re.search(r"frequency\s+divider|divid\w+\s+the\s+.*clock|"
                                   r"clock\s+divider|divides?\s+the\s+input\s+clock",
                                   low))
    generator_words = bool(re.search(r"clock\s+generator|generates?\s+a?\s*"
                                      r"(?:periodic\s+)?clock|square\s*wave\s*clock",
                                      low))

    # 1. free-running generator (no clk input, drives its own period)
    if generator_words and not has_clk and not divider_words:
        pp = _resolve_period_param(spec, params)
        if pp is None or params.get(pp, 0) <= 1 or params[pp] > MAX_RATIO:
            return None
        return Contract("generator", float(params[pp]), True, pp, params[pp],
                        None, f"clock generator: output period == {pp}={params[pp]}")

    # 2. divider (needs a clk input to divide)
    if divider_words and has_clk:
        frac = _spec_fraction(spec)
        if frac is not None:
            return Contract("divider", frac, False, None, None,
                            _spec_reset_value(spec, outport),
                            f"fractional divider: ratio {frac}")
        n = _spec_int_divisor(spec)
        if n is not None:
            return Contract("divider", float(n), True, None, None,
                            _spec_reset_value(spec, outport),
                            f"integer divider: explicit ratio {n}")
        pn = _resolve_divisor_param(spec, params)
        if pn is not None and 1 < params.get(pn, 0) <= MAX_RATIO:
            return Contract("divider", float(params[pn]), True, pn, params[pn],
                            _spec_reset_value(spec, outport),
                            f"parameterised divider: ratio = declared {pn}={params[pn]}")
    return None


# ── measurement (spec-derived self-TB) ──────────────────────────────────────
def _iverilog() -> bool:
    try:
        return subprocess.run(["which", "iverilog"], capture_output=True).returncode == 0
    except Exception:
        return False


def _build_tb(module: str, ports: Dict[str, Tuple[str, Optional[int]]],
              outport: str, clk: Optional[str], rst: Optional[str],
              rst_pol: Optional[str], c: Contract, result_path: str) -> str:
    conns = [f".{outport}(outw)"]
    driver = ""
    resetseq = ""
    runtime = int(c.ratio * CLKP * 16 + 200) if clk else int(c.ratio * 16 + 200)
    if clk:
        conns.append(f".{clk}(clkw)")
        driver = "  always #%d clkw = ~clkw;\n" % (CLKP // 2)
    if rst:
        conns.append(f".{rst}(rstw)")
        assert_v = "1'b0" if rst_pol == "low" else "1'b1"
        deassert_v = "1'b1" if rst_pol == "low" else "1'b0"
        resetseq = (f"    rstw = {assert_v};\n"
                    f"    #{CLKP*2 + 3} rstw = {deassert_v};\n"
                    f"    #2 $fdisplay(vf, \"RSTVAL %b\", outw);\n")
    clkreg = "  reg clkw = 0;\n" if clk else ""
    rstreg = "  reg rstw;\n" if rst else ""
    # NO parameter override: the expected ratio IS the RTL's own declared default
    # (c.param_val), so instantiating with defaults gives the same target while
    # avoiding a `#()`-override elaboration failure on a body-declared parameter
    # (which would otherwise SKIP a checkable design).
    # NO `timescale here: dut.v + tb are compiled as ONE file so a DUT-declared
    # timescale (a free-running generator's `#(PERIOD/2)` delays depend on it)
    # governs BOTH, and when the DUT declares none both use iverilog's default —
    # never a TB-vs-DUT timescale mismatch. Measured RATIOs are unit-independent.
    return f"""module cdr_tb;
{clkreg}{rstreg}  wire outw;
  integer vf; reg ready = 0;
  {module} dut({', '.join(conns)});
{driver}  initial vf = $fopen("{result_path}", "w");
  always @(posedge outw) if (ready) $fdisplay(vf, "R %0f", $realtime);
  always @(negedge outw) if (ready) $fdisplay(vf, "F %0f", $realtime);
  initial begin
{resetseq}    ready = 1;
    #{runtime};
    $fdisplay(vf, "END %0f", $realtime);
    $fclose(vf);
    $finish;
  end
endmodule
"""


def _measure(rtl: str, tb: str) -> Optional[dict]:
    """Compile+run; return {'R':[...],'F':[...],'rstval':0/1/None} or None on any
    build/sim failure (caller treats None as SKIP — never BLOCK)."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        rp = tdp / "cdr_verdict.txt"
        tbtxt = tb.replace("__RESULT__", str(rp))
        # DUT + TB in ONE compilation unit so a DUT-declared `timescale governs the
        # TB too (see _build_tb) — the single robust fix for free-running generators.
        (tdp / "sim.v").write_text(rtl + "\n\n" + tbtxt)
        try:
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build)
            c = subprocess.run(["iverilog", "-g2012", "-o", str(tdp / "sim"),
                                str(tdp / "sim.v")],
                               capture_output=True, text=True, timeout=60)
        except Exception:
            return None
        if c.returncode != 0:
            return None
        try:
            subprocess.run(["vvp", str(tdp / "sim")], capture_output=True,
                           text=True, timeout=60)
        except Exception:
            return None
        if not rp.is_file():
            return None
        txt = rp.read_text(errors="replace")
    R: List[float] = []
    F: List[float] = []
    rstval: Optional[int] = None
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "R":
            try:
                R.append(float(parts[1]))
            except ValueError:
                pass
        elif len(parts) == 2 and parts[0] == "F":
            try:
                F.append(float(parts[1]))
            except ValueError:
                pass
        elif len(parts) == 2 and parts[0] == "RSTVAL" and parts[1] in ("0", "1"):
            rstval = int(parts[1])
    return {"R": R, "F": F, "rstval": rstval}


def _steady_stats(R: List[float], F: List[float]) -> Optional[dict]:
    """From rising/falling edge times, drop the reset transient (first 2 rising)
    and return {'periods':[...], 'duties':[...]} over the steady window."""
    if len(R) < 2 + MIN_STEADY_PERIODS:
        return None
    Rs = R[2:]                       # skip reset transient
    periods = [Rs[i + 1] - Rs[i] for i in range(len(Rs) - 1)]
    if len(periods) < MIN_STEADY_PERIODS:
        return None
    duties = []
    for i in range(len(Rs) - 1):
        f = next((x for x in F if Rs[i] < x <= Rs[i + 1]), None)
        if f is not None and Rs[i + 1] > Rs[i]:
            duties.append((f - Rs[i]) / (Rs[i + 1] - Rs[i]))
    return {"periods": periods, "duties": duties}


def analyze(rtl: str, spec: str, top: Optional[str] = None) -> dict:
    res = {"applicable": False, "verdict": "SKIP", "reason": ""}
    if not rtl.strip() or not spec.strip():
        res["reason"] = "empty rtl/spec"
        return res
    mods = _all_modules(rtl)
    if not mods:
        res["reason"] = "no module in RTL"
        return res
    # resolve the top/DUT module
    cand_top = top if (top and top in mods) else None
    if cand_top is None:
        scored = []
        for m in mods:
            ports = _ports_of(rtl, m)
            outp = _choose_output(ports, spec)
            if outp is None:
                continue
            has_clk = _find_clk(ports) is not None
            scored.append((m, ports, outp, has_clk))
        if len(scored) == 1:
            cand_top = scored[0][0]
        elif len(mods) == 1:
            cand_top = mods[0]
        else:
            res["reason"] = "cannot uniquely resolve the divider/generator top module"
            return res
    module = cand_top
    ports = _ports_of(rtl, module)
    if not ports:
        res["reason"] = "could not parse ports of top module"
        return res
    outport = _choose_output(ports, spec)
    if outport is None:
        res["reason"] = "no unique 1-bit clock/divided output"
        return res
    clk = _find_clk(ports)
    rst, rst_pol = _find_reset(ports)
    params = _param_defaults(rtl, module)
    contract = derive_contract(spec, ports, params, outport, clk is not None)
    if contract is None:
        res["reason"] = "spec is not an unambiguous divider/generator contract"
        return res
    if contract.ratio > MAX_RATIO or contract.ratio <= 1.0:
        res["reason"] = f"declared ratio {contract.ratio} out of measurable range"
        return res
    # any EXTRA driveable input (beyond clk/reset) would float and mis-measure a
    # correct design -> fail-safe SKIP.
    extra_in = sorted(p for p, (d, _w) in ports.items()
                      if d == "input" and p not in (clk, rst))
    if extra_in:
        res["reason"] = f"undriveable extra input port(s) {extra_in} — skip (fail-safe)"
        return res
    if contract.kind == "divider" and clk is None:
        res["reason"] = "divider contract but no clk input to divide"
        return res
    if not _iverilog():
        res["reason"] = "iverilog unavailable"
        return res

    res.update(applicable=True, module=module, outport=outport, clk=clk, rst=rst,
               contract=contract.note, expected_ratio=contract.ratio,
               kind=contract.kind)
    tb = _build_tb(module, ports, outport, clk, rst, rst_pol, contract, "__RESULT__")
    meas = _measure(rtl, tb)
    if meas is None:
        res.update(verdict="SKIP", reason="TB did not build/run (skip, not block)")
        return res
    stats = _steady_stats(meas["R"], meas["F"])
    if stats is None:
        # No steady periodic output captured. A stuck output BLOCKs ONLY for a
        # free-running GENERATOR — it self-initialises (an `initial` block), so a
        # stuck generator output is unambiguously broken. A stuck DIVIDER instead
        # SKIPs: the harness may simply not have reset it (an unrecognised reset
        # name / synchronous reset leaves counters at X → a false 'stuck' that is
        # NOT the design's fault) — the §4.05 safe direction is SKIP, not BLOCK.
        if contract.kind == "generator" and len(meas["R"]) < 2:
            res.update(verdict="BLOCK", failure="no_periodic_output",
                       measured_rising_edges=len(meas["R"]),
                       reason="the generator output never produced a periodic "
                              "clock waveform")
            return res
        res.update(verdict="SKIP",
                   reason=f"too few steady edges to measure ({len(meas['R'])} rising)")
        return res

    import statistics
    mean_p = statistics.fmean(stats["periods"])
    measured_ratio = (mean_p / CLKP) if clk else mean_p
    mean_duty = statistics.fmean(stats["duties"]) if stats["duties"] else None
    res.update(measured_ratio=round(measured_ratio, 4),
               measured_duty=(round(mean_duty, 4) if mean_duty is not None else None),
               measured_reset_value=meas["rstval"],
               n_periods=len(stats["periods"]))

    # (a) division ratio
    if abs(measured_ratio - contract.ratio) > RATIO_TOL:
        res.update(verdict="BLOCK", failure="ratio_mismatch",
                   reason=(f"measured divide ratio {measured_ratio:.3f} != "
                           f"expected ratio {contract.ratio:.3f} "
                           f"({contract.note})"))
        return res
    # (b) reset value (only when the spec unambiguously states it)
    if contract.reset_val is not None and meas["rstval"] is not None \
            and meas["rstval"] != contract.reset_val:
        res.update(verdict="BLOCK", failure="reset_value_mismatch",
                   reason=(f"spec states {outport} resets to {contract.reset_val} "
                           f"but the RTL resets it to {meas['rstval']}"))
        return res
    # (c) duty (only for toggle dividers/generators whose duty is ~50%%)
    if contract.duty_check and mean_duty is not None \
            and not (DUTY_LO <= mean_duty <= DUTY_HI):
        res.update(verdict="BLOCK", failure="duty_mismatch",
                   reason=(f"measured duty {mean_duty:.2%} is outside the "
                           f"[{DUTY_LO:.0%},{DUTY_HI:.0%}] band a ~50% toggle "
                           f"{contract.kind} must hold"))
        return res
    res["verdict"] = "PASS"
    # "expected", not "spec" (folded in at merge). For the parameterised family
    # the expected ratio IS the RTL's own declared default — deliberately, see
    # the resolver note — so calling it "spec" states something the spec may not
    # say. MEASURED: with the RTL changed to `NUM_DIV = 7` against a spec whose
    # only stated ratio is "defaults to 5", the PASS line read "spec 7.0". The
    # verdict was right by the rule; the sentence was not, and it is the sentence
    # a reader reaches for when asking why a design was let through.
    res["reason"] = (f"measured ratio {measured_ratio:.3f} ~ expected "
                     f"{contract.ratio} [{contract.note}] "
                     f"(duty "
                     + (f"{mean_duty:.0%}" if mean_duty is not None else "n/a") + ")")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtl", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--top", default=None)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not a.rtl.is_file() or not a.spec.is_file():
        print("ERROR: --rtl and --spec must be files", file=sys.stderr)
        return 2
    res = analyze(a.rtl.read_text(errors="replace"),
                  a.spec.read_text(errors="replace"), a.top)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))
    v = res["verdict"]
    if v == "BLOCK":
        print(f"BLOCK: clock-divider/generator waveform violates the spec — "
              f"{res.get('reason', '')}")
        return 1
    print(f"PASS/SKIP: {v} — {res.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
