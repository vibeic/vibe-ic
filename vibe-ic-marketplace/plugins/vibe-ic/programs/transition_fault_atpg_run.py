#!/usr/bin/env python3
"""transition_fault_atpg_run.py — REAL open-source TRANSITION-DELAY-FAULT (TDF)
ATPG via the forked vibeic/yosys SAT engine (launch-off-capture, 2-frame).

This CLOSES the long-standing "OSS has no delay-fault ATPG" gap. The stuck-at
producer (`fault_atpg_run.py`, AUCOHL/Fault) is a single-pattern combinational
engine and honestly records `transition.engine_limited=true` — it CANNOT
generate at-speed two-pattern tests. This program does, by reducing a
transition fault under full-scan launch-off-capture (LOC) to a STUCK-AT fault
on a TWO-TIME-FRAME UNROLLING of the combinational core and solving it with
Yosys `sat -prove`.

──────────────────────────────────────────────────────────────────────────
THE REDUCTION (proven, not hand-waved — see the PROOF block at bottom):

  A transition fault at line L under LOC == a stuck-at on a 2-frame unroll:
    frame-1 INITIALISES the fault site (the "from" value of the transition),
    frame-2 LAUNCHES the v->v̄ transition and is where the stuck-at is injected.
      slow-to-rise  (STR)  ⇒  SA0 in the launch frame, frame-1 init L=0
      slow-to-fall  (STF)  ⇒  SA1 in the launch frame, frame-1 init L=1

  Under LOC the primary inputs are HELD constant across the launch→capture
  at-speed window; the transition is created only by the flop-state change
  S1→S2 (frame-1 D  →  frame-2 Q). So the 2-frame unroll is:

     frame1 (good):  core(PI, Q=S1)              -> D=S2, PO1
     frame2 (good):  core(PI, Q=S2)              -> D2g,  PO2g
     frame2 (faulty):core(PI, Q=S2)  L stuck     -> D2f,  PO2f
     trig = OR over frame-2 pseudo-POs of (good != faulty)

  `sat -prove trig 0` proves trig can never be 1; a COUNTEREXAMPLE (SAT model)
  is the launch-capture 2-pattern that DETECTS the fault; UNSAT (proof holds)
  means the transition fault is REDUNDANT / undetectable. The frame-1 init
  value is imposed with `sat -set f1.<L> <init>` so a genuine v→v̄ transition
  is launched (not a mere stuck-at test).

  NOTE (empirical): the sequential-miter `sat -seq 2` form collapses under
  `prep` optimisation. The EXPLICIT 2-frame unroll (core instantiated 3×,
  frame1.D wired to frame2.Q) is reliable and is what this program builds.

──────────────────────────────────────────────────────────────────────────
FLOW (cut → enumerate → 2-frame unroll → sat -prove → grade):

  1. CUT  — reuse the combinational full-scan core: `fault cut` turns every
     DFF into a pseudo-PI (flop Q, named `<flop>`) + pseudo-PO (flop D, named
     `<flop>.d`). If phase2/stage2/dft/cut_netlist.v already exists (Step 11
     ran `fault_atpg_run` first) it is reused; otherwise `fault cut` is run.
  2. GATE-LEVELISE — read the design liberty AS LOGIC (`read_liberty
     -ignore_miss_func`, PDK-agnostic — no proprietary Verilog sim model
     needed), flatten the cut core to generic `$_*_` gates, opt_clean, and
     write flat_core.v. The surviving internal nets are the fault sites.
  3. ENUMERATE — 2 TDF faults per internal net (STR: SA0/init0, STF:
     SA1/init1). Stuck-at fault collapsing is inherited from the gate-level
     net set (one representative net per driver output). A DISCLOSED bounded
     sample is taken for large designs (never a SILENT cap — sampled_faults
     vs total_faults are both reported).
  4. UNROLL + SOLVE — build the explicit 3-instance LOC miter once, then per
     fault: copy the core, inject the launch-frame stuck-at with
     `connect -set`, flatten the miter, and run `sat -prove trig 0
     -set f1.<net> <init>`. SAT(model) → detected (2-pattern recorded);
     UNSAT → redundant; abort/timeout → UNDETECTED (fail-safe, never counted
     as detected).
  5. GRADE — measured TDF LOGIC coverage = detected/(sampled − redundant)
     (test coverage) and detected/sampled (fault coverage); both denominators
     disclosed. Writes reports/phase2/dft/transition_coverage.json.

FALSE-CLEAN-PROOF: a redundant or aborted fault is NEVER counted as detected
(only a `model found: FAIL!` SAT verdict counts). Proven by construction and
by the unit test's soundness fixture (a known-redundant fault ⇒ UNSAT/
undetected; a known-detectable fault ⇒ SAT/detected).

HONEST DISCLOSURE (written into the JSON): this is TDF **LOGIC** coverage
(the transition is launched AND observed at a scan-observable point); it is
**NOT at-speed timing-graded**. True at-speed path-delay-fault grading needs
OpenSTA K-longest-path sensitisation to prove the launched transition is on a
path slow enough to fail the rated cycle — a deferred, harder tier.

Usage:
    python3 transition_fault_atpg_run.py <project_dir> \\
        --clock clk \\
        [--netlist phase2/stage2/synth/spm_synth.v] \\
        [--cut-netlist phase2/stage2/dft/cut_netlist.v] \\
        [--liberty input/pdk/liberty/<pdk>_typ.lib] \\
        [--top spm] [--dff-cells DFFHQD1] \\
        [--floor 90] [--max-faults 400] [--json <out>]

Exit 0 = TDF logic coverage >= floor (or NOT_APPLICABLE: no sequential logic,
         established from the design's own Liberty — see below).
Exit 1 = TDF logic coverage below floor OR the ATPG could not run OR BLOCKED.
Exit 2 = usage / IO error.

NOT_APPLICABLE IS EARNED, NOT ASSUMED. A design self-skips only when its own
Liberty declares sequential cells and the netlist instantiates none of them. If
the Liberty cannot be reached, the design's sequential content was never
checked, and the verdict is BLOCKED (exit 1) — "we could not verify" — rather
than a NOT_APPLICABLE that reads downstream as a clean skip. If the design DOES
have sequential cells and the cut exposed none, that is ERROR: a scan-insertion
result of zero flops on a sequential design is a failure, not a skip.

The floor is enforced by the sibling gate `transition_coverage_check.py`; this
producer's own exit mirrors it for convenience but the gate is authoritative.
chip-AGNOSTIC — no design-specific knowledge.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _watchdog as _wd  # noqa: E402  progress-stall supervision (v1.3.47)

try:  # sibling module; programs/ is on sys.path when run as a script
    import _docker_memory as _dmem
except ImportError:  # pragma: no cover - packaged/flattened layouts
    from . import _docker_memory as _dmem  # type: ignore

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None

# Reuse the pinned EDA image + DFF auto-detection from the stuck-at producer so
# there is a SINGLE pinned `vibeic-eda:X.Y.Z` literal (tracked by
# tools/vibeic-eda/sync_image_version.py) — this file adds none of its own.
try:
    import fault_atpg_run as _far  # type: ignore
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fault_atpg_run as _far  # type: ignore


_PROGRAM = "transition_fault_atpg_run"
_VERSION = "1.0.0"

# Chosen TDF LOGIC-coverage floor. A few points below the 95 % stuck-at
# foundry bar because at-speed escapes are harder AND because this is a
# *logic* (not timing-graded) measurement — see the disclosure. Configurable.
TDF_LOGIC_FLOOR_DEFAULT = 90.0

# Default disclosed sample cap. Each fault is one full SAT solve; for a large
# design the full 2×|nets| fault list is bounded to keep the step tractable.
# NEVER a silent cap — total vs sampled are always reported.
DEFAULT_MAX_FAULTS = 400

# #154 — the dominant per-fault cost is the SAT solve on the 3×-instantiated
# 2-frame miter (measured ~20-25 s/fault on a 461 k-var CNF for a 1.6 k-flop
# sha256; the per-fault flatten is <1 s). At DEFAULT_MAX_FAULTS × 25 s ≈ 2.8 h
# a single 1800 s batch is killed by the wall long before any verdict is parsed
# → the OLD producer scored every fault ABORT → 0 % on a design with REAL
# coverage. Three chip-AGNOSTIC levers now keep a real number landing:
#   (b) FLATTEN-ONCE: the faulty core copy + the 3×-core miter are built and
#       flattened ONE time (`design -save`); each fault reloads that flat
#       snapshot and injects the launch-frame stuck-at directly on the flat
#       faulty-instance net (no per-fault copy/hierarchy/flatten). Verdict-
#       identical to the per-fault-flatten recipe (proven by an A/B parity run).
#   (c) BUDGET-AWARE RIGHT-SIZING: a tiny calibration probe measures the real
#       per-fault SAT seconds on THIS design, then the sample is sized so the
#       batch COMPLETES within the wall budget — a smaller-but-fully-graded,
#       design-spread sample beats a 400-fault batch that all-ABORTs.
#   (outlier guard) a per-fault `sat -timeout` caps ONE pathological deep-cone
#       fault so it cannot stall the whole batch; an undecided fault is a
#       conservative ABORT (undetected), never a false detection.
# The honest disclosure that this is TDF LOGIC coverage (not at-speed timing-
# graded) is unchanged.
DEFAULT_PER_FAULT_SAT_TIMEOUT = 180   # s; generous (normal solves finish first)
_CALIBRATION_FAULTS = 3               # tiny strided probe to measure per-fault s
_BUDGET_SAFETY = 0.85                 # leave head-room for parse / SIGKILL slack
_SETUP_MARKER = "VIBEICTDF_SETUP_DONE"

# ── external CDCL SAT solver for the ATPG prove (fork enhancement) ───────────
# The built-in ezMiniSAT (MiniSAT-2.2, 2008-era) that yosys `sat` uses by
# default TIMES OUT on the large 2-frame launch-off-capture miter CNFs this
# producer builds (measured on a real bit-serial core: ~5.5e5 vars / ~1.4e6
# clauses per fault; MiniSAT ~25 s/fault and ABORTs the hard cones at the
# per-fault timeout). A modern CDCL solver decides the SAME CNF in seconds — and
# reaches the UNSAT proofs MiniSAT never finishes, correctly classifying some
# "aborts" as REDUNDANT instead of leaving them undetected. The vibeic/yosys
# fork registers `kissat` and `cadical` as selectable `sat` backends (see
# kernel/register.cc ExtCdclSat); this producer selects one via
# `sat -select-solver <name>` WHEN the image provides it, and otherwise falls
# back to the built-in engine with no behaviour change. Preference order + a
# hard override are exposed via VIBEIC_ATPG_SAT_SOLVER
# (auto|kissat|cadical|minisat|none). chip/PDK/vendor-AGNOSTIC — pure CNF
# solving, no design knowledge.
_ATPG_SAT_SOLVER_PREFERENCE = ("kissat", "cadical")
_SAT_SOLVER_PROBE_CACHE: dict = {}

# ── size-scaled at-speed ATPG wall budget ───────────────────────────────────
# The per-fault SAT solve on the 2-frame LOC miter dominates, and BOTH its
# per-fault cost AND the one-time miter flatten grow with the design's flop
# count. A FIXED wall (the old 1800 s) therefore does two harmful things on a
# large design and nothing on a small one:
#   (a) it grades only a small strided slice of the disclosed sample — measured
#       on subservient×GF180MCU (1272 scan flops, ~24 k-cell flat 2-frame miter,
#       isolated --cpus=20 container): flatten ~8 s, per-fault SAT ~25 s, so a
#       1800 s wall right-sizes to only ~57 of the 400-fault disclosed sample,
#       while a 65-flop design grades its full sample; and
#   (b) under host contention the fixed calibration ceiling can kill the
#       one-time flatten BEFORE the probe emits its setup marker (yosys exit
#       124, setup_done=False), which the producer then books as a hard ERROR —
#       a false timeout, not an honest coverage number.
# So the wall AND the calibration setup-allowance SCALE with the design's own
# measured scale (the scan-flop count the cut exposed). The caller's --timeout
# is the FLOOR (small designs are unchanged); a large design earns proportially
# more wall, capped. Chip/PDK/vendor-AGNOSTIC — keyed ONLY on flop count, never
# on a chip / SKU / library literal.
WALL_PER_SCAN_FLOP = 3.0              # s/flop added above the floor. Measured:
                                     # 1272 flops → 1800+3·1272 ≈ 5.6 k s →
                                     # right-sizes to ~190 of the 400 disclosed
                                     # faults (vs ~57 under the fixed 1800 s).
WALL_BUDGET_MAX = 7200               # s (2 h) — campaign safety ceiling so an
                                     # arbitrarily large design cannot run away.
SETUP_ALLOWANCE_FLOOR = 120          # s — min one-time flatten allowance (was a
                                     # fixed 60 s baked into cal_wall).
SETUP_ALLOWANCE_PER_SCAN_FLOP = 0.5  # s/flop — the miter flatten grows with the
                                     # flop count; 1272 flops → +636 s head-room.

_DISCLOSURE = (
    "TDF LOGIC coverage (each fault's transition is LAUNCHED in frame-1 and "
    "OBSERVED at a scan-observable frame-2 pseudo-PO via a real Yosys SAT "
    "proof); NOT at-speed timing-graded. True at-speed path-delay-fault "
    "grading needs OpenSTA K-longest-path sensitisation to prove the launched "
    "transition lies on a path slow enough to fail the rated cycle (deferred "
    "harder tier)."
)


# ══════════════════════════════════════════════════════════════════════════
# PURE helpers (unit-tested; no Docker, no IO)
# ══════════════════════════════════════════════════════════════════════════

_PORT_RE = re.compile(
    r'^\s*(input|output)\s+(\[[^\]]*\]\s*)?(\\?[^\s;]+)\s*;', re.MULTILINE)
_WIRE_RE = re.compile(
    r'^\s*wire\s+(\[[^\]]*\]\s*)?(\\?[^\s;]+)\s*;', re.MULTILINE)
_MODULE_RE = re.compile(r'^\s*module\s+(\\?[^\s(]+)', re.MULTILINE)


def esc_id(name: str) -> str:
    """Return `name` as a Verilog identifier safe for an instance-port
    connection. A bare name that already needs no escaping is returned as-is;
    a name containing a dot/backslash (e.g. the cut engine's `_392_.d`
    pseudo-PO) is emitted as an escaped identifier `\\name ` (trailing space
    is REQUIRED by Verilog to terminate an escaped id). Pure."""
    raw = name.lstrip('\\').rstrip()  # trailing space is an escaped-id delimiter
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', raw):
        return raw
    return "\\" + raw + " "


def _base_of_d(name: str) -> str | None:
    """A pseudo-PO is named `<base>.d` (the flop's D input, made observable by
    the scan cut). Return `<base>` or None. Pure."""
    n = name.lstrip('\\')
    return n[:-2] if n.endswith('.d') else None


def parse_cut_ports(verilog_text: str):
    """Classify the cut core's ports. Returns
        (top, prim_in, prim_out, pairs)
    where prim_in/prim_out are lists of (name, range_str) and pairs is a list
    of (base, pi_name, po_name) — the pseudo-PI (flop Q, name==base) matched
    to its pseudo-PO (flop D, name==`base.d`). Primary I/O are the ports that
    are NOT part of a pseudo pair. Pure. chip-AGNOSTIC."""
    mtop = _MODULE_RE.search(verilog_text)
    top = mtop.group(1).lstrip('\\') if mtop else "top"
    ins, outs = [], []
    for m in _PORT_RE.finditer(verilog_text):
        kind, rng, name = m.group(1), (m.group(2) or "").strip(), m.group(3)
        (ins if kind == "input" else outs).append((name, rng))
    pso = {}
    for name, _ in outs:
        b = _base_of_d(name)
        if b is not None:
            pso[b] = name
    inmap = {n.lstrip('\\'): n for n, _ in ins}
    pairs = [(b, inmap[b], pso[b]) for b in pso if b in inmap]
    pair_bases = {b for b, _, _ in pairs}
    prim_in = [(n, r) for n, r in ins if n.lstrip('\\') not in pair_bases]
    prim_out = [(n, r) for n, r in outs if _base_of_d(n) is None]
    return top, prim_in, prim_out, pairs


def enumerate_fault_sites(flat_verilog_text: str) -> list[str]:
    """Return the internal single-bit nets of the flattened gate core (the
    stuck-at / TDF fault sites) — every declared `wire` that is not a port and
    not a bus. Bus/port nets are excluded so each site is a scalar gate-output
    net (standard gate-output fault collapsing). Pure."""
    ports = {m.group(3).lstrip('\\') for m in _PORT_RE.finditer(flat_verilog_text)}
    sites = []
    for m in _WIRE_RE.finditer(flat_verilog_text):
        rng, name = m.group(1), m.group(2)
        if rng:  # skip buses — keep scalar nets only
            continue
        raw = name.lstrip('\\')
        if raw in ports:
            continue
        sites.append(name)
    # stable de-dup
    seen, out = set(), []
    for s in sites:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def enumerate_tdf_faults(nets: list[str]) -> list[tuple[str, str, str, str]]:
    """Two transition faults per net: (net, kind, stuck_value, init_value).
      STR (slow-to-rise): SA0 in launch frame, init 0  → 0→1 must be launched
      STF (slow-to-fall): SA1 in launch frame, init 1  → 1→0 must be launched
    Pure."""
    faults = []
    for n in nets:
        faults.append((n, "STR", "1'b0", "1'b0"))
        faults.append((n, "STF", "1'b1", "1'b1"))
    return faults


def sample_faults(faults: list, max_faults: int):
    """Deterministic, evenly-strided DISCLOSED sample. Returns
    (sampled_list, sampled_bool). When max_faults<=0 or >=len, returns all
    (sampled=False). The stride keeps the sample spread across the net order
    rather than truncating to a prefix. Pure."""
    total = len(faults)
    if max_faults <= 0 or total <= max_faults:
        return list(faults), False
    stride = total / float(max_faults)
    idx = sorted({int(i * stride) for i in range(max_faults)})
    return [faults[i] for i in idx], True


def parse_sat_verdict(body: str) -> str:
    """Classify ONE Yosys `sat -prove` output block.
      'DET'   — `model found: FAIL!`  (proof of trig==0 failed → detecting
                2-pattern found)
      'RED'   — `no model found: SUCCESS!` (proof holds → redundant/undetectable)
      'ABORT' — anything else (timeout / error / no verdict) → NOT detected.
    Pure. FALSE-CLEAN-PROOF: only an explicit `model found: FAIL!` is a
    detection; every ambiguous outcome is conservatively NOT a detection."""
    if "model found: FAIL" in body:
        return "DET"
    if "no model found: SUCCESS" in body:
        return "RED"
    return "ABORT"


def _extract_pattern(body: str, prim_in_names: list[str]) -> dict | None:
    """Pull the primary-input values of the detecting 2-pattern out of a
    `sat -show` block. Returns {name: binvalue} or None. Pure."""
    pat = {}
    for m in re.finditer(r'\\?([A-Za-z_][\w.$]*)\s+\d+\s+[0-9a-fA-Fx]+\s+([01xz]+)\s*$',
                         body, re.MULTILINE):
        name, binv = m.group(1), m.group(2)
        if name in prim_in_names:
            pat[name] = binv
    return pat or None


def coverage_math(detected: int, redundant: int, aborted: int) -> dict:
    """TDF coverage from raw verdict counts. Independently recomputable by the
    gate. Pure.

      sampled            = detected + redundant + aborted
      test_coverage_pct  = detected / (sampled - redundant)   [redundant
                            excluded from the denominator; aborted stays as
                            NOT-detected → conservative]
      fault_coverage_pct = detected / sampled
    Aborted faults are counted as undetected in BOTH ratios (never detected)."""
    sampled = detected + redundant + aborted
    testable = sampled - redundant
    test_cov = (100.0 * detected / testable) if testable > 0 else None
    fault_cov = (100.0 * detected / sampled) if sampled > 0 else None
    return {
        "sampled_faults": sampled,
        "detected": detected,
        "redundant": redundant,
        "aborted": aborted,
        "testable_faults": testable,
        "tdf_test_coverage_pct": (round(test_cov, 4)
                                  if test_cov is not None else None),
        "tdf_fault_coverage_pct": (round(fault_cov, 4)
                                   if fault_cov is not None else None),
    }


def build_loc_miter(top: str, prim_in, prim_out, pairs,
                    faulty_suffix: str = "_f") -> str:
    """Emit the explicit LOC 2-frame unroll miter (pure — the whole point of
    the reliable-form note above). Instantiates the core three times:
      f1  (good)   : frame-1, free flop-init state on the pseudo-PI
      g2  (good)   : frame-2, pseudo-PI driven by f1's pseudo-PO  (LAUNCH)
      fb  (`<top>_f`): frame-2 FAULTY copy, same launched state
    Primary inputs are SHARED across the three (LOC holds PI constant). trig
    ORs every frame-2 pseudo-PO good-vs-faulty difference (flop D scanned out
    + primary POs both observable). Free miter inputs: primary inputs + one
    `<base>_q` per flop (the scanned-in init state S1)."""
    def cid(b):  # clean signal id per flop base
        return "s" + re.sub(r'\W', '_', b)

    L = []
    hdr = [n for n, _ in prim_in] + [cid(b) + "_q" for b, _, _ in pairs] + ["trig"]
    L.append("module miter(" + ", ".join(hdr) + ");")
    for n, r in prim_in:
        L.append(f"  input {r + ' ' if r else ''}{n};")
    for b, _, _ in pairs:
        L.append(f"  input {cid(b)}_q;")
    L.append("  output trig;")
    for b, _, _ in pairs:
        L.append(f"  wire {cid(b)}_f1d, {cid(b)}_g2d, {cid(b)}_fbd;")
    for n, _ in prim_out:
        L.append(f"  wire {n}_g2, {n}_fb, {n}_f1;")

    def instance(mod, iname, q_of, dsuf, posuf):
        c = [f".{n}({n})" for n, _ in prim_in]
        for b, pi, po in pairs:
            c.append(f".{esc_id(pi)}({q_of(b)})")
            c.append(f".{esc_id(po)}({cid(b)}_{dsuf})")
        for n, _ in prim_out:
            c.append(f".{n}({n}{posuf})")
        L.append(f"  {mod} {iname} (" + ", ".join(c) + ");")

    instance(top, "f1", lambda b: cid(b) + "_q", "f1d", "_f1")       # frame1 good
    instance(top, "g2", lambda b: cid(b) + "_f1d", "g2d", "_g2")     # frame2 good (launched)
    instance(top + faulty_suffix, "fb", lambda b: cid(b) + "_f1d",
             "fbd", "_fb")                                           # frame2 faulty (launched)

    terms = [f"({cid(b)}_g2d ^ {cid(b)}_fbd)" for b, _, _ in pairs]
    terms += [f"({n}_g2 ^ {n}_fb)" for n, _ in prim_out]
    L.append("  assign trig = " + (" | ".join(terms) if terms else "1'b0") + ";")
    L.append("endmodule")
    return "\n".join(L) + "\n"


# ══════════════════════════════════════════════════════════════════════════
# Docker / Yosys execution (impure)
# ══════════════════════════════════════════════════════════════════════════

def _as_text(v) -> str:
    """Coerce a subprocess output (str, bytes, or None) to str. Pure."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _run_in_docker(project: Path, shell_cmd: str, timeout: int,
                   pdk_dir: Path | None = None,
                   extra_mounts: list[tuple[str, str]] | None = None
                   ) -> tuple[int, str, str]:
    """Run a shell command inside vibeic-eda with project mounted at /work and
    yosys/fault on PATH. Reuses the pinned image from fault_atpg_run.

    extra_mounts: additional (host, container) bind mounts — used when a
    liberty/PDK file resolves (via symlink) to a path OUTSIDE the project, so
    a fresh `docker run -v project:/work` container can still read it."""
    # A unique --name so that if the watchdog's stall kill fires we can REAP
    # the container: killing the `docker run` CLIENT leaves the yosys process
    # inside the container orphaned and burning a full CPU indefinitely
    # (observed). Naming it lets the kill handler `docker rm -f` the orphan by
    # IDENTITY, never by matching a command line.
    cname = f"vibeic_tdf_{os.getpid()}_{time.time_ns() & 0xFFFFFFFF:x}"
    docker_cmd = [
        "docker", "run", "--rm", "--name", cname,
        *_dmem.docker_memory_flags(),
        "--entrypoint", "bash",
        "-v", f"{project}:/work",
    ]
    for host, ctr in (extra_mounts or []):
        docker_cmd += ["-v", f"{host}:{ctr}"]
    if pdk_dir is not None and pdk_dir.exists():
        docker_cmd += ["-v", f"{pdk_dir}:/pdk"]
    preamble = (
        "export FAULT_IVERILOG=/foss/tools/iverilog/bin/iverilog && "
        "export FAULT_YOSYS=/foss/tools/bin/yosys && "
        "export PATH=/foss/tools/yosys/bin:/foss/tools/iverilog/bin:"
        "/foss/tools/bin:$PATH && "
        "export LD_LIBRARY_PATH=/foss/tools/iverilog/lib:${LD_LIBRARY_PATH:-} && "
    )
    docker_cmd += [_far.DOCKER_IMAGE, "-c", preamble + shell_cmd]

    def _reap(proc, reason: str) -> None:
        """Kill the `docker run` CLIENT *and* the orphan it leaves behind.

        `run_host_supervised`'s default kill reaches only the client; the
        yosys inside the named container survives it and burns a CPU. The
        victim is selected by the unique `--name` this call minted, never by
        matching a command line, so a sibling run's healthy container can
        never be caught (see _watchdog's kill-by-IDENTITY note)."""
        try:
            proc.kill()
        except Exception:  # nosec — already gone
            pass
        try:
            # Cleanup only: nothing is recorded from this call's outcome, so
            # its bound cannot become a verdict about the subject.
            subprocess.run(["docker", "rm", "-f", cname],
                           capture_output=True, text=True, timeout=30)
        except Exception:
            pass

    def _cpu_probe(_proc):
        # MEASURED: the launched process here is the `docker run` CLIENT, and
        # its own /proc CPU sits FLAT for the whole run even while the
        # container burns a full core — over a 12s silent-CPU container job
        # the host-level probe read 0.00/0.00/0.01/0.01/0.01/0.01 (essentially
        # no signal at all: containerd-shim reparents the actual process, so
        # it is never a ppid-chain DESCENDANT of the CLI on the host's own
        # /proc). `run_host_supervised`'s default `cpu_probe` reads the
        # LAUNCHED PROCESS's own tree, which is exactly wrong for `docker
        # run`. `_watchdog`'s own module docstring names the fix — "docker
        # exec ps in-container" — read via `/proc` directly (no `ps` package
        # dependency inside the tool image) using the SAME utime+stime field
        # position `_watchdog._pid_cpu_s` reads on the host. The container is
        # `--rm --name cname` and EXCLUSIVELY this call's own, so every pid
        # inside it is this job's — no marker/identity filtering needed.
        # Without this, captured OUTPUT is the only signal, and yosys's
        # miter-flatten phase on a large design is exactly the quiet-but-
        # working stretch that signal cannot see either (`_docker_watchdog`'s
        # own `yosys-abc` finding: a healthy 1.8M-cell synth was killed by
        # output-only accounting during ABC's silent phase — the same shape
        # of defect).
        try:
            r = subprocess.run(
                ["docker", "exec", cname, "sh", "-c",
                 "cat /proc/[0-9]*/stat 2>/dev/null"],
                capture_output=True, text=True, timeout=15)
        except Exception:  # nosec — a probe failure is just "no reading"
            return None
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        tck = _wd._clk_tck()
        total = 0.0
        seen = False
        for line in r.stdout.splitlines():
            cut = line.rfind(")")
            if cut < 0:
                continue
            rest = line[cut + 2:].split()
            if len(rest) < 13:
                continue
            try:
                total += (float(rest[11]) + float(rest[12])) / tck
                seen = True
            except ValueError:  # nosec
                continue
        return total if seen else None

    # PROGRESS supervision, not a runtime guess (v1.3.47 / owner directive).
    # `timeout` becomes the STALL GRACE: how long every forward-progress
    # signal of the yosys tree (CPU, captured output) may sit flat before the
    # job is called hung. A long-but-WORKING SAT solve on a large design — the
    # case a fixed wall destroyed, booking a false exit-124 ERROR — now runs
    # to completion however long it legitimately takes, while a genuine
    # deadlock is still killed and reported as such under its OWN rc.
    res = _wd.run_host_supervised(docker_cmd, stall_grace_s=float(timeout),
                                  kill=_reap, cpu_probe=_cpu_probe)
    if res.outcome == "launch_error":
        return 127, "", "docker binary not found in PATH"
    # On a stall the partial stdout yosys emitted before the kill is still
    # SALVAGED (it is captured to a file, not lost with the exception), so the
    # COMPLETED-fault PREFIX can still be graded. `res.rc` is then the
    # watchdog's own distinct RC_STALLED, never the old wall-clock 124, so a
    # reader can tell "no forward progress for the whole grace window" from
    # "the runtime guess was too small".
    return res.rc, res.out, res.err


