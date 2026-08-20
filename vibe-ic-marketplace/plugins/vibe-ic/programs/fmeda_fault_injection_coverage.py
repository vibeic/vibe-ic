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
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import _path_layout as _pl  # noqa: E402
try:  # sibling module; programs/ is on sys.path when run as a script
    import _docker_memory as _dmem
except ImportError:  # pragma: no cover - packaged/flattened layouts
    from . import _docker_memory as _dmem  # type: ignore


# ───────────── what this gate REGENERATES inside the project ────────────
# This gate does not only READ the project — it RENDERS an injection
# testbench into it and compiles that testbench there, on every run, so two
# files under `phase2/` carry this gate's timestamp rather than the design
# round's. Anything that dates a run by mtime has to know that, and the only
# place that can state it without drifting is here, where the writing happens.
#
# MEASURED: `flow_compliance_check` on an untouched copy of
# `benchmark-data/ic/opentitan_aes` moved 40 files; the only two outside
# `reports/` are exactly these. `result_md_audit_provenance_check` read one of
# them as "a newer round of the design" and reported the tree STALE from the
# second run onward, on a tree nobody had touched.
#: Where the rendered injection testbench is written, project-relative.
FI_TB_RELPATH = "phase2/stage2/safety/fmeda_fi_tb.v"
#: Every project-relative path this gate rewrites on a run. The compiled
#: object is `<tb>.vvp` on BOTH injection backends (`_run_injection_host` and
#: the container leg both build `f"{tb_rel}.vvp"`).
REGENERATED_PROJECT_PATHS: Tuple[str, ...] = (
    FI_TB_RELPATH, FI_TB_RELPATH + ".vvp")


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
#
# SPLIT BY WHETHER THE TOKEN HAS AN ORDINARY-ENGLISH READING, because the
# single flat pattern below used to be matched against the RAW bytes of every
# .v/.sv file — COMMENTS INCLUDED — and two of its alternatives are ordinary
# English words.
#
# MEASURED, sha256 crypto accelerator: the ONLY match of the whole pattern in
# the entire design was `lockstep`, inside
#     `reg [5:0] round1;   // t+1, kept in lockstep for K[t+1]`
# — a comment saying two round counters advance together. That one word
# admitted a design which declares no ASIL, no safety goal and no safety
# mechanism anywhere in L1..L9 into an ASIL-D FMEDA graded against a 99 %
# diagnostic-coverage floor, which it then FAILed. A safety mechanism is
# DECLARED, not mentioned.
#
# STRONG — terms of art nobody writes by accident. `ISO-26262`, `ASIL-D`,
# `FMEDA`, `SEC-DED`, `error correcting code`, `functional safety`,
# `diagnostic coverage`, `safety mechanism`, `parity protect`. Their presence
# IS a declaration, so they are honoured ANYWHERE — RTL comments included. This
# is what a real ECC block's header comment says, and it keeps firing.
_SAFETY_DECL_STRONG_RE = re.compile(
    r"\b(diagnostic\s+coverage|safety\s+mechanism|iso[-\s]?26262|"
    r"functional\s+safety|fmeda|asil[-\s]?[abcd]|"
    r"single[-\s]?error\s+correct|sec[-\s]?ded|error\s+correcting\s+code|"
    r"parity\s+protect)", re.I)

# WEAK — real safety vocabulary that ALSO has an incidental reading. "kept in
# lockstep" is ordinary English for "in step"; a bare `ecc` is three letters
# that can be an identifier or somebody's initials. These are honoured from the
# design's DECLARATIVE prose (the L-doc / L23 text passed as `doc_text`, where
# a declaration legitimately lives) and from RTL CODE, but NOT from RTL
# commentary — the one place where the incidental reading actually occurs.
_SAFETY_DECL_WEAK_RE = re.compile(r"\b(lockstep|ecc)\b", re.I)

# Union — kept as the historical name for any external reader of this module.
_SAFETY_DECL_RE = re.compile(
    _SAFETY_DECL_STRONG_RE.pattern + "|" + _SAFETY_DECL_WEAK_RE.pattern, re.I)

# A SAFETY MECHANISM IS DECLARED, NEVER MENTIONED. `_SAFETY_DECL_RE` is applied
# to the design's DOC prose (where a declaration legitimately lives) plus the
# RTL — and until this strip existed, "the RTL" meant its raw bytes, COMMENTS
# INCLUDED. An ordinary English comment is not a declaration.
#
# MEASURED, sha256 crypto accelerator: the ONLY match of `_SAFETY_DECL_RE` in
# the entire design was the word `lockstep` inside
#     `reg [5:0] round1;   // t+1, kept in lockstep for K[t+1]`
# — a comment describing a pipeline register that carries round t+1 alongside
# round t. That one word admitted a design which declares no ASIL, no safety
# goal and no safety mechanism anywhere in L1..L9 into an ASIL-D FMEDA graded
# against a 99 % diagnostic-coverage floor, which it then FAILed.
#
# Stripping comments is the CONSERVATIVE direction: a design whose only safety
# statement is a comment now lands on the DISCLOSED `NOT_APPLICABLE` vacuous
# skip (its own tier, its own counter) instead of a false ASIL-D FAIL, and the
# two arms that carry a real declaration are untouched — the POSITIVE STRUCTURE
# arm (corrected-data output PAIRED WITH a syndrome/detect port) still fires
# with no prose at all, and the doc/L23 prose arm is deliberately NOT stripped.
_HDL_COMMENT_RE = re.compile(r'"(?:\\.|[^"\\\n])*"|//[^\n]*|/\*.*?\*/',
                             re.DOTALL)


