#!/usr/bin/env python3
"""analog_sc_loop_probe.py — MEASURE a switched-capacitor loop's coefficients
on the netlist A3 emitted, and (with --validate) check the swing A2 sized for.

CHIP_AGNOSTIC: strict-logic

WHY THIS EXISTS (q6-a2-cap-osr, verifier's B1'). A2 used to take each stage's
loop coefficients from its capacitor RATIOS: `b1 = cs1/ci1`, `a1 = cf1/ci1`.
MEASURED on u_hawaii_adc delta_sigma (tt, 27C, four DC inputs, a per-clock
regression of the first integrator's step): the DAC coefficient is 0.2494
against a ratio of 0.2499 — the branch realises its ratio — but the INPUT
coefficient is 0.2686 against the SAME ratio, +7.5 %, with a 7.0 mV/clock
offset. The input branch opens its top- and bottom-plate switches on the same
phase, so signal-dependent charge injection lands on the sampling capacitor;
the DAC branch's source switch is gated later and does not. No ratio shows
that. So the swing model and the sizing that follows from it take the
coefficients from HERE, and the capacitor ratios are only the starting point.

WHAT IT RUNS. The A3 testbench of the block (its `.lib`/`.include` lines, its
supply, reference and clock sources, unchanged) with the input held at a few
DC levels inside the linear range, for a few dozen clocks. Nothing is read
from any oracle, golden or harness artefact (§4.05): the netlist and the
testbench are this flow's own outputs.

THE FIT, per stage s, over every clock n outside the conversion reset:

    y_s[n+1] - y_s[n] = g_s * (x_s[n] - vcm) + a_s * (fb[n] - vcm) + o_s

where x_1 is the held input, x_s (s > 1) is the previous stage's output at
the start of the clock, fb is the feedback net sampled inside the clock and
vcm the common-mode net sampled with the outputs. `a_s` is the DAC
coefficient, `g_s` the input (s = 1) or inter-stage coefficient, `o_s` the
per-clock offset. Every net comes from the IR's `loop_probe` declaration —
none is named here.

THE CAPACITOR RATIOS the measurement is compared against are computed from
the rendered netlist's own device geometry on the PDK's measured two-term
model, so `gain = measured / ratio` is a property of the SWITCH network, not
of the sizes, and survives A2 resizing the capacitors.

--validate (verifier's B3' circuit check): the input held at the DECLARED
full span (+/- u_decl half-spans about the common mode) and at the fit
levels. Every integrator's excursion about vcm must stay within
`integrator_swing_fraction_of_vdd * vdd_min / 2`, and the per-level DAC
coefficient must not compress by more than 1 % against the linear-range fit.

OUTPUTS, under `phase3/analog/<block>/`:
  loop_coefficients.json   (fit)
  loop_validation.json     (--validate)
Both carry `structure_sha256` (`analog_a2_topology_emit.
loop_structure_fingerprint`) so A2 uses a measurement only for the switch
network it was taken on.

Exit: 0 measured (validate: and PASS), 1 validate FAIL, 2 not applicable /
inputs missing, 3 simulator did not produce the record.

No chip / SKU / foundry literal.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                     # noqa: E402
import sys as _sys                                                   # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse                                                      # noqa: E402
import concurrent.futures as _cf                                     # noqa: E402
import hashlib                                                       # noqa: E402
import json                                                          # noqa: E402
import math                                                          # noqa: E402
import re                                                            # noqa: E402
import shlex                                                         # noqa: E402
import time                                                          # noqa: E402
from pathlib import Path                                             # noqa: E402
from typing import Any, Dict, List, Optional, Sequence, Tuple        # noqa: E402

import _atomic_artefact as _atomic                                   # noqa: E402
import _container_exec as _ce                                        # noqa: E402
import analog_a2_topology_emit as _a2                                # noqa: E402

PRODUCER = "analog_sc_loop_probe"
SCHEMA = 1
FIT_ARTEFACT = "loop_coefficients.json"
VALIDATION_ARTEFACT = "loop_validation.json"
PROBE_KEY = "loop_probe"

#: DC levels for the fit, in units of the HALF reference span about the
#: common mode. Inside the linear range on purpose: the verifier measured the
#: DAC coefficient compressing from 0.249 to 0.232 at u = 0.62, so a fit taken
#: out there would read the compression as the coefficient.
FIT_LEVELS = (-0.08, 0.02, 0.12, 0.22)
FIT_CLOCKS = 36
VALIDATE_CLOCKS = 64
#: Clocks after power-up the fit ignores (the loop leaving its reset state).
SKIP_CLOCKS = 3
#: How far before a rising clock edge the held outputs are sampled.
SAMPLE_BEFORE_EDGE = 0.005
#: Where inside the clock the feedback net is sampled, as a fraction of the
#: period after the rising edge.
FEEDBACK_SAMPLE_AT = 0.25
#: The DAC coefficient may compress this much at the declared span (B3').
MAX_DAC_COMPRESSION = 0.01
#: The fraction of a stage's per-clock step variance the linear per-clock
#: recurrence must explain before its coefficients are used. MEASURED on
#: u_hawaii_adc delta_sigma: stage 1 fits with rms 0.18 mV; stage 2 with
#: 9.1 mV, because the integrator outputs do NOT hold during the sampling
#: phase (vint swings 0.35-0.86 V inside it) and the next stage samples that
#: moving node — the blind spot `analog_incremental_resolution` names. A fit
#: that poor is reported, never used.
MIN_FIT_R2 = 0.995

RC_OK, RC_FAIL, RC_NA, RC_NO_RECORD = 0, 1, 2, 3


# ── the fit (pure arithmetic, no simulator) ──────────────────────────────
def _solve(ata: List[List[float]], atb: List[float]) -> Optional[List[float]]:
    n = len(atb)
    m = [row[:] + [atb[i]] for i, row in enumerate(ata)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-18:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def least_squares(rows: Sequence[Sequence[float]], y: Sequence[float]
                  ) -> Optional[Dict[str, Any]]:
    """Ordinary least squares `y ~ rows @ beta`, with the rms residual."""
    if not rows:
        return None
    k = len(rows[0])
    if len(rows) <= k:
        return None
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(k)]
           for i in range(k)]
    atb = [sum(r[i] * v for r, v in zip(rows, y)) for i in range(k)]
    beta = _solve(ata, atb)
    if beta is None:
        return None
    res = [v - sum(b * x for b, x in zip(beta, r)) for r, v in zip(rows, y)]
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y)
    sse = sum(e * e for e in res)
    return {"beta": beta, "n": len(rows),
            "rms_residual": math.sqrt(sse / len(res)),
            "r2": (1.0 - sse / sst) if sst > 0 else None}


def clock_samples(run: Dict[str, Any], nets: Dict[str, str],
                  stages: Sequence[str], period: float, t0: float,
                  vdd: float) -> List[Dict[str, float]]:
    """Per-clock samples of one run: each stage output and vcm just before
    the rising edge, the feedback net inside the clock, the reset flag."""
    t = run["t"]
    cols = run["v"]

    def at(name: str, when: float) -> float:
        xs = cols[name]
        if when <= t[0]:
            return xs[0]
        if when >= t[-1]:
            return xs[-1]
        lo, hi = 0, len(t) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if t[mid] <= when:
                lo = mid
            else:
                hi = mid
        f = (when - t[lo]) / ((t[hi] - t[lo]) or 1.0)
        return xs[lo] + f * (xs[hi] - xs[lo])

    out: List[Dict[str, float]] = []
    k = 1
    while True:
        edge = t0 + k * period
        ts = edge - SAMPLE_BEFORE_EDGE * period
        if edge + period > t[-1]:
            break
        row = {"k": k, "vcm": at(nets["common_mode"], ts),
               "fb": at(nets["feedback"], edge + FEEDBACK_SAMPLE_AT * period),
               "reset": at(nets["reset"], ts) > vdd / 4.0}
        for s, net in enumerate(stages):
            row[f"y{s}"] = at(net, ts)
        out.append(row)
        k += 1
    return out


def fit_stages(runs: Sequence[Tuple[float, List[Dict[str, float]]]],
               n_stages: int, skip: int = SKIP_CLOCKS
               ) -> List[Dict[str, Any]]:
    """One regression per stage, pooled over every run. `runs` is
    `[(held_input_volts, samples), ...]`."""
    out: List[Dict[str, Any]] = []
    for s in range(n_stages):
        rows: List[List[float]] = []
        ys: List[float] = []
        for vin, smp in runs:
            for i in range(skip, len(smp) - 1):
                a, b = smp[i], smp[i + 1]
                if a["reset"] or b["reset"]:
                    continue
                xin = (vin - a["vcm"]) if s == 0 else (a[f"y{s-1}"] - a["vcm"])
                rows.append([xin, a["fb"] - a["vcm"], 1.0])
                ys.append(b[f"y{s}"] - a[f"y{s}"])
        fit = least_squares(rows, ys)
        if fit is None:
            out.append({"stage": s + 1, "status": "NOT_MEASURED",
                        "reason": "too few clocks outside the reset"})
            continue
        g, a_dac, off = fit["beta"]
        good = fit["r2"] is not None and fit["r2"] >= MIN_FIT_R2
        out.append({"stage": s + 1,
                    "status": "MEASURED" if good else "POOR_FIT",
                    "input_coefficient": g, "dac_coefficient": a_dac,
                    "offset_v_per_clock": off, "n": fit["n"],
                    "rms_residual_v": fit["rms_residual"], "r2": fit["r2"],
                    "min_r2": MIN_FIT_R2})
        if not good:
            out[-1]["reason"] = (
                "the per-clock linear recurrence explains too little of this "
                "stage's step: its output does not hold a value between "
                "clocks, so no coefficient read off it is the loop's")
    return out


def per_run_dac(samples: List[Dict[str, float]], vin: float, stage: int,
                skip: int = SKIP_CLOCKS) -> Optional[float]:
    """The DAC coefficient of ONE run (input held), per-run constant absorbing
    the input term — the compression witness."""
    rows, ys = [], []
    for i in range(skip, len(samples) - 1):
        a, b = samples[i], samples[i + 1]
        if a["reset"] or b["reset"]:
            continue
        x = [a["fb"] - a["vcm"], 1.0]
        if stage > 0:
            x.insert(0, a[f"y{stage-1}"] - a["vcm"])
        rows.append(x)
        ys.append(b[f"y{stage}"] - a[f"y{stage}"])
    fit = least_squares(rows, ys)
    if fit is None:
        return None
    return fit["beta"][-2]


# ── capacitor ratios from the rendered netlist ───────────────────────────
_DEV_RE = re.compile(r"^\s*x(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", re.I)


def _param(text: str, key: str) -> Optional[float]:
    m = re.search(r"\b" + key + r"\s*=\s*([0-9.eE+-]+)(u?)", text)
    if not m:
        return None
    v = float(m.group(1))
    return v if m.group(2) else v * 1e6


def netlist_capacitances(netlist: str, carea: float, cperi: float
                         ) -> Dict[str, float]:
    """`{device_name: fF}` for every two-terminal device carrying w and l —
    unit arrays (`<name>_u<k>`) summed under their base name as well."""
    caps: Dict[str, float] = {}
    for line in netlist.splitlines():
        m = _DEV_RE.match(line)
        if not m:
            continue
        name, rest = m.group(1), m.group(5)
        w, l_ = _param(rest, "w"), _param(rest, "l")
        if w is None or l_ is None:
            continue
        c = carea * w * l_ + 2.0 * cperi * (w + l_)
        caps[name] = caps.get(name, 0.0) + c
        base = re.sub(r"_u\d+$", "", name)
        if base != name:
            caps[base] = caps.get(base, 0.0) + c
    return caps


def cap_ratios(decl: Dict[str, Any], caps: Dict[str, float], n_stages: int
               ) -> List[Dict[str, Optional[float]]]:
    dev = decl.get("coefficient_devices") or {}
    out = []
    for i in range(1, n_stages + 1):
        cs = caps.get(str(dev.get("sampling", "")).format(i=i))
        ci = caps.get(str(dev.get("integrating", "")).format(i=i))
        cf = caps.get(str(dev.get("feedback", "")).format(i=i))
        out.append({"stage": i,
                    "input": (cs / ci) if cs and ci else None,
                    "dac": (cf / ci) if cf and ci else None,
                    "cs_ff": cs, "ci_ff": ci, "cf_ff": cf})
    return out


# ── the deck ─────────────────────────────────────────────────────────────
def _source_value(tb: str, port: str) -> Optional[float]:
    m = re.search(r"^v\S*\s+" + re.escape(port) + r"\s+0\s+([0-9.eE+-]+)\s*$",
                  tb, re.M)
    return float(m.group(1)) if m else None


def _clock(tb: str, port: str) -> Optional[Tuple[float, float, float]]:
    """`(delay_s, period_s, high_v)` of the declared clock source."""
    m = re.search(r"^v\S*\s+" + re.escape(port) + r"\s+0\s+pulse\(([^)]*)\)",
                  tb, re.M | re.I)
    if not m:
        return None
    vals = []
    for tok in m.group(1).split():
        mm = re.match(r"([0-9.eE+-]+)(n|u|m|p)?$", tok)
        if not mm:
            return None
        scale = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "p": 1e-12}.get(
            mm.group(2) or "", 1.0)
        vals.append(float(mm.group(1)) * scale)
    if len(vals) < 7:
        return None
    return vals[2], vals[6], vals[1]


def _instance(tb: str, subckt: str) -> Optional[str]:
    for line in tb.splitlines():
        toks = line.split()
        if toks and toks[0].lower().startswith("x") and \
                toks[-1] == subckt:
            return toks[0]
    return None


def build_deck(tb: str, *, input_port: str, vin: float, inst: str,
               nets: Sequence[str], tstop: float, tstep: float,
               out_file: str, rel_prefix: str = "",
               threads: Optional[int] = None) -> str:
    """The A3 testbench, with the input held at `vin`, its own `.save` and
    `.control` replaced by this probe's, and nothing else touched — except
    that a RELATIVE `.include`/`.lib` path is re-rooted by `rel_prefix`,
    because ngspice resolves it against the directory of the deck carrying
    it and the probe's decks sit one directory below the testbench."""
    keep: List[str] = []
    in_ctl = False
    replaced = False
    for line in tb.splitlines():
        low = line.strip().lower()
        if low.startswith(".control"):
            in_ctl = True
            continue
        if in_ctl:
            if low.startswith(".endc"):
                in_ctl = False
            continue
        if low.startswith(".save") or low == ".end":
            continue
        m = re.match(r"^(\.include|\.lib)\s+(\S+)(.*)$", line.strip(), re.I)
        if m and rel_prefix and not m.group(2).startswith(("/", "'/", '"/')):
            keep.append(f"{m.group(1)} {rel_prefix}{m.group(2)}{m.group(3)}")
            continue
        if re.match(r"^v\S*\s+" + re.escape(input_port) + r"\s+0\s+\S+\s*$",
                    line):
            name = line.split()[0]
            keep.append(f"{name} {input_port} 0 {vin:.6f}")
            replaced = True
            continue
        keep.append(line)
    if not replaced:
        raise ValueError(f"the testbench drives no DC source on "
                         f"`{input_port}`")
    vecs = " ".join(f"v({inst}.{n})" for n in nets)
    if threads is not None and (isinstance(threads, bool) or not isinstance(threads, int) or threads < 1):
        raise ValueError("threads must be a positive integer")
    keep += [f".save {vecs}", ".control"]
    if threads is not None:
        keep += [f"set num_threads={threads}", "set numdgt=15"]
    keep += ["set wr_singlescale",
             "set wr_vecnames", f"tran {tstep:.6g} {tstop:.6g}",
             f"wrdata {out_file} {vecs}", ".endc", ".end"]
    return "\n".join(keep) + "\n"