def _ensure_cut(project: Path, netlist_rel: str, cut_rel: str, clock: str,
                dff_cells: str | None, pdk_dir: Path | None,
                timeout: int,
                liberty_sequential: "set | None" = None) -> tuple[bool, str]:
    """Reuse phase2/stage2/dft/cut_netlist.v if present, else run `fault cut`.
    Returns (ok, message).

    `liberty_sequential` — the set of cells the design's OWN Liberty declares to
    have an `ff` group. Supplying it makes both the cut-validity check and the
    `--dff` list name-independent: whichever cells the netlist instantiates that
    the library calls sequential ARE the flops, however they happen to be
    spelled. Without it the caller falls back to name matching, which is a
    guess about the library's spelling conventions."""
    cut_abs = project / cut_rel
    if cut_abs.exists() and cut_abs.stat().st_size > 0:
        # Only reuse a REAL full-scan cut. TWO ways an existing file fails to be
        # one, and BOTH must force a regenerate — else a SEQUENTIAL design
        # silently scores 0 pseudo-PI/PO pairs, which the producer can only read
        # as a NOT_APPLICABLE / ENGINE_LIMITED self-skip the coverage gate cannot
        # distinguish from a real one (gaming):
        #   (a) it still instantiates flop cells — a prior run cut with the wrong
        #       --dff seed, so `fault cut` cut NOTHING (residual flops present);
        #   (b) it instantiates NO flops AND exposes 0 pseudo-PI/PO pairs while
        #       the SOURCE netlist DOES have flops — a DEGENERATE/empty cut (e.g.
        #       taken from the GENERIC pre-map netlist whose `$_DFF_*` primitives
        #       `fault cut` cannot detect, leaving the flops neither cut NOR
        #       present, or a cut written before the tech-mapped netlist existed).
        #       A real full-scan cut of a sequential design ALWAYS carries one
        #       `.d/.q` pair per flop.
        # A genuinely combinational source legitimately yields 0 pairs — reused.
        # chip/PDK-AGNOSTIC: the flop set comes from the design's own Liberty.
        _cut_text = cut_abs.read_text(errors="replace")
        _cut_has_flops = bool(_far.detect_dff_cells(_cut_text, liberty_sequential))
        try:
            _, _, _, _cut_pairs = parse_cut_ports(_cut_text)
        except Exception:
            _cut_pairs = []
        _src_seq = False
        if not _cut_has_flops and not _cut_pairs:
            try:
                _src_seq = bool(_far.detect_dff_cells(
                    (project / netlist_rel).read_text(errors="replace"),
                    liberty_sequential))
            except OSError:
                _src_seq = False
        if not _cut_has_flops and (_cut_pairs or not _src_seq):
            return True, (f"reused existing cut netlist: {cut_rel} "
                          f"({len(_cut_pairs)} scan pair(s))")
        if _cut_has_flops:
            print(f"{_PROGRAM}: existing {cut_rel} still has flop cells → not a "
                  f"real cut, regenerating", file=sys.stderr)
        else:
            print(f"{_PROGRAM}: existing {cut_rel} exposes 0 scan pairs on a "
                  f"sequential design → degenerate cut, regenerating from "
                  f"{netlist_rel}", file=sys.stderr)
    # Auto-detect the flop cells from the mapped netlist (union with any seed).
    try:
        ntext = (project / netlist_rel).read_text(errors="replace")
    except OSError as exc:
        return False, f"cannot read netlist {netlist_rel}: {exc}"
    detected = _far.detect_dff_cells(ntext, liberty_sequential)
    cells = _far.merge_dff_cells(dff_cells, detected) or (dff_cells or "DFFHQD1")
    cut_abs.parent.mkdir(parents=True, exist_ok=True)
    cmd = (f"fault cut --output /work/{cut_rel} --dff {cells} "
           f"--clock {clock} /work/{netlist_rel}")
    ec, out, err = _run_in_docker(project, cmd, timeout=timeout, pdk_dir=pdk_dir)
    if ec != 0 or not cut_abs.exists():
        return False, f"fault cut failed (exit {ec}): {(out + err)[-400:]}"
    return True, f"ran fault cut (--dff {cells})"