def _strip_hdl_comments(text: str) -> str:
    """Blank out `//` and `/* */` comments in Verilog/SystemVerilog source,
    leaving string literals intact (a `//` inside a string is not a comment).
    Replacement is a space, so token boundaries survive. Pure."""
    return _HDL_COMMENT_RE.sub(
        lambda m: m.group(0) if m.group(0).startswith('"') else " ", text)


_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)\s*", re.MULTILINE)

# The runner's reset/clock-variant alias suffix (design_one_shot_runner renames
# `<top>` → `<top>__rcvar_inner`). Two modules sharing the same base are the SAME
# logical block (a wrapper + its inner), never an encoder/decoder pair (#145).
_RCVAR_SUFFIX = "__rcvar_inner"


def _rcvar_base(mod: str) -> str:
    return mod[:-len(_RCVAR_SUFFIX)] if mod.endswith(_RCVAR_SUFFIX) else mod


def _module_ports(text: str, module: str) -> List[Tuple[str, str, int]]:
    """Best-effort port list (name, dir, width) for `module`. Handles ANSI
    `input [W-1:0] name` headers. Width defaults to 1. Pure-ish (regex).

    The SystemVerilog net/variable-TYPE keyword between the direction and the
    packed dimension must be SKIPPED, not captured as the port name. The old
    pattern skipped only `reg|wire`, so `output logic [56:0] data_o` — the
    lowRISC / OpenTitan house style, and the SV ANSI default — parsed as
    name=`logic`, width=1, losing both the real name and the `[56:0]` width.
    Measured on opentitan_aes x sky130A: every port of
    `prim_secded_inv_64_57_dec` (`output logic [56:0] data_o`,
    `output logic [6:0] syndrome_o`, `output logic [1:0] err_o`) collapsed to
    `('logic', 'output', 1)`, so the ECC decoder had no detect port and no
    corrected-data output, `detect_safety_mechanism` found no decoder and
    returned NOT_APPLICABLE, and Step FS1 VACUOUSLY passed on a design that
    ships a genuine SEC-DED ECC + declares it (`SECDED` matches the strong
    safety-declaration regex) — an ASIL-D FMEDA that was never run.

    Skip a run of net/var-type + signedness keywords (`logic`, `bit`, `var`,
    `signed`, `unsigned`, `reg`, `wire`, e.g. `output wire signed [7:0] x`)
    before the optional dimension. chip-AGNOSTIC — keyed on SV syntax only."""
    # isolate the module header up to the first ');'
    m = re.search(r"\bmodule\s+" + re.escape(module) + r"\b(.*?)\)\s*;",
                  text, re.DOTALL)
    body = m.group(1) if m else ""
    ports: List[Tuple[str, str, int]] = []
    for pm in re.finditer(
            r"(?i)\b(input|output|inout)\b\s*"
            r"(?:(?:reg|wire|logic|bit|var|signed|unsigned)\b\s*)*"
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
    combined_code = doc_text + "\n"
    per_file: List[Tuple[Path, str]] = []
    for f in vfiles:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        per_file.append((f, t))
        # Two views feed the declaration arm below: `combined` keeps the RTL
        # verbatim (STRONG terms of art count wherever they appear, including a
        # module header comment), `combined_code` drops the commentary (so a
        # WEAK token's incidental reading in a comment cannot declare safety).
        # `t` — raw — remains what the port/module parsing uses.
        combined += t + "\n"
        combined_code += _strip_hdl_comments(t) + "\n"

    # Collect all modules and their ports across files.
    mods: Dict[str, Tuple[Path, List[Tuple[str, str, int]]]] = {}
    for f, t in per_file:
        # Module NAMES and port lists must come from CODE, never commentary: a
        # comment sentence "// This module controls the ..." matches `_MODULE_RE`
        # and fabricates a phantom module named `controls`. Measured on
        # opentitan_aes x sky130A: the header comments of aes_cipher_control.sv
        # ("This module controls ...") and aes_ctrl_gcm_reg_shadowed.sv ("This
        # module implements ...") minted phantom modules `controls`/`implements`,
        # which the declared-safety arm then paired into a 1-bit phantom ECC whose
        # TB instances (`controls u_enc`, `implements u_dec`) reference modules
        # that do not exist -> the fault-injection compile FAILs -> DC=UNMEASURED
        # -> FS1 FAIL on a design that ships a genuine SEC-DED ECC. Strip comments
        # first (the same _strip_hdl_comments already used for combined_code).
        code = _strip_hdl_comments(t)
        for mod in _MODULE_RE.findall(code):
            if mod not in mods:
                mods[mod] = (f, _module_ports(code, mod))

    # Find a decoder: has a detect output OR (input wider than a narrower output).
    # RANK candidates rather than breaking on the FIRST by dict/file order.
    # Measured on opentitan_aes x sky130A: iterating in file order locked onto
    # `aes_ctrl_gcm_reg_shadowed` (a shadowed control register whose `err_update_o`
    # matches _is_detect_port) and broke BEFORE reaching the genuine SEC-DED ECC
    # `prim_secded_inv_64_57_dec` (input [63:0] data_i, output [56:0] data_o AND
    # err_o — the textbook corrected-data-plus-detect structure). The shadow
    # register has a detect port but NO corrected-data output, so it only survives
    # the §4.05 gate via the weak `declared` arm, while the real ECC has the #145
    # POSITIVE structure. Prefer the positive-structure decoder (corr_out AND
    # detect) over a detect-only/corr-only one, then the widest codeword, with a
    # deterministic name tie-break. chip-AGNOSTIC — ranks on port structure only.
    candidates = []
    for mod, (f, ports) in mods.items():
        ins = [(n, w) for n, d, w in ports if d == "input"]
        outs = [(n, w) for n, d, w in ports if d == "output"]
        if not ins or not outs:
            continue
        detect_outs = [n for n, _ in outs if _is_detect_port(n)]
        data_ins = [(n, w) for n, w in ins if not _is_clk_rst(n)]
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
            candidates.append({
                "module": mod, "file": f,
                "in": widest_in[0], "code_width": widest_in[1],
                "detect": detect_outs[0] if detect_outs else None,
                "out": corr_out[0] if corr_out else None,
                "data_width": corr_out[1] if corr_out else widest_in[1],
                "_has_both": bool(corr_out and detect_outs),
            })
    dec = None
    if candidates:
        candidates.sort(key=lambda c: (not c["_has_both"],
                                       -c["code_width"], c["module"]))
        dec = candidates[0]
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
    # A STRONG term of art declares safety wherever it appears (comments too); a
    # WEAK one only from declarative prose or RTL code, never from commentary.
    declared = (_SAFETY_DECL_STRONG_RE.search(combined)
                or _SAFETY_DECL_WEAK_RE.search(combined_code))
    if not ((dec["out"] is not None and dec["detect"] is not None)
            or declared):
        return None

    # Find an encoder: input == decoder data_width, output == code_width.
    # RANK rather than break-on-first (same defect as the decoder scan above):
    # in file order the first module with any wider-output-than-input shape wins,
    # which on opentitan_aes grabbed `aes_cipher_control` (an AES control block
    # that `include`s prim_assert.sv and needs the aes package — uncompilable in
    # isolation) instead of the SEC-DED ECC's own `prim_secded_inv_64_57_enc`
    # (input [56:0] → output [63:0], the EXACT inverse of the chosen decoder).
    # Prefer an encoder whose widths mirror the decoder (out == code_width AND
    # in == data_width), then the closest structural match. chip-AGNOSTIC.
    enc = None
    enc_cands = []
    for mod, (f, ports) in mods.items():
        if mod == dec["module"]:
            continue
        # #145 — never pair a module with its OWN reset/clock-variant alias: the
        # runner renames `<top>` → `<top>__rcvar_inner` (a wrapper + inner pair),
        # which is NOT an encoder/decoder pair.
        if _rcvar_base(mod) == _rcvar_base(dec["module"]):
            continue
        ins = [(n, w) for n, d, w in ports
               if d == "input" and not _is_clk_rst(n)]
        outs = [(n, w) for n, d, w in ports if d == "output"]
        if not ins or not outs:
            continue
        widest_out = max(outs, key=lambda x: x[1])
        narrow_in = min(ins, key=lambda x: x[1])
        if widest_out[1] > narrow_in[1]:
            exact = (widest_out[1] == dec["code_width"]
                     and narrow_in[1] == dec["data_width"])
            enc_cands.append({
                "module": mod, "file": f,
                "in": narrow_in[0], "out": widest_out[0],
                "data_width": narrow_in[1], "code_width": widest_out[1],
                "_exact": exact,
                "_delta": (abs(widest_out[1] - dec["code_width"])
                           + abs(narrow_in[1] - dec["data_width"])),
            })
    if enc_cands:
        enc_cands.sort(key=lambda c: (not c["_exact"], c["_delta"], c["module"]))
        enc = enc_cands[0]

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

# A CLOCK/RESET PIN IS NEVER THE PROTECTED DATA PATH. The literal set above is
# an enumeration of spellings, and an enumeration of spellings is a proxy for
# the property "this pin is a clock or a reset". It held `rst_n` and `resetn`
# and MISSED `reset_n` — one of the commonest reset names in Verilog.
#
# MEASURED, sha256: the design's L3 port contract names the pin `reset_n`, so
# the encoder search kept it, `min(ins, key=width)` picked it as the narrowest
# input, and the emitted mechanism was
#     enc_in='reset_n', data_width=1
# — the gate injected stuck-at faults into the RESET PIN and called it the
# protected data path. The generated TB then wired a 32-bit vector to a 256-bit
# `digest` port (`fmeda_fi_tb.v:9: warning: Port 8 (digest) ... expects 256
# bit(s), given 32`), every injection came back `DETECT x`, and no golden
# baseline was ever established.
#
# Replaced with a decomposition: split the name into components, require at
# least one clock/reset ROOT, and allow only polarity/direction decorations
# alongside it. `data_in`, `write_data`, `code_in`, `interrupt` and `sense`
# are all rejected; `reset_n`, `rst_ni`, `n_reset`, `clk_i`, `arst_n`,
# `resetb`, `areset` are all recognised. chip-AGNOSTIC.
_CLK_RST_ROOTS = {"clk", "clock", "clks", "rst", "reset", "arst", "areset",
                  "en", "enable", "ena", "clken", "clkin", "sclk", "aclk"}
# Decorations that may accompany a root without changing what the pin IS.
_CLK_RST_DECOR = {"n", "b", "i", "o", "p", "a", "x", "in", "not", "neg", "inv",
                  "async", "asynch", "sync", "l", "h", "g", "gated", "bar"}
# Glued polarity suffixes: `rstn`, `resetn`, `resetb`, `rst_ni` -> root + tail.
_GLUED_POLARITY = ("ni", "no", "n", "b", "l")


def _is_clk_rst(name: str) -> bool:
    """True iff `name` reads as a clock, reset or enable pin — i.e. something
    that can never be an ECC codeword / protected data bus. Component-aware, so
    it survives spellings the old literal set did not enumerate. Pure."""
    toks = [t for t in re.split(r"[_\W]+", (name or "").lower()) if t]
    if not toks:
        return False
    saw_root = False
    for t in toks:
        if t in _CLK_RST_ROOTS:
            saw_root = True
            continue
        if t in _CLK_RST_DECOR:
            continue
        # a glued polarity suffix: `rstn` -> `rst`+`n`, `resetb` -> `reset`+`b`
        stripped = None
        for suf in _GLUED_POLARITY:
            if t.endswith(suf) and t[:-len(suf)] in _CLK_RST_ROOTS:
                stripped = t[:-len(suf)]
                break
        if stripped is not None:
            saw_root = True
            continue
        return False          # a component that is neither root nor decoration
    return saw_root


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
#: Image refs probed, in order, for a locally-present EDA container. ONE list,
#: shared by `_resolve_docker_image` and `_local_docker_image`, so the pin and
#: the fallback order cannot drift between the two.
_IMAGE_CANDIDATES = (
    "ghcr.io/vibeic/vibeic-eda:0.3.14",
    "vibeic-eda:0.3.14",
    "vibeic/vibeic-eda:0.3.14",
    "hpretl/iic-osic-tools:latest",
)


def _resolve_docker_image() -> str:
    """The image ref to use, falling back to the pin when none is local.

    NOTE the fallback: this ALWAYS returns a ref, including one the daemon does
    not have. Use `_local_docker_image` when the answer must distinguish
    "present" from "would have to be fetched"."""
    env = os.environ.get("VIBEIC_EDA_IMAGE") or os.environ.get("IIC_EDA_IMAGE")
    if env:
        return env
    for img in _IMAGE_CANDIDATES:
        try:
            r = subprocess.run(["docker", "image", "inspect", img],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                return img
        except Exception:
            pass
    return _IMAGE_CANDIDATES[0]


_IVERILOG_ROOT = "/foss/tools/iverilog"
_ENV_PREAMBLE = (
    f"export PATH={_IVERILOG_ROOT}/bin:/foss/tools/bin:$PATH && "
    f"export LD_LIBRARY_PATH={_IVERILOG_ROOT}/lib:${{LD_LIBRARY_PATH:-}} && "
)


def _local_docker_image() -> Optional[str]:
    """The container this run can use WITHOUT a registry pull, else None.

    `_resolve_docker_image` returns the pinned default even when NOTHING is
    present locally, so a caller acting on it hands `docker run` an image the
    daemon must fetch — 6.68 GB across 84 layers for the pinned tag. That is
    not a slow run, it is an unbounded one from the caller's point of view,
    and it is why this backend must be resolved BEFORE it is used.

    An explicit `VIBEIC_EDA_IMAGE` / `IIC_EDA_IMAGE` is honoured as-is: the
    caller named that image on purpose and may well intend it to be pulled.
    Without an override, a candidate is offered only when the LOCAL daemon
    already has it. `docker image inspect` is a daemon-local query that never
    touches the network, and it is bounded here so the PROBE cannot become the
    hang it exists to prevent.
    """
    env = os.environ.get("VIBEIC_EDA_IMAGE") or os.environ.get("IIC_EDA_IMAGE")
    if env:
        return env
    if not shutil.which("docker"):
        return None
    for img in _IMAGE_CANDIDATES:
        try:
            r = subprocess.run(["docker", "image", "inspect", img],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                return img
        except Exception:
            return None
    return None


def _host_iverilog() -> bool:
    """True iff BOTH iverilog and vvp are on the host PATH."""
    return bool(shutil.which("iverilog") and shutil.which("vvp"))


#: Backend tokens returned by :func:`resolve_injection_backend`.
BACKEND_DOCKER = "docker"
BACKEND_HOST = "host"
BACKEND_NONE = "none"


def resolve_injection_backend(image: Optional[str] = None
                              ) -> Tuple[str, Optional[str], str]:
    """Decide WHERE the injection would run here: (backend, image, reason).

    THE SINGLE SOURCE OF THAT DECISION. `run_injection_iverilog` dispatches on
    it and callers that need to know whether a real injection is possible ask
    THIS function rather than restating its conditions — because a guard that
    restates them drifts from them. The landed guard checked host iverilog/vvp
    while this path ran `docker run` against an image it never verified was
    present; on a runner with iverilog installed and no image the guard said GO
    and the path went to the registry, so the measurement blocked on a resource
    nobody had checked for. Same function, no drift.

    Order is container-first, matching the canonical containerised config where
    iverilog lives only in the image (`design_one_shot_runner._iverilog_available`
    documents the same preference), so no host that already has the image sees
    any change. The HOST leg exists because requiring a multi-GB container on a
    host that has a perfectly good iverilog is a host-dependence, not a
    measurement requirement: the rendered TB is plain Verilog-2012 and the DC it
    prints does not depend on which of the two compiled it.
    """
    img = image or _local_docker_image()
    if img:
        return BACKEND_DOCKER, img, f"container {img} usable without a pull"
    if _host_iverilog():
        return BACKEND_HOST, None, "host iverilog/vvp"
    return (BACKEND_NONE, None,
            "no injection backend: no vibeic-eda image is present locally "
            "(set VIBEIC_EDA_IMAGE, or `docker pull`, to use a container) and "
            "the host has no iverilog/vvp on PATH")


def _run_injection_host(project: Path,
                        rtl_rel_files: List[str],
                        tb_rel: str,
                        tb_top: str,
                        timeout: int) -> Tuple[int, str, str]:
    """Compile + run the injection with the HOST iverilog/vvp.

    Mirrors the container leg's `compile && run` semantics exactly: vvp runs
    only when the compile succeeded, and the caller sees the CONCATENATED
    stdout of both stages, because that is where the `GOLDEN`/`FAULT` transcript
    the parser reads comes from. The single `timeout` is a budget for the pair,
    not for each, so this leg cannot outlast the container leg's bound.
    """
    vvp_out = project / f"{tb_rel}.vvp"
    vvp_out.parent.mkdir(parents=True, exist_ok=True)
    srcs = [str(project / s) for s in rtl_rel_files + [tb_rel]]
    deadline = time.monotonic() + timeout
    try:
        c = subprocess.run(
            ["iverilog", "-g2012", "-o", str(vvp_out), "-s", tb_top] + srcs,
            capture_output=True, text=True, cwd=str(project), timeout=timeout)
        if c.returncode != 0:
            return c.returncode, c.stdout, c.stderr
        left = max(1, int(deadline - time.monotonic()))
        r = subprocess.run(["vvp", str(vvp_out)], capture_output=True,
                           text=True, cwd=str(project), timeout=left)
        return r.returncode, c.stdout + r.stdout, c.stderr + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "iverilog/vvp timed out"
    except FileNotFoundError:
        return 127, "", "iverilog/vvp not found on the host PATH"


def run_injection_iverilog(project: Path,
                           rtl_rel_files: List[str],
                           tb_rel: str,
                           tb_top: str = "fmeda_fi_tb",
                           timeout: int = 300,
                           image: Optional[str] = None
                           ) -> Tuple[int, str, str]:
    """Compile the mechanism RTL + generated TB with iverilog and run vvp —
    in the vibeic-eda container when one is usable WITHOUT a registry pull,
    otherwise with the host iverilog/vvp. Returns (exit, stdout, stderr);
    under the container leg the project is mounted at /work.

    When NEITHER backend is available this returns 127 with the reason naming
    both, rather than handing `docker run` an absent image and blocking on the
    registry for a multi-GB fetch."""
    backend, img, reason = resolve_injection_backend(image)
    if backend == BACKEND_NONE:
        return 127, "", reason
    if backend == BACKEND_HOST:
        return _run_injection_host(project, rtl_rel_files, tb_rel, tb_top,
                                   timeout)
    vvp_out = f"{tb_rel}.vvp"
    srcs = " ".join(f"/work/{s}" for s in rtl_rel_files + [tb_rel])
    compile_cmd = (f"iverilog -g2012 -o /work/{vvp_out} -s {tb_top} {srcs}")
    run_cmd = f"vvp /work/{vvp_out}"
    full = _ENV_PREAMBLE + compile_cmd + " && " + run_cmd
    docker_cmd = [
        "docker", "run", "--rm", *_dmem.docker_memory_flags(),
        "--entrypoint", "bash",
        "-v", f"{project}:/work", img, "-c", full,
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
# ---------------------------------------------------------------------------
# vibe-ic#562 — RE-ADJUDICATION RULES for this gate's published records.
#
# THE DRIFT. `dc_verdict(dc, floor)` returns True unconditionally when `floor is
# None` — the ASIL-A / QM case, which states no quantitative DC floor. That is
# right as a gating decision: inventing a floor the standard does not state would
# be fabrication. But it means a run that injected NOTHING, or injected and
# detected nothing, publishes `verdict: PASS` with `diagnostic_coverage_pct: 0`.
#
# `compute_dc` is explicit that "injected==0 -> 0.0 (no evidence is NOT full
# coverage)", and the `reason` string does say "advisory". The VERDICT FIELD does
# not, and that is the field a reader and every machine consumer take.
import _record_adjudication as _ra  # noqa: E402


def _advisory_zero_dc(record: dict):
    """Would this gate still call this a PASS on the coverage it measured?"""
    if record.get("verdict") != "PASS":
        return None
    try:
        dc = float(record.get("diagnostic_coverage_pct") or 0.0)
        injected = int(record.get("injected_faults") or 0)
    except (TypeError, ValueError):
        return None                      # unreadable -> UNDECIDABLE, not a guess
    if injected > 0 and dc > 0.0:
        return None                      # real coverage was measured
    what = ("injected no fault at all" if injected <= 0
            else "detected none of the faults it injected")
    return _ra.Supersession(
        would_issue="VACUOUS_PASS",
        because=(f"the record carries PASS with diagnostic_coverage_pct {dc:g} "
                 f"and injected_faults {injected} — the run {what}. The PASS "
                 f"comes from the ASIL-A/QM branch, which states no quantitative "
                 f"floor and therefore passes any number including zero; the "
                 f"`reason` field says 'advisory' but the verdict does not, and "
                 f"the verdict is what a consumer reads"),
    )


RECORD_ADJUDICATION = _ra.declare(
    __file__,
    gate="fmeda_fault_injection_coverage",
    decision_roots=("build_report",),
    # RE-REVIEWED at the safety-declaration split (this commit), not re-stamped.
    # The digest moved because `build_report`'s reachable logic changed twice:
    # the STRONG/WEAK declaration split, and `diagnostic_coverage_pct` becoming
    # None when nothing was measured instead of a literal 0.0.
    #
    # The rule below reads verdict / diagnostic_coverage_pct / injected_faults,
    # so the second change touches its inputs directly. Re-checked by RUNNING it
    # against both record shapes rather than by reasoning about it:
    #
    #   PASS, dc 0.0,  injected 0     -> VACUOUS_PASS   (old shape)
    #   PASS, dc None, injected 0     -> VACUOUS_PASS   (new shape, via `or 0.0`)
    #   PASS, dc 99.2, injected 500   -> unchanged (no supersession)
    #   FAIL, dc None, injected 0     -> unchanged (no supersession)
    #
    # Identical verdicts across the change, so no published record is
    # re-adjudicated differently. Bumping this constant without running those
    # four is exactly what `published_record_staleness_check` exists to stop.
    decision_digest="ff18dc57a97f43103102d08829175402b0cd05378c130a3779438405a7bf7a27",
    rules=(
        _ra.Rule(
            rule_id="fmeda_fault_injection_coverage.advisory-zero-dc",
            landed_in="#562",
            requires=("verdict", "diagnostic_coverage_pct", "injected_faults"),
            decide=_advisory_zero_dc,
            what=("a PASS at 0% diagnostic coverage measured no fault detection "
                  "at all; the ASIL-A/QM branch passes any number"),
        ),
    ),
)


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
    # UNMEASURED IS NOT ZERO PERCENT. `dc = ... if results else 0.0` published
    # `diagnostic_coverage_pct: 0.0` for a run that injected NO faults, and
    # `main()` printed `DC=0.00% (0/0) floor=99.0 ASIL-D -> FAIL` — a coverage
    # MEASUREMENT — beside this same object's own `reason` field reading
    # "cannot measure DC". A run that measured nothing and a run that measured
    # zero detections are different claims; 0.00 % asserts the second.
    # `None` is the only honest value, and `measured` names which case it is.
    measured = results is not None
    dc = results.dc_pct if results else None
    baseline_ok = bool(results and results.golden_ok)
    if not measured:
        passed, reason = False, ("injection produced NO result to read — "
                                 "diagnostic coverage is UNMEASURED, not 0 %. "
                                 "Reported as null; FAIL because an applicable "
                                 "safety design must not sign off on an "
                                 "unmeasured DC")
    elif not baseline_ok:
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
        "measured": measured,
        "injected_faults": results.injected if results else 0,
        "detected_faults": results.detected if results else 0,
        # null, not 0.0, when nothing was measured — see `measured` above.
        "diagnostic_coverage_pct": (round(dc, 4) if measured else None),
        "per_site_covered": site_cov,
        "per_site_total": site_tot,
        "per_site_dc_pct": (round(compute_dc(site_cov, site_tot), 4)
                            if measured else None),
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


#: The consumer reads `stdout[-300:]` and matches `VACUOUS_PASS` at LINE
#: START. Anything longer than this is not a disclosure — it is a disclosure
#: the window ate. Kept well under the limit so a longer verdict name still
#: fits, and shared with `fmeda_coverage_check` so both gates of step FS1
#: disclose through the same bounded line.
VACUOUS_TOKEN_MAX_LEN = 200


def _vacuous_token_line(verdict: str) -> str:
    """The bounded, line-start `VACUOUS_PASS:` disclosure line."""
    line = (f"VACUOUS_PASS: fmeda diagnostic coverage NOT measured "
            f"(verdict={verdict}); see the --json report for why")
    return line[:VACUOUS_TOKEN_MAX_LEN]


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
        # ── UNMEASURED IS NOT ZERO — AND IS NOT THIS STEP'S DEFECT ────────
        # `detect_safety_mechanism` returns None for TWO different facts: it
        # read the RTL and found no ECC/parity/lockstep mechanism, and it had
        # no RTL to read at all. Folding the second into NOT_APPLICABLE emits
        # "this design declares no safety mechanism" from an input that was
        # never opened — a design-shape CLAIM derived from an unread file.
        # They are separated here, and they answer DIFFERENTLY, because the
        # two failure directions are different:
        #
        #   * `--rtl-dir` DOES NOT EXIST -> rc 1. The caller named a path that
        #     is not there; nothing can be said about the design at all. Not
        #     reachable through the flow (FS1's own condition is
        #     `files_exist: [phase2/stage1/rtl]`, so the step does not run
        #     without it) — this arm exists for the CLI and for any runner
        #     that passes an explicit --rtl-dir.
        #   * The directory EXISTS but holds no HDL this tool can read -> rc 0
        #     with a DISCLOSED vacuous pass. It was tried as an rc-1 FAIL and
        #     REVERTED: an empty or non-Verilog RTL directory is a
        #     PRE-CONDITION of the whole flow, owned by the RTL and synthesis
        #     steps, and making the ISO-26262 SAFETY sign-off the step that
        #     hard-FAILs on it is a false alarm on every project whose RTL is
        #     absent, staged elsewhere, or written in VHDL. Measured: an empty
        #     `phase2/stage1/rtl/` took `STEP FS1 STATUS FAIL` and
        #     `Overall: FAIL` rc 1 from a one-step FS1 flow.
        #
        # What must NOT come back is the original defect: answering
        # NOT_APPLICABLE — "this design declares no safety mechanism" — from an
        # input nobody opened. The vacuous branch below says the opposite in
        # its own verdict (`UNMEASURED_NO_RTL_READ`, `measurable: false`,
        # `rtl_sources_read: 0`) and on stdout, so the step lands on the
        # VACUOUS_PASS tier with its own label and counter rather than in the
        # plain PASS bucket.
        if not args.dec_module and not args.enc_module:
            floor_pct = asil_floor(args.asil, args.min_dc)
            common = {
                "program": "fmeda_fault_injection_coverage",
                "measurable": False,
                "asil": args.asil,
                "dc_floor_pct": floor_pct,
                "injected_faults": 0,
                "detected_faults": 0,
                "baseline_valid": False,
                "rtl_dir": str(args.rtl_dir or "phase2/stage1/rtl"),
                "rtl_sources_read": 0,
            }
            if not rtl_dir.is_dir():
                return 1, dict(common, **{
                    "applicable": True,
                    "verdict": "FAIL",
                    "reason": (
                        f"--rtl-dir {args.rtl_dir!r} does not exist — the "
                        f"presence or absence of a safety mechanism could "
                        f"not be decided from an input that was never "
                        f"opened. Unmeasured is not zero: this is NOT "
                        f"NOT_APPLICABLE."),
                })
            if not (list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv"))):
                return 0, dict(common, **{
                    # `applicable: False` puts this on main()'s vacuous branch,
                    # which prints the line-start VACUOUS_PASS: token. The
                    # verdict below is what stops it being read as the
                    # design-shape claim NOT_APPLICABLE would make.
                    "applicable": False,
                    "verdict": "UNMEASURED_NO_RTL_READ",
                    "reason": (
                        f"--rtl-dir {args.rtl_dir!r} exists but holds no "
                        f".v/.sv source, so ZERO RTL files were read and "
                        f"NOTHING is claimed about this design's safety "
                        f"mechanisms. This is NOT NOT_APPLICABLE — that "
                        f"verdict would assert a design shape derived from "
                        f"an unread input. Missing/foreign-language RTL is "
                        f"owned by the RTL and synthesis steps, not by the "
                        f"safety sign-off."),
                })
        doc = ""
        for cand in (args.doc,):
            if cand and (project / cand).exists():
                doc += (project / cand).read_text(errors="replace")
        spec = detect_safety_mechanism(rtl_dir, doc)
        spec_rtl_rel = []
        if spec is not None:
            # Compile the DETECTED mechanism's OWN files (the enc + dec leaves),
            # resolved from the dir by name — NOT rtl_dir.rglob("*.v"). The old
            # glob (a) matched only *.v, so on a SystemVerilog design (mechanism
            # leaves are *.sv) it compiled ZERO mechanism files, and (b) swept in
            # unrelated *.v files (e.g. an auto-generated typo-alias leaf) that
            # need not elaborate and crash the injection compile. The mechanism's
            # own leaves are self-contained; feeding exactly them makes the TB's
            # `u_enc`/`u_dec` instances resolvable. chip-AGNOSTIC.
            seen: set = set()
            for name in spec.rtl_files:
                for f in rtl_dir.rglob(name):
                    rel = str(f.relative_to(project))
                    if rel not in seen:
                        seen.add(rel)
                        spec_rtl_rel.append(rel)

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
    tb_rel = FI_TB_RELPATH                      # the DECLARED path, not a copy
    tb_path = project / tb_rel
    tb_path.parent.mkdir(parents=True, exist_ok=True)
    tb_path.write_text(tb)

    ec, out, err = run_injection_iverilog(
        project, spec_rtl_rel, tb_rel, tb_top="fmeda_fi_tb",
        timeout=args.timeout)
    log = out + "\n" + err
    if ec not in (0,) or not _GOLDEN_RE.search(out):
        rep = build_report(spec, None, args.asil, floor, tool_log=log)
        rep["verdict"] = "FAIL"
        # SAY WHICH OF THE TWO HAPPENED. The old text — "injection run failed
        # (exit={ec}) or produced no baseline" — was emitted verbatim with
        # `exit=0` in it, i.e. it reported a FAILED run for a tool that had
        # exited zero. They are different faults and they point at different
        # code: a non-zero rc is the simulator; rc 0 with no GOLDEN line is the
        # generated testbench.
        if ec != 0:
            rep["reason"] = (
                f"iverilog/vvp injection run FAILED (exit={ec}) — no result "
                f"was produced, so diagnostic coverage is UNMEASURED (null), "
                f"not 0 %")
        else:
            rep["reason"] = (
                "iverilog/vvp injection ran and exited 0 but emitted NO golden "
                "baseline line, so no fault result could be read — the "
                "generated testbench, not the simulator. Diagnostic coverage "
                "is UNMEASURED (null), not 0 %")
        rep["baseline_valid"] = False
        rep["measured"] = False
        rep["injection_exit_code"] = ec
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
        # DISCLOSED SKIP, not a plain PASS. This branch exits 0 on every
        # non-safety design — the majority — so it IS the default outcome of
        # the FMEDA step, and until the token below existed the step resolved
        # to the plain PASS bucket: an unmeasured diagnostic-coverage figure
        # that read as a measured one. The LINE-START `VACUOUS_PASS:` token is
        # the rc-0 disclosure channel `flow_compliance_check.
        # _stdout_signals_vacuous` reads, and the report's own
        # `verdict=NOT_APPLICABLE` / `applicable=false` remain untouched.
        #
        # The reason goes FIRST and the token line LAST, and the token line is
        # LENGTH-BOUNDED. The consumer's window is `stdout[-300:]` (see
        # `_check_program_exit_zero`), so a token printed ahead of a long
        # reason is sliced off mid-line and the disclosure silently reverts to
        # a plain PASS — measured on the `UNMEASURED_NO_RTL_READ` reason, which
        # is longer than the window.
        reason = str(rep.get("reason", ""))
        if reason:
            print(f"fmeda_fault_injection_coverage: {rep['verdict']} — {reason}")
        print(_vacuous_token_line(rep["verdict"]))
    elif rep.get("diagnostic_coverage_pct") is not None:
        print(f"fmeda_fault_injection_coverage: DC="
              f"{rep['diagnostic_coverage_pct']:.2f}% "
              f"({rep['detected_faults']}/{rep['injected_faults']}) "
              f"floor={rep['dc_floor_pct']} ASIL-{rep['asil']} "
              f"→ {rep['verdict']}")
    elif rep.get("measured") is False and "mechanism" in rep:
        # Applicable safety design, injection produced nothing. The number is
        # UNMEASURED and must print as such — `DC=0.00% (0/0)` read as a
        # measured coverage of zero on every downstream eye, human or machine.
        print(f"fmeda_fault_injection_coverage: DC=UNMEASURED "
              f"(0 faults injected) floor={rep['dc_floor_pct']} "
              f"ASIL-{rep['asil']} → {rep['verdict']} — "
              f"{rep.get('reason', '')}")
    else:
        # Applicable but UNMEASURABLE (e.g. the --rtl-dir input is absent or
        # holds no source). Never a vacuous pass: there is no DC to print and
        # the exit code is non-zero.
        print(f"fmeda_fault_injection_coverage: {rep.get('verdict')} — "
              f"{rep.get('reason', '')}")
    if exit_code != 0:
        print(f"  (see {out_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