def read_wrdata(path: Path, inst: str, nets: Sequence[str]
                ) -> Optional[Dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    if len(lines) < 3:
        return None
    t: List[float] = []
    cols: Dict[str, List[float]] = {n: [] for n in nets}
    for ln in lines[1:]:
        toks = ln.split()
        if len(toks) < 1 + len(nets):
            continue
        try:
            vals = [float(x) for x in toks[:1 + len(nets)]]
        except ValueError:
            continue
        t.append(vals[0])
        for n, v in zip(nets, vals[1:]):
            cols[n].append(v)
    return {"t": t, "v": cols} if len(t) > 10 else None


# ── orchestration ────────────────────────────────────────────────────────
def _sha(p: Path) -> Optional[str]:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _run_decks(decks: Dict[str, Path], container: str, budget_s: float,
               workers: Optional[int] = None, threads: Optional[int] = None,
               wait_policy: Optional[str] = None, working_dir: Optional[Path] = None
               ) -> Dict[str, int]:
    """Every deck in parallel under ONE supervised command (no clock: reaped
    only on a progress stall, vibe-ic#2051/#2083). `budget_s` is a recorded
    budget whose crossing is announced, never a kill.

    ONE command, not one per deck, and that is load-bearing. The stillness
    probe watches the whole container; with one supervised call per deck, a
    deck that FINISHED took its CPU out of every other call's sum and the
    still-computing decks were reaped as STALLED (measured: five of six, rc
    199, three minutes after the first finished). Here the decks are children
    of one in-container shell that `wait`s for them, so a finished deck's CPU
    moves into that shell's reaped-children time and the sum never drops.
    Each deck's rc is written beside its log."""
    if not decks:
        return {}
    wdir = next(iter(decks.values())).parent
    if workers is not None and (isinstance(workers, bool) or not isinstance(workers, int) or workers < 1):
        raise ValueError("workers must be a positive integer")
    if threads is not None and (isinstance(threads, bool) or not isinstance(threads, int) or threads < 1):
        raise ValueError("threads must be a positive integer")
    if wait_policy not in (None, "PASSIVE", "ACTIVE"):
        raise ValueError("wait policy must be PASSIVE or ACTIVE")
    environment = []
    if threads is not None:
        environment.append(f"OMP_NUM_THREADS={threads}")
    if wait_policy:
        environment.append("OMP_WAIT_POLICY=" + wait_policy)
        if wait_policy == "PASSIVE":
            environment.append("GOMP_SPINCOUNT=0")
    prefix = "env " + " ".join(environment) + " " if environment else ""
    parts = [f"cd {shlex.quote(str(working_dir or wdir))}"]
    entries = list(decks.items())
    count = min(workers or len(entries), len(entries))
    for start in range(0, len(entries), count):
        for tag, deck in entries[start:start + count]:
            selected = deck if working_dir else Path(deck.name)
            stem = deck.with_suffix("") if working_dir else Path(deck.stem)
            parts.append(
                f"( {prefix}ngspice -b {shlex.quote(str(selected))} > "
                f"{shlex.quote(str(stem))}.log 2>&1; echo $? > "
                f"{shlex.quote(str(stem))}.rc ) &")
        parts.append("wait")
    cp = _ce.run_in_container_supervised(container, "\n".join(parts),
                                         ceiling_s=float(budget_s))
    out: Dict[str, int] = {}
    for tag, deck in decks.items():
        try:
            out[tag] = int((wdir / f"{deck.stem}.rc").read_text().strip())
        except (OSError, ValueError):
            out[tag] = cp.returncode
    return out


def probe(project: Path, block: str, container: str, validate: bool = False,
          clocks: Optional[int] = None, budget_s: float = 14400.0,
          reuse_records: bool = False, workers: Optional[int] = None,
          threads: Optional[int] = None, wait_policy: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    bdir = project / "phase3" / "analog" / block
    ir_p, sp_p = bdir / "topology.json", bdir / f"{block}.sp"
    tb_p, spec_p = bdir / f"tb_{block}.sp", bdir / "spec.json"
    try:
        ir = json.loads(ir_p.read_text())
        spec = json.loads(spec_p.read_text())
        tb, netlist = tb_p.read_text(), sp_p.read_text()
    except (OSError, ValueError) as exc:
        return RC_NA, {"status": "NOT_APPLICABLE",
                       "reason": f"inputs missing: {exc}"}
    decl = ir.get(PROBE_KEY)
    if not isinstance(decl, dict):
        return RC_NA, {"status": "NOT_APPLICABLE",
                       "reason": f"the IR declares no `{PROBE_KEY}`"}
    chain = []
    for g in [ir.get("stage_expansion") or {}] + list(
            (ir.get("stage_expansion") or {}).get("groups") or []):
        if isinstance(g, dict) and g.get("role") == "cascade":
            chain = list(g.get("chain") or [])
            break
    stages = chain[1:]
    if not stages:
        return RC_NA, {"status": "NOT_APPLICABLE",
                       "reason": "the IR records no integrator cascade"}
    sv = _a2.spec_row_values(spec.get("specs"))
    nets = {"common_mode": decl["common_mode_net"],
            "feedback": decl["feedback_net"], "reset": decl["reset_net"]}
    clk = _clock(tb, decl["clock_port"])
    rp = [_source_value(tb, p) for p in decl["reference_ports"]]
    inst = _instance(tb, block)
    if clk is None or None in rp or inst is None:
        return RC_NA, {"status": "NOT_APPLICABLE",
                       "reason": "the testbench's clock, reference sources "
                                 "or DUT instance could not be read"}
    t0, period, vhigh = clk
    half = abs(rp[0] - rp[1]) / 2.0
    vcm_nom = (rp[0] + rp[1]) / 2.0
    levels: List[Tuple[str, float]] = [(f"fit_{u:+.2f}", u)
                                       for u in FIT_LEVELS]
    u_decl = _a2._res.declared_input_span(sv, decl.get("input_span_spec",
                                                       "vindiff"))
    if validate:
        if u_decl is None:
            return RC_NA, {"status": "NOT_APPLICABLE",
                           "reason": "the declared input span is not bound"}
        levels += [("span_pos", u_decl), ("span_neg", -u_decl)]
    n_clk = int(clocks or (VALIDATE_CLOCKS if validate else FIT_CLOCKS))
    tstop = t0 + (n_clk + 1) * period
    vnets = list(stages) + [nets["common_mode"], nets["feedback"],
                            nets["reset"]]
    wdir = bdir / ("loop_validation" if validate else "loop_probe")
    wdir.mkdir(parents=True, exist_ok=True)
    decks: Dict[str, Path] = {}
    vins: Dict[str, float] = {}
    import analog_bound_measurements as _bound
    native_tb = _bound.contextual_template(tb, tb_p.parent)
    for tag, u in levels:
        vin = vcm_nom + u * half
        vins[tag] = vin
        deck = build_deck(native_tb, input_port=decl["input_port"], vin=vin,
                          inst=inst, nets=vnets, tstop=tstop,
                          tstep=period / 200.0, out_file=str(wdir / f"w_{tag}.txt"), threads=threads)
        p = wdir / f"{tag}.sp"
        if reuse_records:
            if not p.is_file() or p.read_text() != deck:
                return RC_NO_RECORD, {"status": "NOT_MEASURED", "reason": "cached probe deck differs; native records cannot be relabelled"}
        else:
            p.write_text(deck)
        decks[tag] = p
    started = time.time()
    native_inputs = {role: {"path": str(path.resolve()), "sha256": _sha(path)} for role, path in
                     (("netlist", sp_p), ("testbench", tb_p), ("spec", spec_p), ("topology", ir_p))}
    for tag, deck_path in decks.items():
        native_inputs["deck:" + tag] = {"path": str(deck_path.resolve()), "sha256": _sha(deck_path)}
        try:
            native_inputs.update(_bound.consumed_input_views(project, deck_path))
        except (OSError, ValueError) as exc:
            return RC_NO_RECORD, {"status": "NOT_MEASURED", "reason": "native input closure unavailable: " + str(exc)}
    if not any(view["sha256"] == native_inputs["netlist"]["sha256"]
               for role, view in native_inputs.items() if role.startswith("include:")):
        return RC_NO_RECORD, {"status": "NOT_MEASURED", "reason": "declared DUT is absent from the native include closure"}
    execution_settings = {"workers": workers, "threads": threads, "wait_policy": wait_policy,
                          "container": container, "image": _os.environ.get("VIBEIC_EDA_IMAGE")}
    snapshot = wdir / "native-inputs.json"
    if reuse_records:
        try:
            prior = json.loads(snapshot.read_text())
        except (OSError, ValueError):
            prior = {}
        if prior != {"native_inputs": native_inputs, "execution": execution_settings} or not all(
                (wdir / f"w_{tag}.txt").is_file() for tag in decks):
            return RC_NO_RECORD, {"status": "NOT_MEASURED", "reason": "cached probe lacks matching consumed native input closure"}
        rcs = {}
        for tag, deck in decks.items():
            try:
                rcs[tag] = int(deck.with_suffix(".rc").read_text().strip())
            except (OSError, ValueError):
                rcs[tag] = None
    else:
        _atomic.write_json(snapshot, {"native_inputs": native_inputs, "execution": execution_settings})
        rcs = _run_decks(decks, container, budget_s, workers, threads, wait_policy, tb_p.parent)
    native_outputs = {tag: {"returncode": rcs.get(tag), **{kind: {"path": str(path), "sha256": _sha(path)}
        for kind, path in (("log", deck.with_suffix(".log")), ("returncode_file", deck.with_suffix(".rc")),
                           ("capture", wdir / f"w_{tag}.txt"))}} for tag, deck in decks.items()}
    output_snapshot = wdir / "native-outputs.json"
    if reuse_records:
        try:
            previous_outputs = json.loads(output_snapshot.read_text())
        except (OSError, ValueError):
            previous_outputs = {}
        if previous_outputs != native_outputs:
            return RC_NO_RECORD, {"status": "NOT_MEASURED", "reason": "cached native output bytes differ from their terminal receipt"}
    else:
        _atomic.write_json(output_snapshot, native_outputs)
    runs: Dict[str, Any] = {}
    for tag in decks:
        w = read_wrdata(wdir / f"w_{tag}.txt", inst, vnets)
        if w is None:
            continue
        runs[tag] = clock_samples(w, {k: v for k, v in nets.items()},
                                  stages, period, t0, vhigh)
        runs[tag + "__wave"] = w
    fit_runs = [(vins[t], runs[t]) for t, _u in levels
                if t.startswith("fit_") and t in runs]
    rec: Dict[str, Any] = {
        "producer": PRODUCER, "schema": SCHEMA, "block": block,
        "structure_sha256": _a2.loop_structure_fingerprint(ir),
        "netlist": {"path": str(sp_p.relative_to(project)),
                    "sha256": _sha(sp_p)},
        "testbench": {"path": str(tb_p.relative_to(project)),
                      "sha256": _sha(tb_p)},
        "clock_period_s": period, "clocks": n_clk,
        "reference_half_span_v": half, "common_mode_nominal_v": vcm_nom,
        "levels": {t: {"u": u, "vin": vins[t],
                       "rc": rcs.get(t), "record": t in runs}
                   for t, u in levels},
        "elapsed_s": round(time.time() - started, 1),
        "container": container,
        "native_inputs": native_inputs, "execution": execution_settings, "native_outputs": native_outputs,
        "outputs": [str(path) for path in wdir.iterdir() if path.is_file()],
    }
    changed = [role for role, view in native_inputs.items() if _sha(Path(view["path"])) != view["sha256"]]
    import analog_real_corner_sweep as _sweep
    failed = [tag for tag, deck in decks.items() if (isinstance(rcs.get(tag), int) and rcs[tag] > 0 and
        rcs[tag] not in (130, 137, 143, 199)) or any(_sweep._scan_analysis_failures(
        deck.with_suffix(".log").read_text(errors="replace") if deck.with_suffix(".log").is_file() else ""))]
    interrupted = [tag for tag, deck in decks.items() if rcs.get(tag) is None or rcs.get(tag, 0) < 0 or
                   rcs.get(tag) in (130, 137, 143, 199) or not deck.with_suffix(".log").is_file()]
    if changed or failed or interrupted:
        rec.update(status="FAIL" if failed else "NOT_MEASURED", changed_inputs=changed, failed_native_cases=failed,
                   incomplete_native_cases=interrupted,
                   reason="native probe failed or consumed input bytes changed")
        return RC_FAIL if failed else RC_NO_RECORD, rec
    if len(fit_runs) < 3:
        rec["status"] = "NOT_MEASURED"
        rec["reason"] = "fewer than three fit levels produced a record"
        return RC_NO_RECORD, rec
    fit = fit_stages(fit_runs, len(stages))
    meas = ir.get("pdk_measured_params") or {}
    caps = netlist_capacitances(netlist,
                                float(meas.get("cap_area_ff_per_um2") or 0.0),
                                float(meas.get("cap_perim_ff_per_um") or 0.0))
    ratios = cap_ratios(decl, caps, len(stages))
    for f, r in zip(fit, ratios):
        f["cap_ratio_input"] = r["input"]
        f["cap_ratio_dac"] = r["dac"]
        if f.get("status") in ("MEASURED", "POOR_FIT"):
            f["gain_input_over_ratio"] = (f["input_coefficient"] / r["input"]
                                          if r["input"] else None)
            f["gain_dac_over_ratio"] = (f["dac_coefficient"] / r["dac"]
                                        if r["dac"] else None)
            f["offset_state_per_clock"] = f["offset_v_per_clock"] / half
            dev = [abs(g - 1.0) for g in (f["gain_input_over_ratio"],
                                          f["gain_dac_over_ratio"])
                   if g is not None]
            f["within_ratio_tolerance"] = bool(dev) and max(dev) <= \
                _a2._res.COEFFICIENT_RATIO_TOLERANCE
    rec["stages"] = fit
    rec["status"] = ("MEASURED" if all(f.get("status") == "MEASURED"
                                       for f in fit)
                     else "PARTIALLY_MEASURED")
    rc = RC_OK
    if validate:
        frac = (ir.get("constants") or {}).get(
            "integrator_swing_fraction_of_vdd")
        vdd_min = sv.get("vdd_min", sv.get("vdd"))
        lim = (float(frac) * float(vdd_min) / 2.0) if frac and vdd_min \
            else None
        exc: Dict[str, List[float]] = {}
        for tag in ("span_pos", "span_neg"):
            w = runs.get(tag + "__wave")
            if w is None:
                continue
            t = w["t"]
            t_start = t0 + SKIP_CLOCKS * period
            vcm_w = w["v"][nets["common_mode"]]
            exc[tag] = [max(abs(y - c) for tt, y, c in
                            zip(t, w["v"][s], vcm_w) if tt >= t_start)
                        for s in stages]
        comp = []
        for s in range(len(stages)):
            lin = next((f["dac_coefficient"] for f in fit
                        if f["stage"] == s + 1
                        and f.get("status") == "MEASURED"), None)
            for tag in ("span_pos", "span_neg"):
                if tag in runs and lin:
                    a_run = per_run_dac(runs[tag], vins[tag], s)
                    if a_run is not None:
                        comp.append({"stage": s + 1, "level": tag,
                                     "dac_coefficient": a_run,
                                     "linear_fit": lin,
                                     "compression": abs(a_run - lin) / lin})
        swing_ok = (lim is not None and len(exc) == 2 and
                    all(max(v) <= lim for v in exc.values()))
        comp_ok = bool(comp) and all(c["compression"] <= MAX_DAC_COMPRESSION
                                     for c in comp)
        rec["validation"] = {
            "u_decl": u_decl, "excursion_limit_v": lim,
            "excursion_about_vcm_v": exc,
            "dac_compression": comp,
            "max_dac_compression": MAX_DAC_COMPRESSION,
            "swing_within_limit": swing_ok,
            "dac_compression_within_limit": comp_ok,
            "verdict": "PASS" if (swing_ok and comp_ok) else "FAIL",
        }
        rc = RC_OK if (swing_ok and comp_ok) else RC_FAIL
    for k in [k for k in runs if k.endswith("__wave")]:
        runs.pop(k)
    return rc, rec


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--container", default=_os.environ.get(
        "VIBEIC_EDA_CONTAINER", "vibeic-eda"))
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--clocks", type=int, default=None)
    ap.add_argument("--reuse-records", action="store_true",
                    help="re-analyse the records a previous run of this "
                         "probe wrote, without simulating")
    ap.add_argument("--budget-s", type=float, default=14400.0,
                    help="recorded budget; its crossing is announced, it "
                         "stops nothing")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--wait-policy", choices=("PASSIVE", "ACTIVE"), default=None)
    a = ap.parse_args(argv)
    project = a.project.resolve()
    rc, rec = probe(project, a.block, a.container, a.validate, a.clocks,
                    a.budget_s, a.reuse_records, a.workers, a.threads, a.wait_policy)
    if rc != RC_NA:
        name = VALIDATION_ARTEFACT if a.validate else FIT_ARTEFACT
        _atomic.write_json(project / "phase3" / "analog" / a.block / name,
                           rec)
    print(f"{PRODUCER}: {a.block} {rec.get('status')}"
          + (f" validation={rec['validation']['verdict']}"
             if rec.get("validation") else "")
          + (f" ({rec.get('reason')})" if rec.get("reason") else ""))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