def _tdf_pre_flatten_script(liberty_ctr: str, cut_rel: str, top: str,
                            flat_rel: str) -> str:
    """Build the yosys pre-flatten script for the TDF miter core (pure/testable).

    v1.4.39 (ic2-sha256 sha256 DT1 floor): `proc; memory_collect; memory_map` run
    BEFORE `flatten`. A cut netlist bearing a K-ROM `$mem_v2` (e.g. sha256's
    round-constant ROM) still carries a `$proc`/`$mem_v2` cell, so a bare
    `flatten` aborts with "Found processes in selected module" and the TDF run
    ERRORs. `proc` lowers processes; `memory_collect; memory_map` map the memory
    to logic, so the miter core flattens to generic `$_*_` gates. Same recipe as
    the #155 LEC memory_map fix; a no-op on memory-less designs (the passes just
    find nothing to legalize). `flatten -separator _` keeps inlined pin nets as
    CLEAN ids so `sat -set`/`connect` can reference every fault site."""
    return (
        f"read_liberty -ignore_miss_func {liberty_ctr}\n"
        f"read_verilog /work/{cut_rel}\n"
        f"hierarchy -top {top}\n"
        "proc\n"
        "memory_collect\n"
        "memory_map\n"
        "flatten -separator _\n"
        "opt_clean\n"
        f"write_verilog -noattr /work/{flat_rel}\n"
    )


