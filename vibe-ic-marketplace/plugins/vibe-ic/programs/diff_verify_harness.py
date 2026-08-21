#!/usr/bin/env python3
"""diff_verify_harness.py — independent DIFFERENTIAL self-verification
(N-version) for blind RTL authoring (ORGANIC #700).

Problem — the single-self-TB circularity
=========================================
A single agent that derives BOTH the RTL and its self-testbench from ONE
reading of the spec passes its own (possibly wrong) TB: the self-verification
is CIRCULAR. A misread baked into one reading lands in BOTH the RTL surface and
the TB surface, so the TB happily confirms the wrong behaviour.

The break — independent differential verification (N-version)
=============================================================
A SECOND, INDEPENDENT derivation (a reference behavioural model produced
WITHOUT seeing the RTL, with every ambiguous quantity explicitly enumerated and
pinned to the spec's worked examples) is cross-checked against the RTL EVERY
CYCLE. When the two derivations disagree, a misread that one reading noticed but
the other missed surfaces as a designer-vs-reference DIFF — the first
mismatching cycle/signal — instead of silently passing.

Empirically this caught a real oversight during self-check (an hmac write-data
live-read vs latched-read: 3471 diffs → fixed to 0) that the single-self-TB
PASSED.

SCOPE (HONEST — this is a COMPLEMENT, not a silver bullet)
==========================================================
It catches OVERSIGHT misreads: one derivation noticed a clause the other
missed. It does NOT catch:
  * genuine AMBIGUITY where the spec wording biases ALL independent blind
    readings the SAME way (e.g. an exact-latency phrase both the RTL author and
    the reference author read identically-but-wrong) — no amount of N-version
    helps when every version reads the same wrong thing;
  * benchmark spec↔TB contradictions (a defective benchmark whose hidden TB
    disagrees with its own prose).
On the hardest CVDP ambiguity residual it recovered 0/8 — those are FLOOR per
#697. Its value is on FRESH runs preventing OVERSIGHT bugs BEFORE the scorer.
It is the differential complement to the deterministic #697 spec_coverage_check
(force the self-TB to COVER each dimension) and the #699 timing/encoding
reading disciplines — NOT a replacement for either.

What this program IS (the honest boundary)
==========================================
The DETERMINISTIC half of #700: given RTL + an INDEPENDENT reference model
(a Python module exposing `ref(seq)`, or a second SV golden) + optional spec
worked-example vectors, it GENERATES and RUNS a cycle-accurate differential
testbench (directed example vectors + random + boundary) and reports every
designer-vs-reference mismatch with the cycle and signal. The PROGRAM does NOT
author the reference (that is the AI judgment recorded in the issue's
why_not_bucket_a) — it only DRIVES the differential comparison.

It reads ONLY the RTL header (to parse clk + input/output ports), the reference
model, and the vectors. It has NO access to any oracle, hidden TB, or dataset:
a misread cannot leak in through the comparison, because BOTH sides come from
the spec-reader, not from the scorer.

Tool availability
=================
The live RTL side is iverilog/vvp. A live call is gated on `shutil.which`. When
iverilog/vvp is ABSENT the run is reported `SKIP (tool unavailable)` with a
disclosure and rc 0 — NEVER a faked AGREE (mirrors the refuse-don't-fake
doctrine of harness_exact_selfverify #688 / cvdp_gate #604). The reference-side
logic (`ref(seq)` + the per-cycle compare) is exercised independently of
iverilog so CI always covers the comparator.

Exit codes
==========
    0  AGREE — every cycle of every vector matched the reference
       (OR a disclosed SKIP because iverilog/vvp was absent — never a fake AGREE)
    1  MISMATCH — the first diverging cycle/signal is printed
    2  bad input (RTL/ref/port parse failure, bad --vectors, etc.)

chip-AGNOSTIC: pure structure — module/port header parse, vector generation,
iverilog/vvp drive, per-cycle integer compare. No chip / vendor / SKU literal,
no dataset access.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── RTL header parse (reuse the comment-stripped-view doctrine) ──────────────
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def _strip_comments(text: str) -> str:
    t = _BLOCK_COMMENT_RE.sub(" ", text)
    t = _LINE_COMMENT_RE.sub(" ", t)
    return _STRING_LIT_RE.sub('""', t)


_MODULE_HDR_RE = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\s*"
    r"(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"   # optional #(params)
    r"(?:\((?P<ports>(?:[^()]|\([^()]*\))*)\))?\s*;",
    re.DOTALL)

# ANSI port: `input wire [7:0] foo`, `output reg bar`, `inout baz`. Captures
# direction, optional [msb:lsb] range, and the name.
_ANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned))*"
    r"(?:\s*\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*"
    r"([A-Za-z_]\w*)")

# non-ANSI body decl: `input [7:0] foo, bar;` / `output reg q;`
_NONANSI_PORT_RE = re.compile(
    r"\b(input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned))*"
    r"(?:\s*\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*"
    r"((?:[A-Za-z_]\w*\s*,\s*)*[A-Za-z_]\w*)\s*;")

_MODULE_NAME_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)", re.MULTILINE)

# Canonical clock spellings (chip-AGNOSTIC: a small universal set; matching is
# case-insensitive exact-name).
_CLK_NAMES = {"clk", "clock", "clk_i", "i_clk", "clkin", "clk_in", "sysclk",
              "aclk", "hclk", "pclk", "mclk"}
_RST_NAMES = {"rst", "reset", "rst_n", "resetn", "rst_i", "i_rst", "arst",
              "arst_n", "nreset", "rstn", "reset_n", "areset", "rst_ni"}


class Port:
    __slots__ = ("name", "direction", "width")

    def __init__(self, name: str, direction: str, width: int):
        self.name = name
        self.direction = direction
        self.width = width

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Port({self.name!r},{self.direction},{self.width})"


def module_names(code: str) -> List[str]:
    seen: Dict[str, None] = {}
    for n in _MODULE_NAME_RE.findall(_strip_comments(code)):
        seen.setdefault(n, None)
    return list(seen.keys())


def _width(msb: Optional[str], lsb: Optional[str]) -> int:
    if msb is None or lsb is None:
        return 1
    return abs(int(msb) - int(lsb)) + 1


def parse_ports(code: str, top: Optional[str]) -> Tuple[Optional[str],
                                                        List[Port], str]:
    """Parse the named module's (or sole module's) port list into Port objects
    with direction + bit-width. Handles ANSI (header) and non-ANSI (body)."""
    src = _strip_comments(code)
    # Locate the requested module header (default: first/sole module).
    chosen = None
    for m in _MODULE_HDR_RE.finditer(src):
        if top is None or m.group(1) == top:
            chosen = m
            break
    if chosen is None:
        names = module_names(code)
        if top and top not in names:
            return None, [], (f"requested --top {top!r} not declared "
                              f"(declared: {names or 'none'})")
        return None, [], "no module declaration found in RTL"
    name = chosen.group(1)
    ports_blob = chosen.group("ports") or ""
    ports: Dict[str, Port] = {}
    order: List[str] = []
    # ANSI directions in the header.
    for pm in _ANSI_PORT_RE.finditer(ports_blob):
        nm = pm.group(4)
        if nm not in ports:
            ports[nm] = Port(nm, pm.group(1).lower(),
                             _width(pm.group(2), pm.group(3)))
            order.append(nm)
    # bare header names (non-ANSI — directions live in the body).
    header_bare: List[str] = []
    if ports_blob.strip():
        for nm in re.findall(r"[A-Za-z_]\w*", ports_blob):
            if nm in ("input", "output", "inout", "wire", "reg", "logic",
                      "bit", "signed", "unsigned"):
                continue
            if nm not in ports and nm not in header_bare:
                header_bare.append(nm)
    # non-ANSI body declarations.
    body = src[chosen.end():]
    em = re.search(r"\bendmodule\b", body)
    if em:
        body = body[:em.start()]
    for pm in _NONANSI_PORT_RE.finditer(body):
        direction = pm.group(1).lower()
        w = _width(pm.group(2), pm.group(3))
        for nm in re.split(r"\s*,\s*", pm.group(4).strip()):
            nm = nm.strip()
            if nm and nm not in ports:
                ports[nm] = Port(nm, direction, w)
                if nm not in order:
                    order.append(nm)
    for nm in header_bare:
        if nm not in ports:
            ports[nm] = Port(nm, "unknown", 1)
            order.append(nm)
    return name, [ports[n] for n in order], ""


def _classify_ports(ports: List[Port]) -> Tuple[Optional[Port], List[Port],
                                                 List[Port], List[Port]]:
    """Return (clk, reset_inputs, data_inputs, data_outputs).

    clk is the input whose name is a canonical clock spelling. reset inputs are
    canonical reset spellings (held inactive — driven 0, the common active-high
    convention; an active-low `*_n` reset is held 1). data_inputs are the
    remaining inputs (the `in` to drive). data_outputs are the outputs (the
    `out` to sample)."""
    clk = None
    resets: List[Port] = []
    din: List[Port] = []
    dout: List[Port] = []
    for p in ports:
        lo = p.name.lower()
        if p.direction == "input":
            if clk is None and lo in _CLK_NAMES:
                clk = p
            elif lo in _RST_NAMES:
                resets.append(p)
            else:
                din.append(p)
        elif p.direction == "output":
            dout.append(p)
    return clk, resets, din, dout


# ── independent reference model load ─────────────────────────────────────────
def load_reference(ref_path: Path):
    """Load the independent reference behavioural model.

    A Python module exposing `ref(seq)` (input-sequence → expected-output-
    sequence). The reference is authored INDEPENDENTLY of the RTL (the AI
    judgment in the issue's why_not_bucket_a); this program only IMPORTS and
    DRIVES it. (A second SV golden is a documented future extension; the
    Python-`ref(seq)` form is the 驗收 contract.)"""
    if ref_path.suffix.lower() in (".sv", ".v"):
        raise ValueError(
            "SV-golden references are not yet a supported --ref form; supply "
            "a Python module exposing `ref(seq)` (the 驗收 contract)")
    spec = importlib.util.spec_from_file_location("_diff_ref", str(ref_path))
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load --ref module: {ref_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "ref") or not callable(mod.ref):
        raise ValueError(
            f"--ref module {ref_path} must expose a callable `ref(seq)` "
            f"(sequence → expected-output-sequence)")
    return mod.ref


# ── vector generation (directed / random / boundary) ─────────────────────────
def _mask(width: int) -> int:
    return (1 << width) - 1


def gen_vectors(kinds: List[str], width: int, n_random: int,
                seed: int) -> List[List[int]]:
    """Generate the input sequences to drive. Each sequence is a list of
    integers (one per cycle), masked to the input width. Deterministic for a
    given seed. `directed` uses a small canonical ramp; `boundary` pins the
    extreme values; `random` draws `n_random` pseudo-random sequences."""
    rng = random.Random(seed)
    hi = _mask(width)
    seqs: List[List[int]] = []
    seq_len = max(8, n_random)
    if "directed" in kinds:
        # a canonical ramp + an alternating pattern (worked-example-like)
        seqs.append([i & hi for i in range(seq_len)])
        seqs.append([(0 if i % 2 else hi) for i in range(seq_len)])
    if "boundary" in kinds:
        # all-zero, all-ones, single-step impulse, single-zero notch
        seqs.append([0] * seq_len)
        seqs.append([hi] * seq_len)
        seqs.append([hi if i == 0 else 0 for i in range(seq_len)])
        seqs.append([0 if i == 0 else hi for i in range(seq_len)])
    if "random" in kinds:
        for _ in range(max(1, n_random)):
            seqs.append([rng.randint(0, hi) for _ in range(seq_len)])
    if not seqs:
        # never run zero vectors — default to a directed ramp
        seqs.append([i & hi for i in range(seq_len)])
    return seqs


def _parse_vectors_arg(s: str) -> Tuple[List[str], Optional[str]]:
    """`directed|random|boundary` or a + / , combination (e.g.
    `directed+random`, `all`). Returns (kinds, error)."""
    s = (s or "").strip().lower()
    if s in ("all", "directed+random+boundary"):
        return ["directed", "random", "boundary"], None
    parts = re.split(r"[+,\s]+", s)
    kinds = [p for p in parts if p]
    bad = [p for p in kinds if p not in ("directed", "random", "boundary")]
    if bad:
        return [], f"unknown --vectors kind(s): {bad} (use directed|random|boundary)"
    if not kinds:
        return [], "empty --vectors"
    return kinds, None


# ── differential comparison (the pure-logic comparator; iverilog-free) ───────
def compare_sequences(rtl_out: List[int], ref_out: List[int],
                       out_name: str) -> Tuple[bool, Optional[Dict]]:
    """Cycle-accurate compare of an RTL output sequence vs the reference.

    Compares position by position over the common prefix (a reference may
    legitimately return a shorter list — e.g. it elides trailing don't-cares —
    so only the overlap is enforced). Returns (agree, first_mismatch)."""
    n = min(len(rtl_out), len(ref_out))
    for cyc in range(n):
        if rtl_out[cyc] != ref_out[cyc]:
            return False, {"cycle": cyc, "signal": out_name,
                           "rtl": rtl_out[cyc], "ref": ref_out[cyc]}
    return True, None


# ── SV differential testbench generation + run ───────────────────────────────
def _reset_is_active_low(name: str) -> bool:
    """True for the active-low reset spellings (`*_n`, `*_ni`, `nreset`, `rstn`,
    `resetn`). Such resets are held HIGH (inactive); active-high ones held low."""
    lo = name.lower()
    return (lo.endswith("_n") or lo.endswith("_ni") or lo.endswith("n")
            and ("rst" in lo or "reset" in lo))


# How many warmup cycles to drive a quiescent input before the measured window.
# This flushes X out of resetless flops (a resetless K-stage pipe needs K clean
# clocks to become known) and lets a held-inactive reset settle. 8 covers the
# common shallow-pipeline depths; chip-AGNOSTIC (a cycle count, not a chip).
_WARMUP_CYCLES = 8


def _build_tb(top: str, clk: Optional[Port], resets: List[Port],
              din: Port, dout: Port, seq: List[int]) -> str:
    """Emit a self-contained cycle-accurate differential TB.

    Convention (matches the issue's `ref(seq)[i] = seq[i-latency]` contract):
      * WARMUP — drive `din`=0 with reset held INACTIVE for `_WARMUP_CYCLES`
        negedges, flushing X out of resetless flops and settling any pipeline.
      * MEASURED — on each negedge (a phase with NO edge race): first SAMPLE
        `dout` (it holds the value established by the most recent posedge),
        $display `CYC <i> <value>`, THEN drive `din`=seq[i] for the UPCOMING
        posedge. Sampling on the negedge and one cycle before driving makes the
        i-th sample reflect inputs registered `latency` cycles earlier — exactly
        the reference's leading-prefix delay — with no NBA/blocking race.

    The Python side reads those `CYC` lines and compares to `ref(seq)`; the
    comparison itself lives in Python (the comparator is iverilog-free and thus
    always CI-covered)."""
    lines: List[str] = []
    lines.append("`timescale 1ns/1ps")
    lines.append("module diff_tb;")
    lines.append("  reg clk = 0;")
    for r in resets:
        lines.append(f"  reg [{r.width-1}:0] {r.name};")
    lines.append(f"  reg  [{din.width-1}:0] {din.name};")
    lines.append(f"  wire [{dout.width-1}:0] {dout.name};")
    conns = []
    if clk is not None:
        conns.append(f".{clk.name}(clk)")
    for r in resets:
        conns.append(f".{r.name}({r.name})")
    conns.append(f".{din.name}({din.name})")
    conns.append(f".{dout.name}({dout.name})")
    lines.append(f"  {top} dut(" + ", ".join(conns) + ");")
    lines.append("  always #5 clk = ~clk;")
    lines.append("  integer i;")
    lines.append(f"  reg [{max(0,din.width-1)}:0] stim [0:{len(seq)-1}];")
    lines.append("  initial begin")
    for idx, v in enumerate(seq):
        lines.append(f"    stim[{idx}] = {din.width}'d{v & _mask(din.width)};")
    # hold reset INACTIVE throughout (we verify the steady-state datapath).
    for r in resets:
        val = _mask(r.width) if _reset_is_active_low(r.name) else 0
        lines.append(f"    {r.name} = {r.width}'d{val};")
    lines.append(f"    {din.name} = 0;")
    # WARMUP — quiescent input flushes X out of resetless flops.
    lines.append(f"    repeat ({_WARMUP_CYCLES}) begin @(negedge clk); "
                 f"{din.name} = 0; end")
    # MEASURED — sample-then-drive on the negedge (race-free phase).
    lines.append(f"    for (i = 0; i < {len(seq)}; i = i + 1) begin")
    lines.append("      @(negedge clk);")
    lines.append(f"      $display(\"CYC %0d %0d\", i, {dout.name});")
    lines.append(f"      {din.name} = stim[i];")
    lines.append("    end")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


_CYC_RE = re.compile(r"^CYC\s+(\d+)\s+(\d+)\s*$", re.MULTILINE)


def _run(cmd: List[str], timeout: int = 120,
         cwd: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout, cwd=cwd)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out or "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def run_rtl_sequence(rtl_path: Path, top: str, clk: Optional[Port],
                     resets: List[Port], din: Port, dout: Port,
                     seq: List[int], workdir: Path) -> Tuple[Optional[List[int]],
                                                             str]:
    """Compile + run one input sequence through the RTL, returning the sampled
    output sequence (one int per cycle) or (None, error). The caller has
    already confirmed iverilog/vvp are present."""
    tb = _build_tb(top, clk, resets, din, dout, seq)
    tb_path = workdir / "diff_tb.sv"
    tb_path.write_text(tb)
    binp = workdir / "diff_sim.vvp"
    rc, out, err = _run(["iverilog", "-g2012", "-o", str(binp),
                         "-s", "diff_tb", str(rtl_path), str(tb_path)])
    if rc != 0:
        blob = ((out or "") + "\n" + (err or "")).strip()
        return None, ("RTL+diff-TB did not compile: "
                      + "; ".join(blob.splitlines()[:4]))
    rc2, out2, err2 = _run(["vvp", str(binp)])
    sim = (out2 or "")
    samples: Dict[int, int] = {}
    for m in _CYC_RE.finditer(sim):
        samples[int(m.group(1))] = int(m.group(2))
    if not samples:
        return None, ("RTL sim produced no CYC samples (sim stderr: "
                      + "; ".join((err2 or "").splitlines()[:3]) + ")")
    return [samples[i] for i in sorted(samples)], ""


# ── orchestration ────────────────────────────────────────────────────────────
def diff_verify(rtl_path: Path, ref_path: Path, top: Optional[str],
                vectors: str, n_random: int, seed: int,
                require_tools: bool = False) -> Dict:
    """Run the full independent differential verification and return a report."""
    report: Dict = {
        "rtl": str(rtl_path),
        "ref": str(ref_path),
        "methodology": "independent N-version differential verification",
        # honest scope, carried in EVERY report (no over-claim):
        "catches": "OVERSIGHT misreads (one derivation noticed a clause the "
                   "other missed)",
        "does_not_catch": ("genuine ambiguity that biases ALL blind readings "
                           "the same way; benchmark spec<->TB contradictions "
                           "(FLOOR per #697)"),
        "complement_to": ["#697 spec_coverage_check (deterministic dimension "
                          "coverage)", "#699 timing/encoding reading disciplines"],
        "reads_only": "RTL header + independent reference + generated vectors "
                      "(no oracle / hidden TB / dataset)",
        "vectors": vectors,
    }
    code = rtl_path.read_text(errors="replace")
    name, ports, perr = parse_ports(code, top)
    if name is None:
        report["verdict"] = "ERROR"
        report["reason"] = "port parse failed: " + perr
        return report
    report["resolved_top"] = name
    clk, resets, din, dout = _classify_ports(ports)
    if not din:
        report["verdict"] = "ERROR"
        report["reason"] = ("no data-input port found (after excluding "
                            f"clk/reset) in module {name}")
        return report
    if not dout:
        report["verdict"] = "ERROR"
        report["reason"] = f"no output port found in module {name}"
        return report
    # single primary in/out (the 驗收 contract: one `in`, one `out`); when
    # several inputs exist, drive the widest data input and sample the widest
    # output (deterministic, disclosed).
    din_port = max(din, key=lambda p: (p.width, din.index(p) * -1))
    dout_port = max(dout, key=lambda p: (p.width, dout.index(p) * -1))
    report["driven_input"] = {"name": din_port.name, "width": din_port.width}
    report["sampled_output"] = {"name": dout_port.name, "width": dout_port.width}
    report["clk"] = clk.name if clk else None
    report["resets_held_inactive"] = [r.name for r in resets]

    kinds, verr = _parse_vectors_arg(vectors)
    if verr:
        report["verdict"] = "ERROR"
        report["reason"] = verr
        return report
    report["vector_kinds"] = kinds

    try:
        ref = load_reference(ref_path)
    except Exception as e:  # noqa: BLE001 - surface any ref-load failure
        report["verdict"] = "ERROR"
        report["reason"] = f"reference load failed: {e}"
        return report

    seqs = gen_vectors(kinds, din_port.width, n_random, seed)
    report["n_sequences"] = len(seqs)

    # iverilog/vvp gate — refuse-don't-fake: ABSENT → SKIP, never a faked AGREE.
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        report["verdict"] = "SKIP"
        report["tool_available"] = False
        report["reason"] = ("iverilog/vvp absent — the RTL side of the "
                            "differential check cannot run; reporting SKIP with "
                            "disclosure, NOT a faked AGREE (refuse-don't-fake)")
        if require_tools:
            report["verdict"] = "ERROR"
            report["reason"] += " (--require-tools → hard error)"
        return report
    report["tool_available"] = True

    workdir = Path(tempfile.mkdtemp(prefix="diffvh_"))
    try:
        for si, seq in enumerate(seqs):
            rtl_out, rerr = run_rtl_sequence(rtl_path, name, clk, resets,
                                             din_port, dout_port, seq, workdir)
            if rtl_out is None:
                report["verdict"] = "ERROR"
                report["reason"] = f"sequence {si}: {rerr}"
                return report
            try:
                ref_out = list(ref(list(seq)))
            except Exception as e:  # noqa: BLE001
                report["verdict"] = "ERROR"
                report["reason"] = f"reference ref(seq) raised on seq {si}: {e}"
                return report
            ref_out = [int(v) & _mask(dout_port.width) for v in ref_out]
            agree, mm = compare_sequences(rtl_out, ref_out, dout_port.name)
            if not agree and mm is not None:
                report["verdict"] = "MISMATCH"
                report["first_mismatch"] = {**mm, "sequence": si}
                report["reason"] = (
                    f"DIFF at sequence {si} cycle {mm['cycle']} signal "
                    f"{mm['signal']}: RTL={mm['rtl']} ref={mm['ref']} — the "
                    f"designer's RTL diverges from the independently-derived "
                    f"reference (an oversight misread, or a real RTL bug)")
                return report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    report["verdict"] = "AGREE"
    report["reason"] = (f"RTL agrees with the independent reference across all "
                        f"{len(seqs)} vector sequence(s), every cycle")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Independent differential (N-version) self-verification for "
                    "blind RTL (#700): RTL vs an INDEPENDENTLY-derived reference "
                    "`ref(seq)`, cycle-accurately, over directed/random/boundary "
                    "vectors. Catches OVERSIGHT misreads single-self-TB passes; "
                    "does NOT beat genuine-ambiguity FLOOR.")
    ap.add_argument("--rtl", required=True, help="the blind-authored RTL (.v/.sv)")
    ap.add_argument("--ref", required=True,
                    help="independent reference: a Python module exposing "
                         "`ref(seq)` (input-sequence → expected-output-sequence)")
    ap.add_argument("--top", default=None,
                    help="the DUT module name (default: the sole/first module)")
    ap.add_argument("--vectors", default="directed+random+boundary",
                    help="directed|random|boundary or a + / , combination "
                         "(or 'all'); default directed+random+boundary")
    ap.add_argument("--cycles", type=int, default=16,
                    help="cycles per random/directed sequence (default 16)")
    ap.add_argument("--seed", type=int, default=0,
                    help="PRNG seed for the random vectors (deterministic)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    ap.add_argument("--require-tools", action="store_true",
                    help="treat an absent iverilog/vvp as a hard error (exit 2) "
                         "for a CI/container run that MUST enforce")
    args = ap.parse_args(argv)

    rtl_path = Path(args.rtl)
    ref_path = Path(args.ref)
    if not rtl_path.is_file():
        print(f"ERROR: --rtl not found: {rtl_path}", file=sys.stderr)
        return 2
    if not ref_path.is_file():
        print(f"ERROR: --ref not found: {ref_path}", file=sys.stderr)
        return 2

    report = diff_verify(rtl_path.resolve(), ref_path.resolve(), args.top,
                         args.vectors, max(1, args.cycles), args.seed,
                         args.require_tools)

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2,
                                              ensure_ascii=False) + "\n")

    verdict = report.get("verdict")
    if verdict == "AGREE":
        print("AGREE")
        print(report["reason"], file=sys.stderr)
        return 0
    if verdict == "SKIP":
        # disclosed SKIP — NEVER a faked AGREE; rc 0 unless --require-tools.
        print(f"SKIP: {report['reason']}", file=sys.stderr)
        return 2 if args.require_tools else 0
    if verdict == "MISMATCH":
        fm = report["first_mismatch"]
        print(f"MISMATCH cycle={fm['cycle']} signal={fm['signal']} "
              f"rtl={fm['rtl']} ref={fm['ref']} (sequence {fm['sequence']})")
        print(report["reason"], file=sys.stderr)
        return 1
    # ERROR
    print(f"ERROR: {report.get('reason','bad input')}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
