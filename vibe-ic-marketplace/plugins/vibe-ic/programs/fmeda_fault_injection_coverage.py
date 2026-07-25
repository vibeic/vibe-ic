#!/usr/bin/env python3
"""fmeda_fault_injection_coverage.py — REAL ISO-26262 FMEDA diagnostic-coverage
(DC) measurement by single-stuck-at FAULT INJECTION against a declared safety
mechanism (ECC / parity / lockstep).

WHAT THIS IS (and is NOT)
-------------------------
FMEDA (Failure Modes, Effects and Diagnostic Analysis) needs, per safety
mechanism, a measured DIAGNOSTIC COVERAGE:

    DC = detected_faults / injected_faults

This is NOT ATPG. `fault_atpg_run.py` answers "can ATE generate a pattern that
observes this stuck-at at a primary output" (manufacturing test). FMEDA DC
answers a DIFFERENT question: "when a single-point fault occurs in the PROTECTED
data path during operation, does the SAFETY MECHANISM (the ECC syndrome / the
parity-error flag / the lockstep-mismatch flag) DETECT (or correct) it?" That is
a fault-INJECTION simulation, not pattern generation.

METHOD — a REAL inject→simulate→observe loop (iverilog / vvp)
------------------------------------------------------------
For a mechanism whose protected data path is an N-bit codeword:

  for each stimulus data value d (swept or pseudo-random):
      code = ENCODE(d)                       # a valid, fault-free codeword
      GOLDEN: decode(code) must NOT flag and must return d   (baseline sanity)
      for each codeword bit i in [0, N):
          faulted = code ^ (1<<i)            # ONE single stuck-at / bit-flip
          {data_out, detect} = DECODE(faulted)
          covered = detect || (data_out == d)   # flagged OR corrected/masked

  DC = covered_injections / total_injections

Node-AGNOSTIC: the fault is injected on the wire BETWEEN encode and decode (or
on the decoder's protected input port), so no RTL is modified and the same
engine grades any ECC/parity/lockstep mechanism whose checker exposes a detect
flag and/or a corrected output. The engine is driven by a rendered testbench
that prints one `FAULT <id> DETECT <0|1> MATCH <0|1>` line per injection plus a
`GOLDEN ...` baseline; the DC math + verdict are pure and unit-tested.

DETECTION criterion (general): a fault is COVERED if the mechanism EITHER
  (a) asserts its error/detect/syndrome flag (DETECT=1), OR
  (b) still returns the correct functional value (MATCH=1 — corrected/masked).
An injection with DETECT=0 AND MATCH=0 is an ESCAPE (undetected) and honestly
lowers DC.

VACUOUS / NOT-APPLICABLE: a design that declares NO safety mechanism produces
NOT_APPLICABLE (vacuous pass — this step only fires for safety designs). It is
NEVER a fabricated pass and NEVER a fake number.

ASIL floor (single-point-fault-metric SPFM proxy via measured DC):
    ASIL-A : none required (advisory)
    ASIL-B : DC >= 90 %
    ASIL-C : DC >= 97 %
    ASIL-D : DC >= 99 %
(ISO-26262-5 Table 4-ish DC bands — "medium">=90%, "high">=99%; the ASIL-C 97%
is a defensible interpolation. Disclosed + overridable via --asil / --min-dc.)

HONEST RESIDUAL: a FULL FMEDA also needs base-failure-rate (FIT / lambda)
apportionment per failure mode from a reliability database (IEC 62380 / SN 29500
/ foundry data) to roll DC up into SPFM / LFM / PMHF. That reliability data is a
commercial/methodology input, not an EDA measurement. This program delivers the
MEASURED-DC half (the fault-grading engine); it never fabricates the FIT half.

USAGE
-----
  # auto-detect the mechanism from an RTL dir, then inject:
  python3 fmeda_fault_injection_coverage.py <project> --rtl-dir phase2/stage1/rtl \\
      --asil D [--json <out>]

  # explicit mechanism wiring (what the flow passes):
  python3 fmeda_fault_injection_coverage.py <project> \\
      --enc-module hamming_enc --enc-in data_in --enc-out code_out \\
      --dec-module hamming_dec --dec-in code_in --dec-out data_out \\
      --detect-port err --data-width 4 --code-width 7 \\
      --rtl-file phase2/stage1/rtl/ecc.v --asil D

EXIT CODES
----------
  0 — DC >= ASIL floor AND baseline valid  (OR NOT_APPLICABLE vacuous skip)
  1 — DC < ASIL floor OR baseline invalid (false-alarm / can't encode)
  2 — usage / IO / tool error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import _path_layout as _pl  # noqa: E402


# ─────────────────────────── ASIL floors ────────────────────────────────
# Measured-DC floor per ASIL, used as a defensible proxy for the ISO-26262
# single-point-fault-metric target. Disclosed in the report; overridable.
ASIL_DC_FLOOR: Dict[str, Optional[float]] = {
    "A": None,     # no quantitative DC target — advisory only
    "B": 90.0,     # "medium" diagnostic coverage
    "C": 97.0,     # interpolated between medium and high
    "D": 99.0,     # "high" diagnostic coverage
    "QM": None,    # quality-managed, no ASIL
}


def asil_floor(asil: str, min_dc_override: Optional[float] = None) -> Optional[float]:
    """Resolve the DC floor (percent) for an ASIL. An explicit --min-dc override
    always wins. Unknown ASIL → None (advisory). Pure."""
    if min_dc_override is not None:
        return float(min_dc_override)
    return ASIL_DC_FLOOR.get((asil or "").strip().upper(), None)


def compute_dc(detected: int, injected: int) -> float:
    """DC percent = 100 * detected / injected. injected==0 → 0.0 (no evidence is
    NOT full coverage). Pure, unit-tested."""
    if injected <= 0:
        return 0.0
    return 100.0 * float(detected) / float(injected)


def dc_verdict(dc_pct: float, floor: Optional[float]) -> Tuple[bool, str]:
    """(passed, reason). A None floor (ASIL-A/QM) is advisory → passes with an
    advisory note. Pure, unit-tested."""
    if floor is None:
        return True, (f"advisory: DC={dc_pct:.2f}% measured; ASIL has no "
                      f"quantitative DC floor (informational)")
    if dc_pct + 1e-9 >= floor:
        return True, f"DC={dc_pct:.2f}% >= floor {floor:.2f}%"
    return False, f"DC={dc_pct:.2f}% < floor {floor:.2f}%"


# ───────────────────── injection-result parsing ─────────────────────────
_GOLDEN_RE = re.compile(
    r"^GOLDEN\s+DATA\s+(\d+)\s+DETECT\s+([01])\s+MATCH\s+([01])", re.MULTILINE)
_FAULT_RE = re.compile(
    r"^FAULT\s+(\S+)\s+DETECT\s+([01])\s+MATCH\s+([01])", re.MULTILINE)


@dataclass
class Injection:
    fault_id: str
    detect: bool
    match: bool

    @property
    def covered(self) -> bool:
        # Covered if the mechanism flagged the fault OR still produced the
        # correct value (corrected / masked). Both are "handled" for DC.
        return self.detect or self.match


@dataclass
class InjectionResults:
    golden_ok: bool                       # every no-fault baseline: DETECT=0 & MATCH=1
    golden_count: int
    injections: List[Injection] = field(default_factory=list)
    baseline_notes: List[str] = field(default_factory=list)

    @property
    def injected(self) -> int:
        return len(self.injections)

    @property
    def detected(self) -> int:
        return sum(1 for x in self.injections if x.covered)

    @property
    def dc_pct(self) -> float:
        return compute_dc(self.detected, self.injected)

    def per_site(self) -> Tuple[int, int]:
        """(sites_covered, sites_total) collapsing the trailing `_b<i>` bit index
        of a `d<d>_b<i>` fault id: a SITE is covered if covered by >=1 stimulus."""
        by_site: Dict[str, bool] = {}
        for inj in self.injections:
            m = re.search(r"_b(\d+)$", inj.fault_id)
            site = f"b{m.group(1)}" if m else inj.fault_id
            by_site[site] = by_site.get(site, False) or inj.covered
        cov = sum(1 for v in by_site.values() if v)
        return cov, len(by_site)


def parse_injection_results(stdout: str) -> InjectionResults:
    """Parse the testbench transcript into structured injections + a baseline
    validity flag. Pure, unit-tested.

    A VALID baseline requires >=1 GOLDEN line and EVERY GOLDEN line to show
    DETECT=0 & MATCH=1 (a fault-free codeword must neither flag nor corrupt). A
    false-alarm baseline (DETECT=1 with no fault) means the harness/mechanism is
    broken and the DC number is meaningless → golden_ok=False (the caller FAILs
    instead of reporting a bogus DC)."""
    golden = _GOLDEN_RE.findall(stdout)
    notes: List[str] = []
    golden_ok = len(golden) > 0
    for d, det, mat in golden:
        if det != "0":
            golden_ok = False
            notes.append(f"golden data={d}: mechanism FALSE-ALARMED (DETECT=1) "
                         f"with no fault injected")
        if mat != "1":
            golden_ok = False
            notes.append(f"golden data={d}: fault-free decode MISMATCH "
                         f"(MATCH=0) — encoder/decoder not inverse")
    if not golden:
        notes.append("no GOLDEN baseline line emitted — cannot validate harness")
    injections = [
        Injection(fid, det == "1", mat == "1")
        for fid, det, mat in _FAULT_RE.findall(stdout)
    ]
    return InjectionResults(golden_ok=golden_ok, golden_count=len(golden),
                            injections=injections, baseline_notes=notes)


# ───────────────────── mechanism spec + auto-detect ─────────────────────
@dataclass
class MechanismSpec:
    kind: str                       # "ecc" | "parity" | "lockstep"
    enc_module: Optional[str]
    enc_in: str
    enc_out: str
    dec_module: str
    dec_in: str
    dec_out: Optional[str]          # corrected data output (None → no correction)
    detect_port: Optional[str]      # decoder output that flags an error (None → correction-only)
    data_width: int
    code_width: int
    rtl_files: List[str] = field(default_factory=list)
    source: str = "explicit"


# Whether an OUTPUT port name DECLARES an error-detection safety mechanism.
# Node-agnostic: keyed on the SAFETY SEMANTIC (syndrome / parity-error /
# ECC-error / mismatch / SECDED), never on a design name. Underscore-robust:
# `\b` sits at word chars, so `\bsyndrome\b` MISSES `syndrome_err` (`_` is a
# word char) — we match strong substrings AND per-component bare tokens instead.
_DETECT_STRONG_SUBSTR = (
    "syndrome", "mismatch", "uncorrect", "correctable", "secded", "sec_ded",
    "lockstep", "parity_err", "parityerr", "parity_error", "ecc_err", "eccerr",
    "err_detect", "errdetect", "error_detect", "err_flag", "errflag",
    "ce_flag", "ue_flag", "double_err", "single_err", "fault_detect",
)
_DETECT_BARE_TOKENS = {
    "err", "error", "errs", "errors", "detect", "detected", "fault",
    "derr", "serr", "perr", "synd", "syn",
}


def _is_detect_port(name: str) -> bool:
    """True iff a port name reads as an error/detect/syndrome flag. Component-
    aware so `syndrome_err`, `parity_error`, `ecc_err_o`, `mismatch`, and a bare
    `err`/`detect` all match, while a data bus (`data_out`, `interrupt`) does
    NOT. Pure, unit-tested via the auto-detect tests."""
    low = name.lower()
    for s in _DETECT_STRONG_SUBSTR:
        if s in low:
            return True
    for comp in re.split(r"[_\W0-9]+", low):
        if comp in _DETECT_BARE_TOKENS:
            return True
    return False

# Prose/L23 cues that a safety mechanism is DECLARED (used to gate auto-detect
# so a non-safety design skips as NOT_APPLICABLE rather than false-firing).
_SAFETY_DECL_RE = re.compile(
    r"(?i)\b(diagnostic\s+coverage|safety\s+mechanism|iso[-\s]?26262|"
    r"functional\s+safety|fmeda|asil[-\s]?[abcd]|lockstep|"
    r"single[-\s]?error\s+correct|sec[-\s]?ded|error\s+correcting\s+code|"
    r"\becc\b|parity\s+protect)")

_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)\s*", re.MULTILINE)

# The runner's reset/clock-variant alias suffix (design_one_shot_runner renames
# `<top>` → `<top>__rcvar_inner`). Two modules sharing the same base are the SAME
# logical block (a wrapper + its inner), never an encoder/decoder pair (#145).
_RCVAR_SUFFIX = "__rcvar_inner"


def _rcvar_base(mod: str) -> str:
    return mod[:-len(_RCVAR_SUFFIX)] if mod.endswith(_RCVAR_SUFFIX) else mod


def _module_ports(text: str, module: str) -> List[Tuple[str, str, int]]:
    """Best-effort port list (name, dir, width) for `module`. Handles ANSI
    `input [W-1:0] name` headers. Width defaults to 1. Pure-ish (regex)."""
    # isolate the module header up to the first ');'
    m = re.search(r"\bmodule\s+" + re.escape(module) + r"\b(.*?)\)\s*;",
                  text, re.DOTALL)
    body = m.group(1) if m else ""
    ports: List[Tuple[str, str, int]] = []
    for pm in re.finditer(
            r"(?i)\b(input|output|inout)\b\s*(?:reg|wire)?\s*"
            r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*([A-Za-z_]\w*)", body):
        d, hi, lo, name = pm.groups()
        w = (abs(int(hi) - int(lo)) + 1) if hi is not None else 1
        ports.append((name, d.lower(), w))
    return ports


def detect_safety_mechanism(rtl_dir: Path,
                            doc_text: str = "") -> Optional[MechanismSpec]:
    """Scan an RTL directory (+ optional L23/doc text) for a DECLARED ECC/parity
    safety mechanism and infer the encode/decode modules + protected ports.
    Returns None (→ NOT_APPLICABLE) when no mechanism is unambiguously pinned —
    §4.05 PARSE-OR-SKIP: a non-safety design must skip, never fake a pass.

    Recognises a decoder as a module with a protected (widest) input port AND a
    narrower corrected-DATA output that is PAIRED WITH an error-detection port
    whose NAME declares detection (syndrome/parity_err/...). A narrower data
    output on its OWN (an instruction/address decoder or mux) is NOT ECC; a bare
    detect flag on its own is NOT ECC either — the positive structure is BOTH, OR
    an explicit safety declaration (ISO-26262 / ASIL / ECC / parity / lockstep)
    in prose/L23, under which even a SEC-only correction-only decoder fires. An
    encoder is a module producing a WIDER output than its input. chip-AGNOSTIC.
    """
    if not rtl_dir.is_dir():
        return None
    vfiles = sorted(list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv")))
    if not vfiles:
        return None

    combined = doc_text + "\n"
    per_file: List[Tuple[Path, str]] = []
    for f in vfiles:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        per_file.append((f, t))
        combined += t + "\n"

    # Collect all modules and their ports across files.
    mods: Dict[str, Tuple[Path, List[Tuple[str, str, int]]]] = {}
    for f, t in per_file:
        for mod in _MODULE_RE.findall(t):
            if mod not in mods:
                mods[mod] = (f, _module_ports(t, mod))

    # Find a decoder: has a detect output OR (input wider than a narrower output).
    dec = None
    for mod, (f, ports) in mods.items():
        ins = [(n, w) for n, d, w in ports if d == "input"]
        outs = [(n, w) for n, d, w in ports if d == "output"]
        if not ins or not outs:
            continue
        detect_outs = [n for n, _ in outs if _is_detect_port(n)]
        data_ins = [(n, w) for n, w in ins if n.lower() not in _CLK_RST]
        if not data_ins:
            continue
        widest_in = max(data_ins, key=lambda x: x[1])
        # corrected-DATA output = the widest NON-detect output that is >1 bit
        # (a 1-bit output is a flag, never the recovered data bus) and narrower
        # than the protected codeword input.
        data_outs = [(n, w) for n, w in outs
                     if not _is_detect_port(n) and w > 1]
        # decoder heuristic: a detect output, or a corrected-data output that is
        # NARROWER than the protected codeword input.
        corr_out = None
        if data_outs:
            wide = max(data_outs, key=lambda x: x[1])
            if wide[1] < widest_in[1]:
                corr_out = wide
        if detect_outs or corr_out:
            dec = {
                "module": mod, "file": f,
                "in": widest_in[0], "code_width": widest_in[1],
                "detect": detect_outs[0] if detect_outs else None,
                "out": corr_out[0] if corr_out else None,
                "data_width": corr_out[1] if corr_out else widest_in[1],
            }
            break
    if dec is None:
        return None

    # §4.05 declared-mechanism gate (TIGHTENED, #145 → follow-up): a decoder-
    # SHAPED module counts as a SAFETY mechanism ONLY with POSITIVE ECC
    # structure — a real corrected-DATA output narrower than the codeword input
    # PAIRED WITH a syndrome/detect PORT (`dec["out"]` AND `dec["detect"]`: a
    # decoder that both recovers the data AND raises an error flag) — OR an
    # explicit safety declaration in prose/L23.
    #
    # A corrected-DATA output ALONE is NOT sufficient: a plain instruction /
    # address decoder or mux (wide input → narrower output, NO syndrome/detect
    # port) is structurally identical to an ECC correction decoder and would
    # otherwise be auto-paired into a phantom encoder/decoder and forced into an
    # ASIL-D FMEDA it can never satisfy — on a design that never declared any
    # functional-safety intent. (subservient: `serv_immdec`, the SERV 32-bit
    # immediate decoder → 5-bit `o_rd_addr`, auto-paired with `chip_top` as a
    # phantom ECC and FAILed at the default ASIL-D 99% floor, despite the design
    # declaring no ASIL/ECC/parity/lockstep anywhere.) A bare 1-bit detect /
    # `error` STATUS flag likewise remains insufficient on its own (#145 —
    # sha256 crypto accelerator). A genuine SEC-only ECC with no detect flag
    # still fires whenever the design DECLARES safety (the _SAFETY_DECL_RE arm).
    if not ((dec["out"] is not None and dec["detect"] is not None)
            or _SAFETY_DECL_RE.search(combined)):
        return None

    # Find an encoder: input == decoder data_width, output == code_width.
    enc = None
    for mod, (f, ports) in mods.items():
        if mod == dec["module"]:
            continue
        # #145 — never pair a module with its OWN reset/clock-variant alias: the
        # runner renames `<top>` → `<top>__rcvar_inner` (a wrapper + inner pair),
        # which is NOT an encoder/decoder pair.
        if _rcvar_base(mod) == _rcvar_base(dec["module"]):
            continue
        ins = [(n, w) for n, d, w in ports if d == "input" and n.lower() not in _CLK_RST]
        outs = [(n, w) for n, d, w in ports if d == "output"]
        if not ins or not outs:
            continue
        widest_out = max(outs, key=lambda x: x[1])
        narrow_in = min(ins, key=lambda x: x[1])
        if widest_out[1] > narrow_in[1]:
            enc = {"module": mod, "file": f,
                   "in": narrow_in[0], "out": widest_out[0],
                   "data_width": narrow_in[1], "code_width": widest_out[1]}
            break

    files = sorted({str(dec["file"])} | ({str(enc["file"])} if enc else set()))
    kind = "ecc" if (dec["out"] is not None or dec["detect"]) else "parity"
    return MechanismSpec(
        kind=kind,
        enc_module=enc["module"] if enc else None,
        enc_in=enc["in"] if enc else "",
        enc_out=enc["out"] if enc else "",
        dec_module=dec["module"],
        dec_in=dec["in"],
        dec_out=dec["out"],
        detect_port=dec["detect"],
        data_width=(enc["data_width"] if enc else dec["data_width"]),
        code_width=dec["code_width"],
        rtl_files=[str(Path(p).name) for p in files],
        source="auto-detected",
    )


_CLK_RST = {"clk", "clock", "clk_i", "rst", "reset", "rst_n", "rstn",
            "rst_i", "resetn", "arst", "arst_n", "en", "enable"}


# ─────────────────────── testbench rendering ────────────────────────────
def _stimulus_values(data_width: int, max_vectors: int = 64) -> List[int]:
    """Deterministic stimulus set. Sweep all 2^K when small; else a fixed
    pseudo-random-but-deterministic spread (LCG). Pure, unit-tested."""
    n = 1 << data_width
    if n <= max_vectors:
        return list(range(n))
    vals, x = [], 1
    mask = n - 1
    while len(vals) < max_vectors:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        v = x & mask
        if v not in vals:
            vals.append(v)
    return vals


def build_ecc_injection_tb(spec: MechanismSpec,
                           max_vectors: int = 64) -> str:
    """Render a self-contained iverilog testbench that injects one single-bit
    stuck-at fault per codeword bit per stimulus value and prints one
    `FAULT d<d>_b<i> DETECT <x> MATCH <x>` line + a `GOLDEN ...` baseline. The
    mechanism RTL is instantiated as-is; the fault is injected on the codeword
    wire BETWEEN encoder and decoder (non-invasive). Pure string builder.

    Requires an encoder to produce valid codewords; a decoder-only mechanism is
    unsupported by this builder (the caller must supply codeword stimulus). The
    detect flag is the decoder's declared detect port (tied 0 if absent, in which
    case coverage is correction-only via MATCH)."""
    if not spec.enc_module:
        raise ValueError("build_ecc_injection_tb needs an encoder module to "
                         "generate valid codewords")
    K, N = spec.data_width, spec.code_width
    vals = _stimulus_values(K, max_vectors)
    det = spec.detect_port
    dec_out = spec.dec_out
    lines: List[str] = []
    lines.append("// Auto-generated FMEDA fault-injection TB "
                 "(fmeda_fault_injection_coverage).")
    lines.append("`timescale 1ns/1ps")
    lines.append("module fmeda_fi_tb;")
    lines.append(f"    reg  [{K-1}:0] data;")
    lines.append(f"    wire [{N-1}:0] code;")
    lines.append(f"    reg  [{N-1}:0] faulted;")
    if dec_out:
        lines.append(f"    wire [{K-1}:0] dout;")
    if det:
        lines.append("    wire detect_w;")
    lines.append("    integer i, vi;")
    # encoder + decoder instances (named-port to be robust to port order)
    lines.append(f"    {spec.enc_module} u_enc (.{spec.enc_in}(data), "
                 f".{spec.enc_out}(code));")
    dec_conns = [f".{spec.dec_in}(faulted)"]
    if dec_out:
        dec_conns.append(f".{dec_out}(dout)")
    if det:
        dec_conns.append(f".{det}(detect_w)")
    lines.append(f"    {spec.dec_module} u_dec ({', '.join(dec_conns)});")
    # detect / match expressions
    detect_expr = "(|detect_w)" if det else "1'b0"
    match_expr = "(dout === data)" if dec_out else "1'b0"
    # stimulus memory
    lines.append(f"    reg [{K-1}:0] tv [0:{len(vals)-1}];")
    lines.append("    initial begin")
    for idx, v in enumerate(vals):
        lines.append(f"        tv[{idx}] = {K}'d{v};")
    lines.append(f"        for (vi = 0; vi < {len(vals)}; vi = vi + 1) begin")
    lines.append("            data = tv[vi];")
    lines.append("            #1;")
    lines.append("            faulted = code;")           # fault-free
    lines.append("            #1;")
    lines.append(f"            $display(\"GOLDEN DATA %0d DETECT %0d MATCH %0d\","
                 f" data, {detect_expr}, {match_expr});")
    lines.append(f"            for (i = 0; i < {N}; i = i + 1) begin")
    lines.append("                faulted = code ^ (1'b1 << i);")   # single stuck-at
    lines.append("                #1;")
    lines.append(f"                $display(\"FAULT d%0d_b%0d DETECT %0d MATCH %0d\","
                 f" data, i, {detect_expr}, {match_expr});")
    lines.append("            end")
    lines.append("        end")
    lines.append("        $finish;")
    lines.append("    end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# ───────────────────────── docker / iverilog ────────────────────────────
def _resolve_docker_image() -> str:
    env = os.environ.get("VIBEIC_EDA_IMAGE") or os.environ.get("IIC_EDA_IMAGE")
    if env:
        return env
    candidates = (
        "ghcr.io/vibeic/vibeic-eda:0.2.30",
        "vibeic-eda:0.2.30",
        "vibeic/vibeic-eda:0.2.30",
        "hpretl/iic-osic-tools:latest",
    )
    for img in candidates:
        try:
            r = subprocess.run(["docker", "image", "inspect", img],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                return img
        except Exception:
            pass
    return "ghcr.io/vibeic/vibeic-eda:0.2.30"


_IVERILOG_ROOT = "/foss/tools/iverilog"
_ENV_PREAMBLE = (
    f"export PATH={_IVERILOG_ROOT}/bin:/foss/tools/bin:$PATH && "
    f"export LD_LIBRARY_PATH={_IVERILOG_ROOT}/lib:${{LD_LIBRARY_PATH:-}} && "
)


def run_injection_iverilog(project: Path,
                           rtl_rel_files: List[str],
                           tb_rel: str,
                           tb_top: str = "fmeda_fi_tb",
                           timeout: int = 300,
                           image: Optional[str] = None
                           ) -> Tuple[int, str, str]:
    """Compile the mechanism RTL + generated TB with iverilog and run vvp inside
    vibeic-eda. Returns (exit, stdout, stderr). project mounted at /work."""
    image = image or _resolve_docker_image()
    vvp_out = f"{tb_rel}.vvp"
    srcs = " ".join(f"/work/{s}" for s in rtl_rel_files + [tb_rel])
    compile_cmd = (f"iverilog -g2012 -o /work/{vvp_out} -s {tb_top} {srcs}")
    run_cmd = f"vvp /work/{vvp_out}"
    full = _ENV_PREAMBLE + compile_cmd + " && " + run_cmd
    docker_cmd = [
        "docker", "run", "--rm", "--entrypoint", "bash",
        "-v", f"{project}:/work", image, "-c", full,
    ]
    try:
        r = subprocess.run(docker_cmd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "iverilog/vvp timed out"
    except FileNotFoundError:
        return 127, "", "docker binary not found"


# ─────────────────────────── report emit ────────────────────────────────
def build_report(spec: Optional[MechanismSpec],
                 results: Optional[InjectionResults],
                 asil: str,
                 floor: Optional[float],
                 tool_log: str = "") -> dict:
    """Pure report assembler. NOT_APPLICABLE when spec is None. NEVER fabricates
    a DC when the harness baseline is invalid (marks invalid + fails)."""
    if spec is None:
        return {
            "program": "fmeda_fault_injection_coverage",
            "applicable": False,
            "verdict": "NOT_APPLICABLE",
            "reason": "no declared safety mechanism (ECC/parity/lockstep) found "
                      "— FMEDA diagnostic-coverage step vacuously skipped",
            "asil": asil,
        }
    site_cov, site_tot = (results.per_site() if results else (0, 0))
    dc = results.dc_pct if results else 0.0
    baseline_ok = bool(results and results.golden_ok)
    if not baseline_ok:
        passed, reason = False, ("harness baseline INVALID (false-alarm or "
                                 "non-inverse encode/decode) — DC not "
                                 "trustworthy; FAIL rather than report a bogus "
                                 "number")
    else:
        passed, reason = dc_verdict(dc, floor)
    rep = {
        "program": "fmeda_fault_injection_coverage",
        "applicable": True,
        "mechanism_kind": spec.kind,
        "mechanism": {
            "encoder": spec.enc_module,
            "decoder": spec.dec_module,
            "protected_input": spec.dec_in,
            "detect_port": spec.detect_port,
            "corrected_output": spec.dec_out,
            "data_width": spec.data_width,
            "code_width": spec.code_width,
            "source": spec.source,
            "rtl_files": spec.rtl_files,
        },
        "asil": asil,
        "dc_floor_pct": floor,
        "fault_model": "single stuck-at (bit-flip) on protected data path",
        "detection_criterion": "detect_flag_asserted OR corrected_output_matches",
        "injected_faults": results.injected if results else 0,
        "detected_faults": results.detected if results else 0,
        "diagnostic_coverage_pct": round(dc, 4),
        "per_site_covered": site_cov,
        "per_site_total": site_tot,
        "per_site_dc_pct": round(compute_dc(site_cov, site_tot), 4),
        "baseline_valid": baseline_ok,
        "baseline_golden_count": results.golden_count if results else 0,
        "baseline_notes": results.baseline_notes if results else [],
        "ge_floor": passed,
        "verdict": "PASS" if passed else "FAIL",
        "reason": reason,
        "residual_note": (
            "MEASURED-DC half of FMEDA only. Full SPFM/LFM/PMHF roll-up needs "
            "base-FIT/lambda apportionment from a reliability database "
            "(IEC 62380 / SN 29500 / foundry) — a commercial/methodology input, "
            "not fabricated here."),
    }
    if not (results and results.golden_ok) and tool_log:
        rep["tool_log_tail"] = tool_log[-1200:]
    # per-fault list (bounded) for auditability
    if results:
        rep["fault_list"] = [
            {"id": inj.fault_id, "detect": inj.detect, "match": inj.match,
             "covered": inj.covered}
            for inj in results.injections[:512]
        ]
        rep["fault_list_truncated"] = len(results.injections) > 512
    return rep


def _report_path(project: Path, override: Optional[str]) -> Path:
    if override:
        return Path(override)
    return _pl.reports_phase2_dir(project) / "safety" / "fmeda_coverage.json"


# ──────────────────────────────── main ──────────────────────────────────
def run(project: Path, args) -> Tuple[int, dict]:
    # 1) resolve the mechanism spec: explicit flags win; else auto-detect.
    spec: Optional[MechanismSpec] = None
    if args.dec_module and args.enc_module:
        rtl_files = list(args.rtl_file or [])
        spec = MechanismSpec(
            kind="ecc",
            enc_module=args.enc_module, enc_in=args.enc_in, enc_out=args.enc_out,
            dec_module=args.dec_module, dec_in=args.dec_in, dec_out=args.dec_out,
            detect_port=args.detect_port,
            data_width=args.data_width, code_width=args.code_width,
            rtl_files=[str(Path(p).name) for p in rtl_files],
            source="explicit",
        )
        spec_rtl_rel = rtl_files
    else:
        rtl_dir = project / (args.rtl_dir or "phase2/stage1/rtl")
        doc = ""
        for cand in (args.doc,):
            if cand and (project / cand).exists():
                doc += (project / cand).read_text(errors="replace")
        spec = detect_safety_mechanism(rtl_dir, doc)
        spec_rtl_rel = []
        if spec is not None:
            # resolve rtl files relative to project for the mount
            for f in rtl_dir.rglob("*.v"):
                spec_rtl_rel.append(str(f.relative_to(project)))

    floor = asil_floor(args.asil, args.min_dc)

    # 2) NOT_APPLICABLE → vacuous pass (this step only fires for safety designs)
    if spec is None:
        rep = build_report(None, None, args.asil, floor)
        return 0, rep

    if not spec.enc_module:
        # decoder-only auto-detect: this builder needs an encoder for stimulus.
        rep = build_report(None, None, args.asil, floor)
        rep["verdict"] = "NOT_APPLICABLE"
        rep["reason"] = ("safety mechanism found but no encoder to generate "
                         "valid codewords for injection — supply --enc-module "
                         "or codeword stimulus; skipped (no fabricated DC)")
        rep["applicable"] = False
        return 0, rep

    # 3) render TB + run the REAL injection
    tb = build_ecc_injection_tb(spec, max_vectors=args.max_vectors)
    tb_dir = project / "phase2" / "stage2" / "safety"
    tb_dir.mkdir(parents=True, exist_ok=True)
    tb_path = tb_dir / "fmeda_fi_tb.v"
    tb_path.write_text(tb)
    tb_rel = str(tb_path.relative_to(project))

    ec, out, err = run_injection_iverilog(
        project, spec_rtl_rel, tb_rel, tb_top="fmeda_fi_tb",
        timeout=args.timeout)
    log = out + "\n" + err
    if ec not in (0,) or not _GOLDEN_RE.search(out):
        rep = build_report(spec, None, args.asil, floor, tool_log=log)
        rep["verdict"] = "FAIL"
        rep["reason"] = (f"iverilog/vvp injection run failed (exit={ec}) or "
                         f"produced no baseline — cannot measure DC")
        rep["baseline_valid"] = False
        return 1, rep

    results = parse_injection_results(out)
    rep = build_report(spec, results, args.asil, floor, tool_log=log)
    return (0 if rep["ge_floor"] else 1), rep


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--rtl-dir", default="phase2/stage1/rtl",
                   help="RTL dir to auto-detect the safety mechanism in")
    p.add_argument("--doc", default=None,
                   help="optional L23/safety doc (relative) to confirm a "
                        "declared mechanism")
    # explicit wiring (overrides auto-detect)
    p.add_argument("--enc-module")
    p.add_argument("--enc-in", default="data_in")
    p.add_argument("--enc-out", default="code_out")
    p.add_argument("--dec-module")
    p.add_argument("--dec-in", default="code_in")
    p.add_argument("--dec-out", default=None)
    p.add_argument("--detect-port", default=None)
    p.add_argument("--data-width", type=int, default=4)
    p.add_argument("--code-width", type=int, default=7)
    p.add_argument("--rtl-file", action="append",
                   help="RTL file (relative to project) — repeatable")
    p.add_argument("--asil", default="D", help="target ASIL (A/B/C/D/QM)")
    p.add_argument("--min-dc", type=float, default=None,
                   help="explicit DC floor %% (overrides the ASIL default)")
    p.add_argument("--max-vectors", type=int, default=64,
                   help="max stimulus data values (all 2^K if small)")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--json", default=None)
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fmeda_fault_injection_coverage: not a dir: {project}",
              file=sys.stderr)
        return 2

    exit_code, rep = run(project, args)

    out_path = _report_path(project, args.json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rep, indent=2) + "\n")

    if not rep.get("applicable", False):
        print(f"fmeda_fault_injection_coverage: {rep['verdict']} — "
              f"{rep.get('reason', '')}")
    else:
        print(f"fmeda_fault_injection_coverage: DC="
              f"{rep['diagnostic_coverage_pct']:.2f}% "
              f"({rep['detected_faults']}/{rep['injected_faults']}) "
              f"floor={rep['dc_floor_pct']} ASIL-{rep['asil']} "
              f"→ {rep['verdict']}")
    if exit_code != 0:
        print(f"  (see {out_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