def _gate_levelise(project: Path, cut_rel: str, liberty_ctr: str,
                   top: str, flat_rel: str, pdk_dir: Path | None,
                   timeout: int,
                   extra_mounts: list[tuple[str, str]] | None = None
                   ) -> tuple[bool, str]:
    """Read the liberty AS LOGIC + the cut netlist, flatten to generic `$_*_`
    gates, opt_clean, write flat_core.v. PDK-agnostic (no proprietary Verilog
    sim model). Returns (ok, message)."""
    (project / flat_rel).parent.mkdir(parents=True, exist_ok=True)
    # `flatten -separator _` : concatenate hierarchy levels with '_' instead of
    # the default '.', so inlined cell-pin nets are CLEAN ids (`_196__Y`, not
    # `_196_.Y`). Dotted names cannot be referenced by yosys `sat -set` /
    # `connect` / `rename` (the '.' is the hierarchy separator), which would
    # abort the whole batch mid-run. This keeps every fault site referenceable
    # across yosys builds that name flattened cell nets `<inst>.<pin>`.
    script = _tdf_pre_flatten_script(liberty_ctr, cut_rel, top, flat_rel)
    script_rel = str(Path(flat_rel).parent / "_tdf_pre.ys")
    (project / script_rel).write_text(script)
    ec, out, err = _run_in_docker(
        project, f"yosys /work/{script_rel}", timeout=timeout, pdk_dir=pdk_dir,
        extra_mounts=extra_mounts)
    if ec != 0 or not (project / flat_rel).exists():
        return False, f"gate-levelise failed (exit {ec}): {(out + err)[-400:]}"
    return True, "gate-levelised via read_liberty -ignore_miss_func + flatten"


def _resolve_liberty_mount(project: Path, liberty: str):
    """Resolve --liberty to (container_path, extra_mount). A container-absolute
    path (/pdk, /foss, …) is used as-is with no extra mount (relies on
    pdk_dir). A project-relative path is realpath'd: if it stays inside the
    project it maps under /work; if it resolves (via a symlink) OUTSIDE the
    project — common when input/pdk is a symlink to a shared PDK — its real
    directory is bind-mounted at /libmnt so a fresh container can read it."""
    if liberty.startswith("/"):
        return liberty, None
    host = (project / liberty)
    try:
        real = host.resolve()
    except Exception:
        real = host
    try:
        rel = real.relative_to(project.resolve())
        return "/work/" + str(rel), None
    except ValueError:
        # resolves outside the project (symlinked PDK) — bind-mount its dir
        return "/libmnt/" + real.name, (str(real.parent), "/libmnt")


def _liberty_structure_text(project: Path, liberty: str,
                            pdk_dir: Path | None,
                            timeout: int = 120) -> tuple[str, str]:
    """Read the resolved std-cell Liberty far enough to enumerate which cells
    declare an `ff` group. Returns (text, source) — `text` may be "" when the
    Liberty could not be reached, which is a first-class outcome the caller
    must NOT round down to "no flops" (see `_far.sequential_evidence`).

    Two reads, because the flow's Liberty lives on either side of the container
    boundary: a project-relative or host-visible path is read directly; a
    container-baked path (the mainstream case — the Liberty synth/STA/LEC
    already use is inside the tool image, not in the run dir) is reduced to its
    group structure INSIDE the container and only that is brought back. Never
    reaches into another PDK's data, and never invents cells: an unreachable
    Liberty yields "", and the caller says so.

    chip- and PDK-AGNOSTIC — nothing here knows a library's name."""
    host_cands = []
    if liberty.startswith("/"):
        host_cands.append(Path(liberty))
    else:
        host_cands.append(project / liberty)
    for cand in host_cands:
        try:
            if cand.is_file():
                return cand.read_text(errors="replace"), f"host read {cand}"
        except OSError:
            pass
    # Container read: reduce to group structure so a 20 MB Liberty crosses the
    # boundary as kilobytes.
    liberty_ctr, mount = _resolve_liberty_mount(project, liberty)
    try:
        ec, out, err = _run_in_docker(
            project, f"{_far.LIBERTY_STRUCTURE_GREP} {liberty_ctr} || true",
            timeout=timeout, pdk_dir=pdk_dir,
            extra_mounts=([mount] if mount else None))
    except Exception as exc:  # pragma: no cover - defensive
        return "", f"container read failed: {exc}"
    if ec == 0 and out.strip():
        return out, f"container structure read {liberty_ctr}"
    return "", (f"unreachable (host miss; container exit {ec}): "
                f"{(err or '')[-160:]}")


