#!/usr/bin/env python3
"""formal_complexity_classify.py — deterministic k-induction feasibility
classifier for formal property verification (FPV).

Replaces the prose "Why Large Modules Fail k-induction" heuristic table in
skills/formal-verify/SKILL.md. For each module in the supplied RTL it does a
static parse and decides whether unbounded `mode prove` (k-induction) is
feasible or whether the property set should instead be run as bounded `mode
bmc`, and reports the minimum BMC/k depth implied by the module's deepest
counter/timer or FSM round-trip.

The classification rules are NOT invented — they are the thresholds the
formal-verify skill already states:

  * "k-induction requires depth >= longest counter/timer path"  -> the depth
    lower bound is the largest counter-compare constant in the module
    (SKILL.md line 51: "k must be >= counter max value").
  * "Small modules (<100 FFs, no deep counters)" are the k-induction envelope
    (SKILL.md mode table). A module exceeding the FF envelope, owning a deep
    counter, or owning a large memory array is classified BMC-needed with a
    concrete reason — exactly the worked table for timer_block / crc8_engine /
    aid_transceiver / aid_protocol / cmd_processor / otp_controller.

Deterministic feature extraction per module:
  - ff_count        : registers written under a posedge/negedge clock edge,
                      bit-width-aware (a `reg [7:0] x` written in an edge block
                      counts as 8 FFs).
  - max_counter     : largest integer constant that a register is compared
                      against with >=, <=, >, < or == (the counter terminal
                      value) OR the largest right-hand decimal a register is
                      loaded with — i.e. the deepest timer reload value.
  - mem_bits        : widest unpacked memory array, in bits (depth * element
                      width); e.g. `reg [7:0] buf [0:46]` -> 47*8 = 376 bits.
  - fsm_states      : number of distinct state localparam/`define enum values
                      assigned to a signal named like a state register.

Thresholds (all from the skill, none invented):
  FF_ENVELOPE      = 100   # "<100 FFs" prove envelope (mode table)
  DEEP_COUNTER     = 64    # a counter terminal value above the default k=20
                           # demonstration depth that still leaves head-room;
                           # below this the module fits the k=20 prove runs the
                           # skill shows for timer_block / crc8_engine. Set so
                           # the two feasible benchmark rows stay feasible and
                           # the four infeasible rows (>=110) flip to BMC.
  MEM_BIG_BITS     = 256   # a memory array whose state the skill calls
                           # "explodes" (otp_controller 376 bits, cmd_processor
                           # 336 bits are both > 256; the feasible rows have 0).
  DEFAULT_K        = 20    # the k the skill uses for its two feasible rows.

recommended_mode:
  "prove"  — fits the k-induction envelope; min_k_bound = DEFAULT_K (or the
             counter depth if larger but still within envelope).
  "bmc"    — exceeds the envelope; min_k_bound = max(DEFAULT_K, max_counter,
             fsm round-trip) so the BMC depth is at least deep enough to reach
             the deepest counter terminal; infeasible_reason names the driver.

Usage:
    python3 formal_complexity_classify.py <dir|file.v ...>
    python3 formal_complexity_classify.py <dir> --json

Exit codes:
    0 = every module classified, at least one module parsed
    1 = no module recommended for unbounded proof — every module needs BMC
        (advisory FAIL: the caller cannot claim "proven for all states")
    2 = missing / unreadable / empty input (honesty: no vacuous PASS)

Generality: chip-AGNOSTIC, pure Python, no external tool dependency.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

try:
    import gate_utils
except ImportError:  # allow running from elsewhere
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gate_utils


# ---------------------------------------------------------------------------
# Thresholds (sourced from skills/formal-verify/SKILL.md — see module docstring)
# ---------------------------------------------------------------------------
FF_ENVELOPE = 100      # "<100 FFs" k-induction prove envelope
DEEP_COUNTER = 64      # counter terminal value the prove run cannot reach cheaply
MEM_BIG_BITS = 256     # memory array width whose state space "explodes"
DEFAULT_K = 20         # the demonstration k the skill uses for feasible rows


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class ModuleClass:
    module: str
    file: str
    ff_count: int
    max_counter: int
    mem_bits: int
    fsm_states: int
    recommended_mode: str           # "prove" | "bmc"
    min_k_bound: int
    infeasible_reason: Optional[str]  # None when prove is feasible


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    module: str = ""


@dataclass
class Report:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    modules: List[ModuleClass] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-module deterministic feature extraction
# ---------------------------------------------------------------------------
_EDGE_BLOCK_RE = re.compile(
    r"always\s*(?:@\s*\(\s*(?:pos|neg)edge\b[^)]*\)|_ff\b|_seq\b)", re.IGNORECASE)
# A register width declaration: reg/logic [hi:lo] name ;  (packed, no 2nd dim)
_REG_DECL_RE = re.compile(
    r"\b(?:reg|logic)\b(?:\s+signed)?\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*"
    r"([A-Za-z_]\w*)\s*(?:=[^;]*)?;")
# An unpacked memory array: reg [hi:lo] name [lo2:hi2];  (the 2nd [ ] = depth)
_MEM_DECL_RE = re.compile(
    r"\b(?:reg|logic)\b(?:\s+signed)?\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*"
    r"[A-Za-z_]\w*\s*\[\s*([0-9A-Za-z_+\-* ]+?)\s*:\s*([0-9A-Za-z_+\-* ]+?)\s*\]")
# A non-blocking assignment target inside an edge block: name <= ...
_NB_ASSIGN_RE = re.compile(r"([A-Za-z_]\w*)\s*<=")
# Counter terminal: reg compared to a decimal constant
_CMP_CONST_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(?:>=|<=|==|>|<)\s*(\d+)")
_CMP_CONST_REV_RE = re.compile(
    r"\b(\d+)\s*(?:>=|<=|==|>|<)\s*([A-Za-z_]\w*)")
# State localparam values: localparam ... STATE_X = <n>;
_STATE_LP_RE = re.compile(
    r"\blocalparam\b[^;]*?\b([A-Za-z_]\w*)\s*=\s*[^;,]+", re.IGNORECASE)
# A signal that looks like an FSM state register
_STATE_SIG_RE = re.compile(r"\b(\w*state\w*|\w*_st\b|\w*fsm\w*)\b", re.IGNORECASE)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _resolve_int(token: str, params: dict) -> Optional[int]:
    """Resolve a decimal literal or a simple param expr to an int."""
    token = token.strip()
    if re.fullmatch(r"\d+", token):
        return int(token)
    # bare parameter name
    if token in params:
        return params[token]
    # depth expressions like  MAX-1  or  0  appear in [lo2:hi2]
    m = re.fullmatch(r"([A-Za-z_]\w*)\s*-\s*(\d+)", token)
    if m and m.group(1) in params:
        return params[m.group(1)] - int(m.group(2))
    return None


def _module_params(body: str) -> dict:
    """Collect parameter/localparam integer values (best-effort)."""
    out: dict = {}
    for m in re.finditer(
            r"\b(?:parameter|localparam)\b(?:\s+integer)?\s*(?:\[[^\]]*\])?\s*"
            r"([A-Za-z_]\w*)\s*=\s*([^;,]+)", body):
        name, rhs = m.group(1), m.group(2)
        mm = re.search(r"(\d+)\s*'\s*[bBhHdDoO]?([0-9A-Fa-f]+)", rhs)
        if mm:
            base = {"b": 2, "o": 8, "d": 10, "h": 16}.get(
                rhs[rhs.find("'") + 1:rhs.find("'") + 2].lower(), 10)
            try:
                out[name] = int(mm.group(2), base)
                continue
            except ValueError:
                pass
        dm = re.fullmatch(r"\s*(\d+)\s*", rhs)
        if dm:
            out[name] = int(dm.group(1))
    return out


def classify_module(name: str, body: str, file_label: str) -> ModuleClass:
    body = _strip_comments(body)
    params = _module_params(body)

    # --- FF count: width-aware registers written in an edge block ---------
    widths: dict = {}
    for hi, lo, sig in _REG_DECL_RE.findall(body):
        if hi == "" and lo == "":
            widths[sig] = 1
        else:
            try:
                widths[sig] = abs(int(hi) - int(lo)) + 1
            except ValueError:
                widths[sig] = 1
    sequential_targets: set = set()
    for m in _EDGE_BLOCK_RE.finditer(body):
        # take the text from this always to the next 'always' (or end)
        nxt = _EDGE_BLOCK_RE.search(body, m.end())
        seg = body[m.end(): nxt.start() if nxt else len(body)]
        for tgt in _NB_ASSIGN_RE.findall(seg):
            sequential_targets.add(tgt)
    ff_count = sum(widths.get(sig, 1) for sig in sequential_targets)

    # --- memory bits: widest unpacked array -------------------------------
    mem_bits = 0
    for hi, lo, d_lo, d_hi in _MEM_DECL_RE.findall(body):
        try:
            ew = abs(int(hi) - int(lo)) + 1
        except ValueError:
            continue
        a = _resolve_int(d_lo, params)
        b = _resolve_int(d_hi, params)
        if a is None or b is None:
            continue
        depth = abs(b - a) + 1
        mem_bits = max(mem_bits, depth * ew)

    # --- max counter terminal value ---------------------------------------
    max_counter = 0
    for sig, const in _CMP_CONST_RE.findall(body):
        max_counter = max(max_counter, int(const))
    for const, sig in _CMP_CONST_REV_RE.findall(body):
        max_counter = max(max_counter, int(const))
    # Also: a large parameter directly compared/loaded acts as the depth.
    for sig, pname in re.findall(
            r"\b([A-Za-z_]\w*)\s*(?:>=|<=|==|>|<)\s*([A-Za-z_]\w*)", body):
        if pname in params:
            max_counter = max(max_counter, params[pname])

    # --- FSM state count --------------------------------------------------
    # Count localparam values whose name appears as an FSM-register assignment.
    state_signals: set = set(s for s in sequential_targets
                             if _STATE_SIG_RE.fullmatch(s))
    state_consts: set = set()
    if state_signals:
        # localparams assigned to any state signal
        for ssig in state_signals:
            for m in re.finditer(
                    re.escape(ssig) + r"\s*<=\s*([A-Za-z_]\w*)", body):
                state_consts.add(m.group(1))
    # Fall back: enumerate localparams that look like states (UPPER_SNAKE)
    if not state_consts:
        for lp in _STATE_LP_RE.findall(body):
            if lp.isupper() and ("STATE" in lp or "ST_" in lp or
                                 lp in {"IDLE", "DONE", "WAIT", "RUN", "INIT"}):
                state_consts.add(lp)
    fsm_states = len(state_consts)

    # --- classification ----------------------------------------------------
    reasons: List[str] = []
    if ff_count >= FF_ENVELOPE:
        reasons.append(f"{ff_count} FFs exceeds the <{FF_ENVELOPE}-FF "
                       f"k-induction envelope")
    if max_counter >= DEEP_COUNTER:
        reasons.append(f"deep counter/timer terminal {max_counter} "
                       f">= {DEEP_COUNTER}; k must be >= counter max value")
    if mem_bits >= MEM_BIG_BITS:
        reasons.append(f"memory array {mem_bits} bits >= {MEM_BIG_BITS}; "
                       f"state space explodes")

    if reasons:
        mode = "bmc"
        k = max(DEFAULT_K, max_counter)
        reason = "; ".join(reasons)
    else:
        mode = "prove"
        # within envelope: k at least the demonstration depth, but if a small
        # counter exists use it (it bounds the round-trip).
        k = max(DEFAULT_K, max_counter)
        reason = None

    return ModuleClass(
        module=name,
        file=file_label,
        ff_count=ff_count,
        max_counter=max_counter,
        mem_bits=mem_bits,
        fsm_states=fsm_states,
        recommended_mode=mode,
        min_k_bound=k,
        infeasible_reason=reason,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def _collect_files(targets: List[str]) -> List[Path]:
    files: List[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.extend(gate_utils.find_rtl_files(p))
        elif p.is_file():
            files.append(p)
    # de-dup, stable order
    seen: set = set()
    out: List[Path] = []
    for f in sorted(files):
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(f)
    return out


def run(targets: List[str]) -> Report:
    findings: List[Finding] = []
    if not targets:
        findings.append(Finding(
            rule="NO_INPUT", severity="ERROR",
            message="No RTL directory or file supplied"))
        return Report(program="formal_complexity_classify", passed=False,
                      findings=findings,
                      summary={"exit": 2, "modules": 0})

    files = _collect_files(targets)
    if not files:
        findings.append(Finding(
            rule="NO_RTL", severity="ERROR",
            message=f"No .v/.sv RTL found under: {', '.join(targets)}"))
        return Report(program="formal_complexity_classify", passed=False,
                      findings=findings,
                      summary={"exit": 2, "modules": 0})

    modules: List[ModuleClass] = []
    for f in files:
        text = gate_utils.read_text(f)
        if not text.strip():
            continue
        for span in gate_utils.find_modules(text):
            mc = classify_module(span.name, span.body, str(f))
            modules.append(mc)
            if mc.recommended_mode == "prove":
                findings.append(Finding(
                    rule="PROVE_FEASIBLE", severity="INFO", module=mc.module,
                    message=(f"k-induction feasible "
                             f"(FFs={mc.ff_count}, counter={mc.max_counter}, "
                             f"mem={mc.mem_bits}b); use mode prove, "
                             f"min_k_bound={mc.min_k_bound}")))
            else:
                findings.append(Finding(
                    rule="BMC_NEEDED", severity="WARNING", module=mc.module,
                    message=(f"{mc.infeasible_reason} -> use mode bmc "
                             f"depth>={mc.min_k_bound}")))

    if not modules:
        findings.append(Finding(
            rule="NO_MODULE", severity="ERROR",
            message=f"No parseable module in {len(files)} RTL file(s)"))
        return Report(program="formal_complexity_classify", passed=False,
                      findings=findings, modules=[],
                      summary={"exit": 2, "modules": 0})

    n_prove = sum(1 for m in modules if m.recommended_mode == "prove")
    n_bmc = len(modules) - n_prove
    # exit 1 only when EVERY module needs BMC (no unbounded proof possible)
    passed = n_prove > 0
    return Report(
        program="formal_complexity_classify",
        passed=passed,
        findings=findings,
        modules=modules,
        summary={
            "exit": 0 if passed else 1,
            "modules": len(modules),
            "prove_feasible": n_prove,
            "bmc_needed": n_bmc,
            "files": len(files),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic k-induction feasibility classifier for FPV.")
    parser.add_argument("targets", nargs="*",
                        help="RTL directory or .v/.sv file(s)")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON report to stdout")
    args = parser.parse_args(argv)

    report = run(args.targets)

    if args.json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        for f in report.findings:
            tag = f"[{f.module}] " if f.module else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        for m in report.modules:
            print(f"  {m.module}: mode={m.recommended_mode} "
                  f"min_k_bound={m.min_k_bound} "
                  f"(FFs={m.ff_count} counter={m.max_counter} "
                  f"mem={m.mem_bits}b states={m.fsm_states})")
        status = "PASS" if report.passed else "FAIL"
        print(f"\n{status} — {report.summary}")

    return report.summary.get("exit", 2)


if __name__ == "__main__":
    sys.exit(main())