def _resolve_design_liberty(project: Path, explicit: "str | None") -> str:
    """Chip/PDK-AGNOSTIC std-cell Liberty resolution for the at-speed ATPG
    producers (TDF/PDF). The gate-levelise step needs ANY std-cell Liberty read
    AS LOGIC; the prior code globbed ONLY `input/pdk/liberty/*typ*.lib` and, when
    that project-relative tree was absent (the mainstream sky130 flow, whose
    Liberty is container-baked and recorded per-project, not shipped in-tree),
    fell through to a NON-EXISTENT `input/pdk/liberty/typ.lib` — so gate-levelise
    read a missing file and the producer errored (a false FAIL, not a real
    coverage miss). Resolution order:
      1. explicit --liberty (caller override, e.g. commercial PDK);
      2. the project's OWN PDK glob input/pdk/liberty/*typ*.lib (kept FIRST so a
         shipped Liberty always wins);
      3. the Liberty the FLOW ITSELF used, recorded per-project in
         phase2/stage2/constraints/pvt_matrix.json (its primary corner) — a
         gf180 project records its gf180 path there, sky130 records sky130, so
         this stays PDK-agnostic;
      4. the shared OSS container default (lec_run.DEFAULT_LIBERTY) that
         synth/PnR/STA/LEC already use flow-wide — a single source of truth.
    Returns a path string (container-absolute /foss… used as-is, or a project-
    relative path); `_resolve_liberty_mount` handles either. No chip literal."""
    if explicit:
        return explicit
    hits = sorted(project.glob("input/pdk/liberty/*typ*.lib"))
    if hits:
        return str(hits[0].relative_to(project))
    pvt = project / "phase2" / "stage2" / "constraints" / "pvt_matrix.json"
    if pvt.is_file():
        try:
            d = json.loads(pvt.read_text(errors="ignore"))
            corners = d.get("corners") or []
            primary = str(d.get("primary_corner") or "").strip().lower()

            def _lib_of(c):
                return c.get("liberty") if isinstance(c, dict) else None
            # primary corner by label (e.g. "TT"), else a tt/typ corner, else any
            pick = next((c for c in corners if _lib_of(c)
                         and str(c.get("label", "")).strip().lower() == primary),
                        None)
            if pick is None:
                pick = next((c for c in corners if _lib_of(c)
                             and ("tt" in Path(_lib_of(c)).name.lower()
                                  or "typ" in Path(_lib_of(c)).name.lower())),
                            None)
            if pick is None:
                pick = next((c for c in corners if _lib_of(c)), None)
            if pick and _lib_of(pick):
                return str(_lib_of(pick))
        except (ValueError, OSError):
            pass
    try:
        import lec_run  # type: ignore
    except Exception:  # pragma: no cover - path fallback
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import lec_run  # type: ignore
    return lec_run.DEFAULT_LIBERTY


def _detect_sat_solver(project: Path, pdk_dir: Path | None,
                       timeout: int = 90) -> str:
    """Probe the EDA image ONCE for a modern external CDCL `sat` backend
    (kissat/cadical) and return the name to pass to `sat -select-solver`, or ""
    to use the built-in ezMiniSAT.

    SELF-VALIDATING: for each candidate it runs a trivial KNOWN-SAT prove through
    the WHOLE chain — `assign y = a; sat -prove y 0 -select-solver <name> -set a
    1` must find a model (y=1≠0). It selects a solver ONLY when that prove
    returns `model found: FAIL!`, which is true iff (a) the fork registers the
    solver, (b) its binary is on PATH, and (c) the backend returns the correct
    verdict end-to-end. A stale image (solver unknown → `Unknown SAT solver`), a
    missing binary, or a backend regression therefore ALL fall back to the
    built-in engine with NO change in grading — so wiring the external solver can
    never itself turn a real detection into an abort. Result is cached per image.
    chip/PDK/vendor-AGNOSTIC — no design/library knowledge. Env override
    VIBEIC_ATPG_SAT_SOLVER: auto (default) | kissat | cadical | minisat | none."""
    pref = (os.environ.get("VIBEIC_ATPG_SAT_SOLVER") or "auto").strip().lower()
    if pref in ("none", "minisat", "builtin", "off"):
        return ""
    if pref in ("auto", ""):
        candidates = list(_ATPG_SAT_SOLVER_PREFERENCE)
    else:
        candidates = [pref]
    key = (_far.DOCKER_IMAGE, tuple(candidates))
    if key in _SAT_SOLVER_PROBE_CACHE:
        return _SAT_SOLVER_PROBE_CACHE[key]
    chosen = ""
    for name in candidates:
        probe = (
            "printf 'module p(input a, output y); assign y = a; endmodule\\n' "
            "> /tmp/_vibeic_satprobe.v 2>/dev/null; "
            "yosys -p 'read_verilog /tmp/_vibeic_satprobe.v; prep -top p; "
            f"sat -prove y 0 -select-solver {name} -set a 1' 2>&1"
        )
        try:
            _ec, out, err = _run_in_docker(project, probe,
                                           timeout=min(int(timeout), 120),
                                           pdk_dir=pdk_dir)
        except Exception:
            continue
        blob = (out or "") + "\n" + (err or "")
        if "Unknown SAT solver" in blob:
            continue                       # stale image: backend not registered
        if "model found: FAIL" in blob:    # known-SAT prove detected end-to-end
            chosen = name
            break
    _SAT_SOLVER_PROBE_CACHE[key] = chosen
    return chosen


def _build_batch_script(flat_rel: str, miter_rel: str, top: str,
                        faults: list, prim_in_names: list[str],
                        sat_timeout: int = DEFAULT_PER_FAULT_SAT_TIMEOUT,
                        select_solver: str = "") -> str:
    """One Yosys script that solves every fault in the sample in a single
    process. #154 FLATTEN-ONCE: the faulty core copy is created and the 3×-core
    2-frame miter is resolved + flattened EXACTLY ONCE, then snapshotted with
    `design -save`. Each fault reloads that flat snapshot and injects the
    launch-frame stuck-at directly on the ALREADY-flattened faulty-instance net
    `fb.<net>` (the `fb` frame-2 faulty instance of the core), then runs
    `sat -prove trig 0 -timeout <T> -set f1.<net> <init>` with the primary
    inputs -show'd so the detecting 2-pattern can be recovered.

    Why this is equivalent to (and much cheaper than) the old per-fault recipe:
    the OLD script reloaded an UN-flattened base, `copy`-d the core, injected
    into the copy, then RE-RAN `hierarchy`+`flatten` on the whole miter FOR
    EVERY FAULT — and that per-fault re-flatten forced a fresh ~461 k-var CNF
    build + SAT solve each time (measured ~25 s/fault → a 400-fault batch is
    killed by the wall before any verdict → 0 %). Injecting on the flat net via
    `connect -nomap -set fb.<net>` reaches the identical physical wire the old
    in-module `connect -nomap -set <net>` reached after flatten (f1/g2/fb are
    the same core flattened the same way, so `fb.<net>` mirrors the `f1.<net>`
    the sat `-set` already addresses); an A/B parity run confirmed byte-identical
    per-fault verdicts. `-nomap` is REQUIRED so the forced net is not silently
    remapped to its driver alias (else the fault is NOT injected → spurious
    detections). The per-fault `sat -timeout <T>` caps one pathological deep-cone
    fault (undecided → conservative ABORT, never a false detection). A one-time
    `VIBEICTDF_SETUP_DONE` marker + a per-fault `VIBEICTDF <net> <kind>` marker
    let the parser tell a fault that was NEVER REACHED (batch killed by the wall
    budget before its block) from one that was attempted-but-undecided."""
    show = " ".join(f"-show {n}" for n in prim_in_names)
    # #ATPG-SAT: route the per-fault prove at a modern external CDCL solver
    # (kissat/cadical) wired into the fork's `sat` command when the image
    # supports it. The built-in ezMiniSAT (MiniSAT-2.2) times out (ABORT) on the
    # ~5.5e5-var 2-frame LOC miter that kissat decides in seconds; those aborts
    # were counted UNDETECTED and collapsed coverage. `-select-solver` is EMPTY
    # → built-in engine (unchanged behaviour) when the probe found no external
    # backend, so this is a no-op fallback on an image without the backend.
    sel = f"-select-solver {select_solver} " if select_solver else ""
    L = [
        f"read_verilog /work/{flat_rel} /work/{miter_rel}",
        # Build + flatten the faulty miter ONCE, then snapshot.
        f"copy {top} {top}_f",
        "hierarchy -top miter",
        "flatten",
        "design -save baseflat",
        f"log {_SETUP_MARKER}",
    ]
    for net, kind, stuck, init in faults:
        raw = net.lstrip('\\')
        L += [
            "design -load baseflat",
            # SOUND stuck-at injection on the flat faulty-instance net (see
            # docstring): `-nomap -set` forces `fb.<net>` to the launch-frame
            # value the transition launches FROM.
            f"connect -nomap -set fb.{net} {stuck}",
            f"log VIBEICTDF {raw} {kind}",
            f"sat -prove trig 0 -timeout {int(sat_timeout)} "
            f"{sel}-set f1.{net} {init} {show}".rstrip(),
        ]
    return "\n".join(L) + "\n"


_TIME_SAT_RE = re.compile(r"(\d+)x\s+sat\s+\((\d+)\s+sec\)")
_TIME_FLATTEN_RE = re.compile(r"(\d+)x\s+flatten\s+\((\d+)\s+sec\)")


def _parse_time_spent(log: str) -> "tuple[int, int, int]":
    """Parse Yosys' final `Time spent: … Nx sat (S sec), … Mx flatten (F sec)`
    line. Returns (sat_calls, sat_sec, flatten_sec); any field absent → 0. Used
    by the calibration probe to size the real fault sample against the wall
    budget from THIS design's measured per-fault SAT seconds. Pure."""
    sat_calls = sat_sec = flatten_sec = 0
    m = _TIME_SAT_RE.search(log or "")
    if m:
        sat_calls, sat_sec = int(m.group(1)), int(m.group(2))
    m = _TIME_FLATTEN_RE.search(log or "")
    if m:
        flatten_sec = int(m.group(2))
    return sat_calls, sat_sec, flatten_sec


def _scaled_wall_budget(floor_wall: int, scan_flops: int) -> int:
    """The at-speed ATPG wall budget for THIS design: the caller's floor plus a
    per-scan-flop term, capped at WALL_BUDGET_MAX. A design with no/few flops
    keeps the floor unchanged; a large design earns proportionally more wall so
    its disclosed sample is not starved and its one-time flatten is never killed
    by a fixed ceiling. Chip-AGNOSTIC — keyed ONLY on the flop count the cut
    exposed. Monotonic non-decreasing in scan_flops. Pure."""
    if scan_flops <= 0:
        return int(floor_wall)
    want = floor_wall + WALL_PER_SCAN_FLOP * scan_flops
    return int(min(WALL_BUDGET_MAX, max(floor_wall, want)))


def _scaled_setup_allowance(scan_flops: int) -> int:
    """One-time flatten (setup) time allowance for the calibration probe, scaled
    with flop count so a large 2-frame miter's flatten is not killed before it
    emits the setup marker (the yosys-exit-124 / setup_done=False false-ERROR
    that a fixed 60 s allowance produced under host contention). Chip-AGNOSTIC —
    keyed ONLY on flop count. Pure."""
    return int(SETUP_ALLOWANCE_FLOOR
               + SETUP_ALLOWANCE_PER_SCAN_FLOP * max(0, scan_flops))


def _rightsize_sample(per_fault_sec: float, setup_sec: float,
                      wall_budget: float, hard_cap: int,
                      total_available: int) -> int:
    """How many faults fully grade within `wall_budget` given the measured
    per-fault SAT seconds and one-time setup (flatten) seconds. Deterministic,
    unit-tested. Returns at least 1 (an honest tiny partial beats 0) and never
    more than the disclosed `hard_cap` (--max-faults) or what exists. Pure."""
    if per_fault_sec <= 0:
        return min(hard_cap, total_available)
    usable = wall_budget * _BUDGET_SAFETY - setup_sec
    affordable = int(usable // per_fault_sec) if usable > 0 else 0
    return max(1, min(hard_cap, total_available, affordable))


def _spread_order(items: list) -> list:
    """Reorder a list so ANY prefix samples the whole list quasi-uniformly
    (bit-reversal permutation). #154: if the wall budget still truncates the
    batch, the graded prefix then covers the WHOLE design rather than a
    low-net-id cluster — keeping a budget-truncated partial representative.
    Deterministic + pure; a list of <3 is returned unchanged."""
    n = len(items)
    if n < 3:
        return list(items)
    bits = max(1, (n - 1).bit_length())
    order, seen = [], set()
    for i in range(1 << bits):
        r = int(f"{i:0{bits}b}"[::-1], 2)
        if r < n and r not in seen:
            seen.add(r)
            order.append(items[r])
    return order


def _parse_batch_log(log: str, faults: list, prim_in_names: list[str]):
    """Map each `VIBEICTDF <net> <kind>` marker to the sat verdict block that
    follows it. Returns (results, example_pattern, setup_done) where each result
    verdict is one of:
      * 'DET'       marker + `model found: FAIL!`      (detecting 2-pattern)
      * 'RED'       marker + `no model found: SUCCESS!` (redundant/undetectable)
      * 'ABORT'     marker present but no sat verdict — the fault WAS attempted
                    but left undecided (per-fault `sat -timeout` hit, solver
                    interrupted, or the batch was killed WHILE solving it).
                    Conservatively undetected — never a false detection.
      * 'UNREACHED' NO marker at all — the batch never got to this fault (e.g.
                    the wall budget killed yosys first, #154). The caller
                    EXCLUDES these from the graded sample (an honest, disclosed
                    budget-truncation) rather than counting them undetected — so
                    a design's real coverage over the graded faults is not
                    depressed by faults the tool simply ran out of time to try.
    `setup_done` is True iff the one-time flatten/setup marker was emitted (the
    miter flattened and at least the first fault block began). Pure."""
    setup_done = _SETUP_MARKER in (log or "")
    marker = re.compile(r'VIBEICTDF (\S+) (\S+)')
    hits = list(marker.finditer(log))
    results = {}
    example = None
    for i, m in enumerate(hits):
        net, kind = m.group(1), m.group(2)
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(log)
        body = log[start:end]
        v = parse_sat_verdict(body)
        results[(net, kind)] = v
        if v == "DET" and example is None:
            pat = _extract_pattern(body, prim_in_names)
            if pat:
                example = {"fault_net": net, "fault_kind": kind,
                           "primary_input_pattern": pat}
    out = []
    for net, kind, stuck, init in faults:
        raw = net.lstrip('\\')
        out.append((raw, kind, results.get((raw, kind), "UNREACHED")))
    return out, example, setup_done


# ══════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════

def _to_container_path(project: Path, p: str) -> str:
    """A container-absolute path (/pdk, /foss, /work) is used as-is; a
    project-relative path is mapped under the /work mount."""
    if p.startswith("/"):
        return p
    return "/work/" + p.lstrip("./")


def run_tdf_atpg(project: Path, netlist_rel: str, cut_rel: str, liberty: str,
                 top: str, clock: str, dff_cells: str | None,
                 floor: float, max_faults: int, pdk_dir: Path | None,
                 timeout: int = 1800,
                 sat_timeout: int = DEFAULT_PER_FAULT_SAT_TIMEOUT
                 ) -> tuple[int, dict]:
    """Full producer. Returns (exit_code, report_dict)."""
    dft_dir = (_pl.dft_dir(project) if _pl is not None
               else project / "phase2/stage2/dft")
    tdf_dir = dft_dir / "tdf"
    tdf_dir.mkdir(parents=True, exist_ok=True)
    flat_rel = "phase2/stage2/dft/tdf/flat_core.v"
    miter_rel = "phase2/stage2/dft/tdf/loc_miter.v"

    base = {
        "program": _PROGRAM, "version": _VERSION, "tool": "vibeic/yosys sat",
        "fault_model": "transition (LOC 2-frame stuck-at reduction)",
        "clock": clock, "top": top, "netlist": netlist_rel,
        "floor_pct": floor, "disclosure": _DISCLOSURE,
    }

    # 0. AUTHORITATIVE FLOP IDENTIFICATION. Ask the design's own Liberty which
    # cells declare an `ff` group, BEFORE cutting — so `fault cut --dff` is
    # given the flops the library says exist rather than the ones a name pattern
    # guesses at, and so the self-skip decision below has real evidence behind
    # it. An unreachable Liberty is recorded as such, never silently treated as
    # "this library declares no flops".
    lib_text, lib_source = _liberty_structure_text(project, liberty, pdk_dir,
                                                   timeout=min(timeout, 120))
    lib_seq = _far.liberty_sequential_cells(lib_text) if lib_text else set()
    base["liberty_source"] = lib_source
    base["liberty_sequential_cells_declared"] = len(lib_seq)

    # 1. CUT
    ok, msg = _ensure_cut(project, netlist_rel, cut_rel, clock, dff_cells,
                          pdk_dir, timeout=min(timeout, 300),
                          liberty_sequential=lib_seq)
    base["cut"] = msg
    if not ok:
        base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
        return 1, base

    # 2. GATE-LEVELISE
    liberty_ctr, lib_mount = _resolve_liberty_mount(project, liberty)
    extra_mounts = [lib_mount] if lib_mount else None
    base["liberty_container_path"] = liberty_ctr
    ok, msg = _gate_levelise(project, cut_rel, liberty_ctr, top, flat_rel,
                             pdk_dir, timeout=min(timeout, 300),
                             extra_mounts=extra_mounts)
    base["gate_levelise"] = msg
    if not ok:
        base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
        return 1, base

    flat_text = (project / flat_rel).read_text(errors="replace")
    _top, prim_in, prim_out, pairs = parse_cut_ports(flat_text)
    prim_in_names = [n.lstrip('\\') for n, _ in prim_in]

    # ZERO SCAN FLOPS — the three-way decision. `scan_flops: 0` is only ONE of
    # these three things, and which one it is decides whether the step may
    # self-skip. Collapsing them (as a single boolean "does the name pattern
    # match anything?" did) is what let a scan-insertion result of zero flops on
    # a design with 65 of them be reported as a clean NOT_APPLICABLE.
    #
    #   HAS_SEQUENTIAL → the cut did NOT run (wrong --dff list / stale bogus
    #     cut). A scan-insertion step that inserted nothing into a sequential
    #     design is a FAILURE, never a skip. ERROR.
    #   NO_SEQUENTIAL  → genuinely combinational, established from the design's
    #     own Liberty. There are no launch-off-capture transition faults to
    #     find. Honest NOT_APPLICABLE.
    #   UNKNOWN        → the Liberty could not be reached, so "this design has
    #     no flops" was never actually checked. BLOCKED: we could not verify,
    #     and that is now sayable instead of being rounded down to a self-skip.
    try:
        src_text = (project / netlist_rel).read_text(errors="replace")
    except OSError:
        src_text = ""
    evidence = _far.sequential_evidence(src_text, lib_text or None)
    base["sequential_evidence"] = evidence

    if not pairs:
        # ENGINE-LIMITED (generic/unmapped netlist) — distinguished from a real
        # scan-insertion ERROR. The OSS `fault` engine parses the netlist with
        # pyverilog, which cannot recognise a GENERIC yosys netlist's flops
        # (`$_DFF_*` primitives have no module body) — `fault cut` then emits
        # "Failed to detect any flip-flop cells" and cuts nothing → 0 pairs, even
        # with the correct --dff/--clock. This is the SAME OSS capability gap the
        # sibling stuck-at ATPG already discloses (design_one_shot_runner Step 11:
        # "a library-MAPPED netlist with real stdcell DFFs is required ... Fault
        # is not turnkey on the sky130 generic/UDP DFF forms" → cap:atpg_signoff_
        # coverage). At-speed TDF has the identical limit. On a MAPPED netlist
        # (real sky130/gf180/commercial stdcell DFFs) 0 pairs stays a hard ERROR.
        # Detection is structural + chip-AGNOSTIC: generic yosys seq cell present
        # AND no library sequential cell present.
        _nl = src_text or ""
        _has_generic_seq = ("$_DFF_" in _nl or "$_SDFF_" in _nl
                            or "$_DFFE_" in _nl or "$_DLATCH_" in _nl)
        _has_lib_seq = bool(re.search(
            r"sky130_fd_sc_\w+__[se]?d[fr]|gf180mcu_\w+__dff|\b[A-Z]{1,6}S?DFF[A-Z0-9]*\b",
            _nl))
        if _has_generic_seq and not _has_lib_seq:
            base.update({
                "verdict": "ENGINE_LIMITED", "status": "ENGINE_LIMITED",
                "scan_flops": 0,
                "engine_limited": True,
                "capability_flag": "cap:at_speed_timing_graded_atpg",
                "pdk_detected": "generic_unmapped",
                "reasons": ["at-speed TDF ATPG is ENGINE-LIMITED on this netlist: "
                            "it is a GENERIC (unmapped) yosys netlist whose flops "
                            "are `$_DFF_*` primitives, which the OSS `fault` engine "
                            "cannot detect (fault cut: 'Failed to detect any "
                            "flip-flop cells') → 0 pseudo-PI/PO pairs. A library-"
                            "MAPPED netlist (real stdcell DFFs) is required; the "
                            "SAME disclosed OSS capability gap the stuck-at ATPG "
                            "records (cap:atpg_signoff_coverage). The design HAS "
                            "sequential cells ("
                            + "; ".join(evidence["reasons"])
                            + ") — coverage is UNMEASURED (never claimed); a "
                            "mapped-netlist or commercial ATPG path closes it"],
            })
            return 0, base
        if evidence["verdict"] == _far.SEQ_PRESENT:
            base.update({
                "verdict": "ERROR", "status": "ERROR", "scan_flops": 0,
                "reasons": ["scan cut exposed 0 pseudo-PI/PO pairs on a design "
                            "that HAS sequential cells ("
                            + "; ".join(evidence["reasons"]) + ") — the cut did "
                            "not run correctly (NOT a combinational design); "
                            "refusing a false NOT_APPLICABLE"],
            })
            return 1, base
        if evidence["verdict"] == _far.SEQ_ABSENT:
            base.update({
                "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                "scan_flops": 0,
                "reasons": ["no sequential (scan-cut) flops found in the core — a "
                            "combinational design has no launch-off-capture "
                            "transition faults; TDF ATPG not applicable ("
                            + "; ".join(evidence["reasons"]) + ")"],
            })
            return 0, base
        base.update({
            "verdict": "BLOCKED", "status": "BLOCKED", "scan_flops": 0,
            "reasons": ["scan cut exposed 0 pseudo-PI/PO pairs and it could NOT "
                        "be established whether the design has sequential "
                        "elements ("
                        + "; ".join(evidence["reasons"])
                        + f"; liberty: {lib_source}) — refusing both a coverage "
                        "number and a NOT_APPLICABLE self-skip on unverified "
                        "grounds"],
        })
        return 1, base

    # 3. ENUMERATE
    nets = enumerate_fault_sites(flat_text)
    all_faults = enumerate_tdf_faults(nets)
    scan_flops = len(pairs)
    # SIZE-SCALED WALL: the caller's --timeout is the FLOOR; the effective wall
    # (and, below, the calibration setup-allowance) scales with THIS design's
    # own flop count so a large design's sample is not starved and its one-time
    # flatten is never killed by a fixed ceiling. See _scaled_wall_budget.
    wall = _scaled_wall_budget(timeout, scan_flops)
    base.update({
        "scan_flops": scan_flops,
        "fault_sites_total": len(nets),
        "tdf_faults_total": len(all_faults),
        "wall_budget_floor_sec": timeout,
        "wall_budget_sec": wall,
    })

    # Build the 2-frame LOC miter ONCE (reused by the calibration probe and the
    # real run). The batch itself does the flatten-once (see _build_batch_script).
    miter_text = build_loc_miter(_top, prim_in, prim_out, pairs)
    (project / miter_rel).write_text(miter_text)

    # Select a modern external CDCL `sat` backend (kissat/cadical) if the fork
    # image provides one — this is the fix for the MiniSAT-timeout aborts that
    # collapsed at-speed coverage. Self-validating + fail-safe to the built-in
    # engine (see _detect_sat_solver). Probed ONCE, reused by both batches.
    select_solver = _detect_sat_solver(project, pdk_dir, timeout=min(timeout, 120))
    base["sat_solver"] = select_solver or "minisat (built-in ezSAT)"

    def _run_batch(sample, wall, tag):
        batch = _build_batch_script(flat_rel, miter_rel, _top, sample,
                                    prim_in_names, sat_timeout=sat_timeout,
                                    select_solver=select_solver)
        batch_rel = f"phase2/stage2/dft/tdf/_tdf_{tag}.ys"
        (project / batch_rel).write_text(batch)
        t0 = time.time()
        ec, out, err = _run_in_docker(project, f"yosys /work/{batch_rel}",
                                      timeout=max(30, int(wall)), pdk_dir=pdk_dir)
        return ec, (out + "\n" + err), time.time() - t0

    # 3a. CALIBRATION (#154 lever c) — measure THIS design's per-fault SAT
    # seconds on a tiny strided probe so the real sample is sized to COMPLETE
    # within the wall budget (a smaller, fully-graded, design-spread sample beats
    # a max-faults batch that all-ABORTs → 0 %). Bounded so it cannot itself eat
    # the whole budget.
    cal_n = min(_CALIBRATION_FAULTS, len(all_faults))
    cal_faults, _ = sample_faults(all_faults, cal_n)
    # The calibration probe must survive the one-time flatten of THIS design's
    # miter (which grows with flop count) plus its `cal_n` SAT solves; the
    # setup-allowance therefore scales with scan_flops instead of a fixed 60 s.
    # Bounded by half the scaled wall so calibration can never eat the budget.
    cal_wall = min(wall // 2,
                   _scaled_setup_allowance(scan_flops) + cal_n * sat_timeout)
    cal_ec, cal_log, cal_elapsed = _run_batch(cal_faults, cal_wall, "cal")
    (tdf_dir / "cal_run.log").write_text(cal_log[-100000:])
    sat_calls, sat_sec, flatten_sec = _parse_time_spent(cal_log)
    cal_results, _, cal_setup_done = _parse_batch_log(cal_log, cal_faults,
                                                      prim_in_names)
    cal_graded = sum(1 for _, _, v in cal_results if v in ("DET", "RED", "ABORT"))
    # per-fault SAT seconds: prefer Yosys' own timing breakdown; else derive from
    # the measured wall over however many faults actually graded (conservative).
    if sat_calls > 0 and sat_sec > 0:
        per_fault_sec = sat_sec / sat_calls
        setup_sec = float(flatten_sec)
    elif cal_graded > 0:
        per_fault_sec = max(1.0, (cal_elapsed - flatten_sec) / cal_graded)
        setup_sec = float(flatten_sec)
    else:
        # the probe could not grade even one fault in its slice → the design is
        # extremely heavy; fall back to a conservative sat_timeout-based estimate.
        per_fault_sec = float(sat_timeout)
        setup_sec = float(flatten_sec or 30)

    if not cal_setup_done and cal_graded == 0:
        base.update({"verdict": "ERROR", "status": "ERROR",
                     "reasons": [f"ATPG calibration produced no setup marker or "
                                 f"verdict (yosys exit {cal_ec}) within the "
                                 f"{cal_wall}s size-scaled calibration wall "
                                 f"(setup-allowance {_scaled_setup_allowance(scan_flops)}s "
                                 f"for {scan_flops} flops); cannot measure TDF "
                                 f"coverage", (cal_log[-400:] or "").strip()]})
        return 1, base

    # 3b. RIGHT-SIZE + SPREAD the real sample against the remaining budget.
    remaining = wall - cal_elapsed
    n_target = _rightsize_sample(per_fault_sec, setup_sec, remaining,
                                 max_faults, len(all_faults))
    faults, _ = sample_faults(all_faults, n_target)
    # A bit-reversal spread so that IF the wall still truncates the batch, the
    # graded prefix samples the WHOLE design, not a low-net-id cluster.
    faults = _spread_order(faults)
    budget_bounded = n_target < min(max_faults, len(all_faults))
    base["calibration"] = {
        "probe_faults": cal_n,
        "per_fault_sat_sec": round(per_fault_sec, 2),
        "setup_sec": round(setup_sec, 2),
        "wall_budget_sec": wall,
        "wall_budget_floor_sec": timeout,
        "cal_wall_sec": cal_wall,
        "setup_allowance_sec": _scaled_setup_allowance(scan_flops),
        "per_fault_sat_timeout_sec": sat_timeout,
        "sized_to_budget": budget_bounded,
        "n_target": n_target,
    }

    # 4. SOLVE the right-sized sample within the remaining wall budget.
    real_ec, log, real_elapsed = _run_batch(faults, remaining, "batch")
    (tdf_dir / "sat_run.log").write_text(log[-200000:])
    results, example, setup_done = _parse_batch_log(log, faults, prim_in_names)

    # #154 completed-prefix: a fault the batch NEVER REACHED (wall killed yosys
    # first) is EXCLUDED from the graded sample AND disclosed — never counted as
    # undetected (counting un-reached faults undetected is exactly what scored a
    # too-large batch 0 %). Genuine per-fault aborts (marker present, undecided)
    # STILL count as undetected — anti-gaming intact.
    graded = [(n, k, v) for n, k, v in results if v != "UNREACHED"]
    unreached = len(results) - len(graded)
    det = sum(1 for _, _, v in graded if v == "DET")
    red = sum(1 for _, _, v in graded if v == "RED")
    abort = sum(1 for _, _, v in graded if v == "ABORT")

    if det + red + abort == 0:
        base.update({"verdict": "ERROR", "status": "ERROR",
                     "reasons": [f"ATPG produced no gradeable verdicts (yosys "
                                 f"exit {real_ec}, setup_done={setup_done})",
                                 (log[-400:] or "").strip()]})
        return 1, base

    # 5. GRADE over the faults that were actually attempted (completed prefix).
    cov = coverage_math(det, red, abort)
    base.update(cov)
    base["tdf_faults_sampled"] = cov["sampled_faults"]     # = graded count
    base["tdf_faults_graded"] = cov["sampled_faults"]
    base["budget_truncated_faults"] = unreached
    base["fault_sample_applied"] = (cov["sampled_faults"] < len(all_faults))
    test_cov = cov["tdf_test_coverage_pct"]
    ge_floor = (test_cov is not None and test_cov >= floor)
    reasons = []
    if not ge_floor:
        reasons.append(
            f"TDF logic test-coverage {test_cov}% < floor {floor}% "
            f"(detected {det}/(graded {cov['sampled_faults']} - redundant "
            f"{red}) = {cov['testable_faults']} testable; aborted {abort} "
            "counted as undetected)")
    if unreached:
        reasons.append(
            f"DISCLOSED budget-truncation: {unreached} of {len(faults)} sampled "
            f"faults were not reached within the {wall}s size-scaled wall budget "
            f"(floor {timeout}s + {WALL_PER_SCAN_FLOP:g}s/scan-flop, {scan_flops} "
            f"flops) and are EXCLUDED from the graded sample (NOT counted "
            f"undetected); coverage is over the {cov['sampled_faults']} graded "
            f"faults. Raise --timeout or lower --max-faults for a fuller sample.")
    base.update({
        "ge_floor": ge_floor,
        "launch_capture_pattern_count": det,   # each detection IS a 2-pattern
        "example_two_pattern": example,
        "fault_list": [{"net": n, "kind": k, "verdict": v} for n, k, v in graded],
        "sat_log": "phase2/stage2/dft/tdf/sat_run.log",
        "verdict": "PASS" if ge_floor else "FAIL",
        "status": "PASS" if ge_floor else "FAIL",
        "reasons": reasons,
    })
    return (0 if ge_floor else 1), base


# The mapped-netlist emit name is NOT uniform across the flow: the DFT/synth
# chain writes `<top>_synth.v` in some paths, but the canonical Phase-2 synth
# step (design_one_shot_runner) emits `phase2/stage2/synth/netlist.v` (+
# `netlist_yosys.v`) — the SAME file the LEC gold read and the SHA-attestation
# reference. Discovering ONLY `*_synth.v`/`synth.v` MISSES that canonical
# netlist, so on a run whose synth produced `netlist.v` the producer cannot
# find an existing mapped netlist, writes a not-run sentinel ("cannot derive
# --top"), and the DT1 gate books it BLOCKED → FAIL — a false FAIL on a netlist
# that is right there (measured on opentitan_aes × sky130A). Ordered so the
# DFT-chain `<top>_synth.v` still wins when present. chip/tool-AGNOSTIC.
_MAPPED_NETLIST_GLOBS = (
    "phase2/stage2/synth/*_synth.v",        # phase2/phase3 tech-mapped synth
    "phase3/stage3/pnr/*_pnr_repaired.v",   # post-route, real stdcells
    "phase3/stage3/pnr/*_pnr.v",            # post-place, real stdcells
    "phase2/stage2/synth/netlist.v",        # MAY be generic — last-resort only
    "phase2/stage2/synth/netlist_yosys.v",
)
_MAPPED_NETLIST_FALLBACK = "phase2/stage2/synth/synth.v"

# A yosys GENERIC (un-tech-mapped) netlist keeps its flops as `$_DFF_*`
# primitives, which the OSS `fault` engine (pyverilog) cannot detect — `fault
# cut` then cuts NOTHING → 0 pseudo-PI/PO pairs, and the at-speed engine cannot
# grade. Such a netlist is NOT a valid ATPG input; a tech-mapped netlist (real
# stdcell DFFs) is. chip/PDK-AGNOSTIC — keyed on yosys's own generic cell
# vocabulary, never a library name.
_GENERIC_SEQ_PRIM_RE = re.compile(r"\$_(?:S?DFFE?|DFFSR|DLATCH|SDFFCE)_")


def _is_generic_seq_netlist(text: str) -> bool:
    """True iff `text` is a generic yosys netlist whose flops are `$_DFF_*`
    primitives (un-tech-mapped) — not gradable by the OSS at-speed engine. A
    design with no flops at all is NOT generic (nothing to map). PURE."""
    return bool(_GENERIC_SEQ_PRIM_RE.search(text or ""))


def discover_mapped_netlist(project: Path) -> str:
    """Project-relative path to a genuinely TECH-MAPPED netlist (real stdcell
    flops that `fault cut` can detect), trying each canonical emit in order and
    SKIPPING any candidate that is still a generic `$_DFF_*` netlist. The phase2
    DFT step and the phase3 re-run share this: in phase2 only the generic
    `netlist.v` may exist (→ returned as a last resort, and the producer records
    an honest engine-limited note); by phase3 the tech-mapped `<top>_synth.v` /
    routed netlist exists and IS selected here. Returns the first generic
    candidate only when NO mapped one is present. PURE."""
    first_any = None
    for pat in _MAPPED_NETLIST_GLOBS:
        for hit in sorted(project.glob(pat)):
            rel = str(hit.relative_to(project))
            if first_any is None:
                first_any = rel
            try:
                if not _is_generic_seq_netlist(hit.read_text(errors="replace")):
                    return rel   # genuinely tech-mapped → usable by `fault cut`
            except OSError:
                continue
    return first_any or _MAPPED_NETLIST_FALLBACK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    p.add_argument("project_dir")
    p.add_argument("--clock", required=True, help="Functional clock name (e.g. clk)")
    p.add_argument("--netlist", default=None,
                   help="Mapped netlist (used only if a cut netlist is absent; "
                        "auto-discovered: phase2/stage2/synth/*_synth.v)")
    p.add_argument("--cut-netlist", default="phase2/stage2/dft/cut_netlist.v",
                   help="Combinational full-scan cut netlist (reused if present;"
                        " else produced by `fault cut`)")
    p.add_argument("--liberty", default=None,
                   help="Std-cell liberty (read AS LOGIC to gate-levelise; "
                        "container-absolute /pdk|/foss or project-relative; "
                        "auto-discovered: input/pdk/liberty/*typ*.lib)")
    p.add_argument("--top", default=None,
                   help="Top module name (auto-derived from the mapped "
                        "netlist's name/first module when omitted)")
    p.add_argument("--dff-cells", default=None,
                   help="Flop cell names for `fault cut` (auto-detected + "
                        "unioned when omitted)")
    p.add_argument("--floor", type=float, default=TDF_LOGIC_FLOOR_DEFAULT,
                   help=f"TDF logic-coverage floor %% (chosen; default "
                        f"{TDF_LOGIC_FLOOR_DEFAULT:.0f}; at-speed grading "
                        "deferred). The sibling gate is authoritative.")
    p.add_argument("--max-faults", type=int, default=DEFAULT_MAX_FAULTS,
                   help=f"DISCLOSED bounded fault-sample size (default "
                        f"{DEFAULT_MAX_FAULTS}; <=0 = all). Never a silent cap "
                        "— total vs sampled are reported.")
    p.add_argument("--pdk-dir", default=None,
                   help="PDK dir mounted at /pdk (default ../shared_pdk for the "
                        "commercial model, if present)")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--sat-timeout", type=int,
                   default=DEFAULT_PER_FAULT_SAT_TIMEOUT,
                   help="Per-fault SAT wall cap in seconds (default "
                        "%(default)s; #154 outlier guard: one pathological "
                        "deep-cone fault cannot stall the batch — an undecided "
                        "fault is a conservative ABORT, never a false detect).")
    p.add_argument("--json", default=None,
                   help="Report path (default reports/phase2/dft/"
                        "transition_coverage.json)")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2

    # Chip-AGNOSTIC auto-discovery for omitted inputs (never a chip-named
    # default): first glob hit under the flow's canonical emit locations.
    def _first_rel(pat: str, fallback: str) -> str:
        hits = sorted(project.glob(pat))
        return str(hits[0].relative_to(project)) if hits else fallback

    if args.netlist is None:
        args.netlist = discover_mapped_netlist(project)
    if args.liberty is None:
        # Chip/PDK-AGNOSTIC: project PDK glob → the flow's recorded corner
        # Liberty (pvt_matrix.json) → shared OSS default. NEVER a dead relative
        # fallback (which made gate-levelise read a missing file → false FAIL).
        args.liberty = _resolve_design_liberty(project, None)
    if args.top is None:
        # The top must name a module of the netlist this run will ACTUALLY
        # gate-levelise. When a cut netlist is already present it is REUSED
        # verbatim (see load_or_build_cut_netlist) and the mapped netlist is
        # never read — so deriving the top from the mapped netlist asks yosys
        # `hierarchy -top <A>` about a file that only contains <B>. A project
        # that emits more than one *_synth.v (e.g. a chip-top wrapper beside
        # the core) picks the wrong one by glob order and the whole TDF run
        # dies with "ERROR: Module `<A>' not found!" — recorded as "ATPG could
        # not run", i.e. no transition-coverage statement at all.
        # So: when the cut netlist exists, IT is the subject; derive from it.
        _cut = project / args.cut_netlist
        _subject = _cut if _cut.is_file() else None
        if _subject is not None:
            _m = re.search(r"(?m)^\s*module\s+\\?([A-Za-z_]\w*)",
                           _subject.read_text(errors="replace"))
            if not _m:
                print(f"{_PROGRAM}: cannot derive --top (no module in cut "
                      f"netlist {args.cut_netlist})", file=sys.stderr)
                return 2
            args.top = _m.group(1)
        else:
            # No cut netlist yet — `fault cut` will build one FROM the mapped
            # netlist, so the mapped netlist is the subject. Unchanged.
            stem = Path(args.netlist).stem
            if stem.endswith("_synth"):
                args.top = stem[: -len("_synth")]
            else:
                _nl = project / args.netlist
                _m = re.search(r"(?m)^\s*module\s+([A-Za-z_]\w*)",
                               _nl.read_text(errors="replace")) \
                    if _nl.is_file() else None
                if not _m:
                    print(f"{_PROGRAM}: cannot derive --top (no mapped netlist "
                          f"at {args.netlist})", file=sys.stderr)
                    return 2
                args.top = _m.group(1)

    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    else:
        cand = project.parent / "shared_pdk"
        if cand.exists():
            pdk_dir = cand

    exit_code, report = run_tdf_atpg(
        project, netlist_rel=args.netlist, cut_rel=args.cut_netlist,
        liberty=args.liberty, top=args.top, clock=args.clock,
        dff_cells=args.dff_cells, floor=args.floor, max_faults=args.max_faults,
        pdk_dir=pdk_dir, timeout=args.timeout, sat_timeout=args.sat_timeout)

    if args.json:
        json_path = Path(args.json)
    elif _pl is not None:
        json_path = _pl.report_path(project, "dft/transition_coverage.json")
    else:
        json_path = project / "reports/phase2/dft/transition_coverage.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))

    v = report.get("verdict")
    trunc = report.get("budget_truncated_faults") or 0
    print(f"{_PROGRAM}: verdict={v} "
          f"test_cov={report.get('tdf_test_coverage_pct')}% "
          f"detected={report.get('detected')} redundant={report.get('redundant')} "
          f"aborted={report.get('aborted')} "
          f"graded={report.get('tdf_faults_sampled')}/"
          f"{report.get('tdf_faults_total')} "
          + (f"budget_truncated={trunc} " if trunc else "")
          + f"patterns={report.get('launch_capture_pattern_count')}")
    if exit_code != 0 and v != "NOT_APPLICABLE":
        print(f"  (see {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
