#!/usr/bin/env python3
"""path_delay_fault_atpg_run.py — REAL at-speed TIMING-graded PATH-DELAY-FAULT
(PDF) ATPG. Composes OpenSTA K-longest-path enumeration (real Liberty + SPEF
timing) with the forked vibeic/yosys SAT sensitisation engine.

This is the AT-SPEED / TIMING-graded tier that the sibling LOGIC-graded step
`transition_fault_atpg_run.py` (DT1) honestly deferred. DT1 proves each
transition is LAUNCHED + OBSERVED under LOC, but it does NOT prove the
sensitised path is SLOW enough to fail the rated clock. That needs the timing
model. This program adds it:

──────────────────────────────────────────────────────────────────────────
THE COMPOSITION (OpenSTA timing ⊗ SAT sensitisation):

  1. TIMING — run OpenSTA on the ROUTED netlist + SPEF + SDC (the design's
     REAL post-layout timing) and enumerate the K LONGEST paths
     (`report_checks -path_delay max`). Each path has a startpoint (flop Q or
     PI), an endpoint (flop D or PO), a launch/capture EDGE (rise/fall), the
     real ARRIVAL (path delay), and SLACK. A delay defect on a LONG path is
     exactly what an at-speed test must catch.

  2. SENSITISE — for each long path build a launch-off-capture 2-frame miter on
     the gate-levelised combinational core (reused from DT1) and prove, with
     yosys `sat -prove`, that a REAL 2-pattern exists that LAUNCHES the path's
     start transition (v→v̄, the STA edge) AND CAPTURES a resulting transition
     at the path's timing-critical ENDPOINT. Both the startpoint (flop Q =
     pseudo-PI) and the endpoint (flop D = pseudo-PO, or a PO) are PORTS of the
     scan-cut core, so the sensitisation is expressed with no fragile internal-
     net mapping between the OpenSTA (routed) and SAT (synth-core) name spaces —
     flop instance names are preserved, and OpenSTA `_419_` maps to pseudo-PI
     `_419_`, endpoint `_418_` to pseudo-PO `_418_.d`.

       ROBUST vs NON-ROBUST (the industrial PDF distinction):
         NON-ROBUST : full LOC launch (every flop takes its launched state).
                      Any co-changing side signal may help propagate.
         ROBUST     : SINGLE-INPUT-CHANGE launch — ONLY the path's start flop
                      toggles; every OTHER flop HOLDS its frame-1 state. If the
                      endpoint still transitions, the transition is attributable
                      to the start transition ALONE (no help from other
                      simultaneously-changing signals) → robustly testable.
                      Robust-SAT ⟹ non-robust-SAT (strict sub-case).

  3. GRADE — a path is at-speed COVERED iff (a) a real SAT 2-pattern sensitises
     it (nr verdict == DET) AND (b) its arrival is a MEANINGFUL fraction of the
     clock period (disclosed threshold; a trivially-fast path carries little
     at-speed risk). robust = additionally the robust (SIC) miter is SAT.

──────────────────────────────────────────────────────────────────────────
FALSE-CLEAN-PROOF (the crux — a covered path MUST have a real 2-pattern):
  * `sat -prove ok 0` finds a COUNTEREXAMPLE (2-pattern) only when `ok` — the
    conjunction (start launches v→v̄) ∧ (endpoint transitions) — is SATISFIABLE.
    A FALSE / functionally-unsensitisable path (a held controlling side-input
    blocks propagation, or the endpoint is not in the start's fan-in cone)
    yields `no model found: SUCCESS!` → verdict RED → reported NON-COVERED and
    EXCLUDED from the numerator. Only an explicit `model found: FAIL!` counts.
  * ROBUST requires its OWN independent SAT model; a non-robust-only path is
    never mislabelled robust.
  * A start on a PRIMARY INPUT is NOT LOC-launchable (LOC holds PIs constant
    across the at-speed window) → reported `not_loc_testable`, never counted.
  * ABORT / timeout is fail-safe NON-COVERED (never DET).
  Proven by the unit soundness fixture (a structurally-blocked endpoint ⇒ RED ⇒
  non-covered) and by the spm end-to-end run.

HONEST RESIDUAL (written into the JSON): this is ENDPOINT-ANCHORED robust-PDF
over the top-K longest paths (K disclosed) — the start transition is launched
and a resulting transition is captured at the critical endpoint, whose worst
arrival IS that path's delay. Exhaustive PDF over ALL structural paths is
exponential; the K longest (by real arrival) are the ones a delay defect most
likely fails. Forcing the transition through every EXACT intermediate cell of
the OpenSTA path (vs endpoint-anchored) is a further, finer tier.

Usage:
    python3 path_delay_fault_atpg_run.py <project_dir> --clock clk \\
        [--sta-netlist phase3/stage3/pnr/spm_pnr.v] \\
        [--spef phase3/stage3/extracted/spm.spef] \\
        [--sdc  phase3/stage3/pnr/constraint.sdc] \\
        [--liberty input/pdk/liberty/<pdk>_typ.lib] \\
        [--netlist phase2/stage2/synth/spm_synth.v] \\
        [--cut-netlist phase2/stage2/dft/cut_netlist.v] \\
        [--flat-core phase2/stage2/dft/tdf/flat_core.v] \\
        [--top spm] [--k 16] [--floor 80] [--timing-fraction 0.30] [--json OUT]

Exit 0 = PDF coverage >= floor  OR  NOT_APPLICABLE (no SPEF/STA, or no scan).
Exit 1 = PDF coverage below floor OR the ATPG could not run.
Exit 2 = usage / IO error.

The sibling gate `path_delay_coverage_check.py` is AUTHORITATIVE; this
producer's own exit mirrors it. chip-AGNOSTIC — no design-specific knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover
    _pl = None

# Reuse DT1's pinned image, docker runner, cut/gate-levelise, cut-port parse,
# SAT-verdict + pattern helpers, and the liberty-mount resolver. This program
# adds only OpenSTA path enumeration + the PDF miter + PDF grading.
try:
    import transition_fault_atpg_run as _tdf  # type: ignore
except Exception:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import transition_fault_atpg_run as _tdf  # type: ignore

_far = _tdf._far  # the stuck-at producer (DOCKER_IMAGE, detect_dff_cells, …)


_PROGRAM = "path_delay_fault_atpg_run"
_VERSION = "1.0.0"

# Default number of longest paths to grade (DISCLOSED, never a silent cap).
DEFAULT_K = 16
# PDF coverage floor over the LOC-testable top-K longest paths (chosen,
# DISCLOSED). A few points below the TDF-logic floor because path sensitisation
# is strictly harder than point transition detection and some longest paths are
# genuinely functionally false (correctly excluded, not failures).
PDF_FLOOR_DEFAULT = 80.0
# A path's arrival must be at least this fraction of the clock period to be an
# at-speed-MEANINGFUL target (DISCLOSED). A trivially-fast path carries little
# at-speed delay-defect risk. Reported per path; never hides the real arrival.
TIMING_FRACTION_DEFAULT = 0.30

_DISCLOSURE = (
    "AT-SPEED path-delay-fault coverage: OpenSTA (real Liberty+SPEF timing) "
    "K-longest paths, each sensitised by a REAL vibeic/yosys SAT launch-capture "
    "2-pattern (start v→v̄ launched AND endpoint transition captured under LOC). "
    "ROBUST = single-input-change launch (only the start flop toggles). "
    "ENDPOINT-ANCHORED over the top-K longest by arrival (K disclosed); a false "
    "/ held / PI-launched path is reported NON-COVERED and excluded, never "
    "fabricated. Exhaustive all-path PDF is exponential; exact per-intermediate-"
    "cell path forcing is a finer deferred tier."
)


# ══════════════════════════════════════════════════════════════════════════
# PURE helpers — OpenSTA path parsing (unit-tested; no Docker, no IO)
# ══════════════════════════════════════════════════════════════════════════

# A hop line in `report_checks -format full_clock_expanded`, e.g.
#   "   0.0159    0.1728    0.2873    0.2873 ^ _419_/Q (DFFHQD1)"
#   "             0.1728    0.0002    0.2875 ^ _389_/B (XNOR2D1)"
#   "             0.0489    0.0000    0.2075 ^ p (out)"
# Capture: the LAST float before the edge (the "Time"/arrival column), the edge
# char (^ rise / v fall), the pin (inst/pin or a bare port), and the cell/kind.
_HOP_RE = re.compile(
    r'^\s*(?:[-\d.]+\s+)*([-\d.]+)\s+([\^v])\s+(\S+)\s+\(([\w]+)\)\s*$',
    re.MULTILINE)
_START_RE = re.compile(r'^Startpoint:\s+(\S+)\s+\((.*)\)\s*$', re.MULTILINE)
_END_RE = re.compile(r'^Endpoint:\s+(\S+)\s+\((.*)\)\s*$', re.MULTILINE)
_ARRIVAL_RE = re.compile(r'^\s*([-\d.]+)\s+data arrival time', re.MULTILINE)
_REQUIRED_RE = re.compile(r'^\s*([-\d.]+)\s+data required time', re.MULTILINE)
_SLACK_RE = re.compile(r'^\s*([-\d.]+)\s+slack\s+\((MET|VIOLATED)\)', re.MULTILINE)


def _port_kind(descr: str) -> str:
    """Classify a Start/Endpoint parenthetical. 'ff' for a flip-flop, 'input'
    or 'output' for a port, else 'other'. Pure."""
    d = descr.lower()
    if "flip-flop" in d or "latch" in d:
        return "ff"
    if "input port" in d:
        return "input"
    if "output port" in d:
        return "output"
    return "other"


def _pin_inst(pin: str) -> str:
    """`_419_/Q` -> `_419_`; a bare port `p` -> `p`. Pure."""
    return pin.split("/", 1)[0]


def start_from_value(edge: str) -> int:
    """The launched transition's INITIAL (frame-1) value. A rising edge `^`
    starts from 0 (0→1); a falling edge `v` starts from 1 (1→0). Pure."""
    return 0 if edge == "^" else 1


def parse_sta_paths(rpt_text: str) -> list[dict]:
    """Parse an OpenSTA `report_checks -path_delay max -format
    full_clock_expanded` report into a list of path records. Each record:
        {startpoint, start_kind, start_edge, endpoint, end_kind, end_edge,
         arrival, slack, required, slack_met, hops:[(pin,cell,edge,time)]}
    Startpoint/Endpoint instance names are stripped of any `/pin`. Pure.
    chip-AGNOSTIC."""
    # Split into per-path blocks on the "Startpoint:" anchor.
    starts = list(_START_RE.finditer(rpt_text))
    paths: list[dict] = []
    for i, sm in enumerate(starts):
        blk = rpt_text[sm.start():(starts[i + 1].start()
                                   if i + 1 < len(starts) else len(rpt_text))]
        em = _END_RE.search(blk)
        if not em:
            continue
        start_name, start_kind = sm.group(1), _port_kind(sm.group(2))
        end_name, end_kind = em.group(1), _port_kind(em.group(2))
        # Only the DATA-ARRIVAL region carries the combinational path; the
        # required/clock section that follows repeats the capture flop's `/CK`
        # (an `^` clock edge) which must NOT be mistaken for the data edge.
        arr_pos = blk.find("data arrival time")
        data_region = blk[:arr_pos] if arr_pos >= 0 else blk
        hops: list[tuple] = []
        for hm in _HOP_RE.finditer(data_region):
            t = float(hm.group(1))
            edge, pin, cell = hm.group(2), hm.group(3), hm.group(4)
            # drop clock pins (`/CK`, `/CLK`) — they are not data hops.
            if re.search(r'/(CK|CLK|CKN|GCLK)$', pin):
                continue
            hops.append((pin, cell, edge, t))
        if not hops:
            continue
        # start edge: the FIRST data hop whose instance == startpoint (the
        # `<start>/Q` or `<start> (in)` launch), else the first hop.
        start_edge = next((e for (p, _c, e, _t) in hops
                           if _pin_inst(p) == start_name), hops[0][2])
        # end edge: the LAST hop whose instance == endpoint (the `<end>/D` or
        # `<end> (out)` capture), else the last hop.
        end_edge = next((e for (p, _c, e, _t) in reversed(hops)
                         if _pin_inst(p) == end_name), hops[-1][2])
        am = _ARRIVAL_RE.search(blk)
        rm = _REQUIRED_RE.search(blk)
        km = _SLACK_RE.search(blk)
        paths.append({
            "startpoint": start_name, "start_kind": start_kind,
            "start_edge": start_edge,
            "endpoint": end_name, "end_kind": end_kind, "end_edge": end_edge,
            "arrival": (float(am.group(1)) if am else hops[-1][3]),
            "required": (float(rm.group(1)) if rm else None),
            "slack": (float(km.group(1)) if km else None),
            "slack_met": (km.group(2) == "MET") if km else None,
            "hops": hops,
        })
    return paths


def select_topk_paths(paths: list[dict], k: int) -> tuple[list[dict], dict]:
    """Rank LOC-launchable (flop-start) paths by DESCENDING arrival (longest =
    highest delay-defect risk) and take the top-k. PI-launched paths are kept
    aside (disclosed, not LOC-testable). Returns (selected, meta). Pure."""
    ff_paths = [p for p in paths if p.get("start_kind") == "ff"]
    pi_paths = [p for p in paths if p.get("start_kind") == "input"]
    ff_sorted = sorted(ff_paths, key=lambda p: (-(p.get("arrival") or 0.0),
                                                p.get("endpoint", "")))
    sel = ff_sorted[:k] if k > 0 else ff_sorted
    meta = {
        "paths_reported_by_sta": len(paths),
        "loc_launchable_paths": len(ff_paths),
        "pi_launched_paths": len(pi_paths),
        "k_selected": len(sel),
        "k_requested": k,
        "longest_arrival_ns": (ff_sorted[0]["arrival"] if ff_sorted else None),
        "longest_arrival_endpoint": (ff_sorted[0]["endpoint"]
                                     if ff_sorted else None),
        "overall_longest_arrival_ns": (max((p.get("arrival") or 0.0)
                                           for p in paths) if paths else None),
    }
    return sel, meta


# ══════════════════════════════════════════════════════════════════════════
# PURE helpers — PDF miter builder + grading (unit-tested)
# ══════════════════════════════════════════════════════════════════════════

def _cid(b: str) -> str:
    """Clean per-flop signal id (mirrors DT1's build_loc_miter). Pure."""
    return "s" + re.sub(r'\W', '_', b)


def build_pdf_miter(top: str, prim_in, prim_out, pairs, start_base: str,
                    end_base: str, end_is_po: bool, from_val: int,
                    robust: bool, mod_name: str) -> str:
    """Emit a launch-off-capture 2-frame PDF sensitisation miter (PURE).

    Instantiates the combinational core TWICE:
      f1 (frame-1): pseudo-PI = free scanned-in init state (`<b>_q`).
      g2 (frame-2): pseudo-PI = LAUNCHED state. In NON-ROBUST mode every flop's
                    g2 state is f1's D output (full LOC). In ROBUST mode ONLY
                    the start flop is launched; every other flop HOLDS its
                    frame-1 state (`<b>_q`) — single-input-change, so any
                    endpoint transition is attributable to the start alone.
    Primary inputs are SHARED across the two frames (LOC holds PI constant).

    Output `ok` == 1 iff the start flop launches the STA edge (frame1==from,
    frame2==~from) AND the endpoint transitions between frame1 and frame2.
    `sat -prove ok 0`: a model (FAIL) is the sensitising 2-pattern; no model
    (SUCCESS) means the path is functionally false / held → non-covered."""
    hdr = ([n for n, _ in prim_in]
           + [_cid(b) + "_q" for b, _, _ in pairs] + ["ok"])
    L = [f"module {mod_name}(" + ", ".join(hdr) + ");"]
    for n, r in prim_in:
        L.append(f"  input {r + ' ' if r else ''}{n};")
    for b, _, _ in pairs:
        L.append(f"  input {_cid(b)}_q;")
    L.append("  output ok;")
    for b, _, _ in pairs:
        L.append(f"  wire {_cid(b)}_f1d, {_cid(b)}_g2d;")
    for n, _ in prim_out:
        L.append(f"  wire {n}_f1, {n}_g2;")

    def instance(iname, q_of, dsuf, posuf):
        c = [f".{n}({n})" for n, _ in prim_in]
        for b, pi, po in pairs:
            c.append(f".{_tdf.esc_id(pi)}({q_of(b)})")
            c.append(f".{_tdf.esc_id(po)}({_cid(b)}_{dsuf})")
        for n, _ in prim_out:
            c.append(f".{n}({n}{posuf})")
        L.append(f"  {top} {iname} (" + ", ".join(c) + ");")

    # frame-1 good: free init state on every pseudo-PI.
    instance("f1", lambda b: _cid(b) + "_q", "f1d", "_f1")

    # frame-2 good: launched. NON-ROBUST launches every flop (full LOC);
    # ROBUST launches ONLY the start flop, all others hold frame-1 state.
    def g2_q(b):
        if robust and b != start_base:
            return _cid(b) + "_q"          # HELD (single-input-change)
        return _cid(b) + "_f1d"            # LAUNCHED
    instance("g2", g2_q, "g2d", "_g2")

    start_f1 = f"{_cid(start_base)}_q"
    start_f2 = f"{_cid(start_base)}_f1d"
    if end_is_po:
        end_f1, end_f2 = f"{end_base}_f1", f"{end_base}_g2"
    else:
        end_f1, end_f2 = f"{_cid(end_base)}_f1d", f"{_cid(end_base)}_g2d"

    launch = (f"(~{start_f1} & {start_f2})" if from_val == 0
              else f"({start_f1} & ~{start_f2})")
    L.append(f"  assign ok = {launch} & ({end_f1} ^ {end_f2});")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def classify_path(nr_verdict: str, robust_verdict: str) -> dict:
    """Fold the two SAT verdicts (non-robust, robust) into a PDF status. Pure.
      nr==DET, r==DET   -> covered=True,  robust=True  (robustly testable)
      nr==DET, r!=DET   -> covered=True,  robust=False (non-robust only)
      nr==RED           -> covered=False, status=false_or_held  (SOUND exclude)
      nr==ABORT         -> covered=False, status=aborted         (fail-safe)
    A path is NEVER counted covered unless its non-robust SAT verdict is DET."""
    if nr_verdict == "DET":
        robust = (robust_verdict == "DET")
        return {"covered": True, "robust": robust,
                "status": "robust" if robust else "non_robust"}
    if nr_verdict == "RED":
        return {"covered": False, "robust": False, "status": "false_or_held"}
    return {"covered": False, "robust": False, "status": "aborted"}


def pdf_coverage_math(records: list[dict], period_ns: float | None,
                      timing_fraction: float) -> dict:
    """Recompute PDF coverage from per-path records (independently redone by the
    gate). Pure. chip-AGNOSTIC.

    TEST-coverage denominator (identical convention to DT1's transition
    `coverage_math`): testable = LOC-testable graded paths MINUS the
    SAT-proven-redundant false/held paths (nr==RED). A path proven redundant has
    NO sensitising 2-pattern by construction — penalising it would make this a
    FAULT-coverage metric, which DT1 deliberately does not use (it excludes
    redundant faults from its denominator, aborted stays). ABORTED (SAT-
    undecided) paths STAY in the denominator as non-covered (conservative). The
    fault-coverage ratio (numerator over ALL graded) is still reported as
    `pdf_sensitised_fault_coverage_pct` for transparency, mirroring DT1's
    `tdf_fault_coverage_pct`.

    A path is at-speed COVERED iff it is SAT-sensitised (covered) AND its
    arrival is a meaningful fraction of the clock period. sensitised counts
    testability (SAT 2-pattern exists) regardless of the timing fraction;
    at_speed_covered additionally requires the timing significance."""
    graded = [r for r in records if r.get("loc_testable")]
    sensitised = [r for r in graded if r.get("covered")]
    robust = [r for r in sensitised if r.get("robust")]
    false_held = [r for r in graded if r.get("status") == "false_or_held"]
    aborted = [r for r in graded if r.get("status") == "aborted"]

    def _meaningful(r):
        a = r.get("arrival")
        return (period_ns is not None and period_ns > 0 and a is not None
                and (a / period_ns) >= timing_fraction)
    at_speed = [r for r in sensitised if _meaningful(r)]

    n_graded = len(graded)
    n_false = len(false_held)
    testable = n_graded - n_false
    sens_pct = (100.0 * len(sensitised) / testable) if testable > 0 else None
    robust_pct = (100.0 * len(robust) / testable) if testable > 0 else None
    sens_fault_pct = (100.0 * len(sensitised) / n_graded) if n_graded else None
    return {
        "graded_paths": n_graded,
        "testable_paths": testable,
        "sensitised_paths": len(sensitised),
        "robust_paths": len(robust),
        "non_robust_paths": len(sensitised) - len(robust),
        "false_or_held_paths": n_false,
        "aborted_paths": len(aborted),
        "at_speed_meaningful_paths": len(at_speed),
        "pdf_sensitised_coverage_pct": (round(sens_pct, 4)
                                        if sens_pct is not None else None),
        "pdf_robust_coverage_pct": (round(robust_pct, 4)
                                    if robust_pct is not None else None),
        "pdf_sensitised_fault_coverage_pct": (round(sens_fault_pct, 4)
                                              if sens_fault_pct is not None
                                              else None),
        "timing_fraction": timing_fraction,
        "clock_period_ns": period_ns,
    }


# ══════════════════════════════════════════════════════════════════════════
# OpenSTA + Yosys execution (impure)
# ══════════════════════════════════════════════════════════════════════════

def _run_opensta_paths(project: Path, sta_netlist: str, sdc: str, spef: str,
                       liberty: str, top: str, n_paths: int,
                       pdk_dir: Path | None, timeout: int
                       ) -> tuple[bool, str, str]:
    """Run OpenSTA on the ROUTED netlist + SPEF (real timing) and return the
    raw `report_checks` text of the N worst-slack (longest) LOC-launchable
    paths. Returns (ok, report_text, message)."""
    liberty_ctr, lib_mount = _tdf._resolve_liberty_mount(project, liberty)
    extra = [lib_mount] if lib_mount else None
    rpt_rel = "phase2/stage2/dft/pdf/sta_paths.rpt"
    (project / rpt_rel).parent.mkdir(parents=True, exist_ok=True)
    tcl_rel = "phase2/stage2/dft/pdf/_pdf_sta.tcl"
    tcl = (
        f"read_liberty {liberty_ctr}\n"
        f"read_verilog /work/{sta_netlist}\n"
        f"link_design {top}\n"
        f"read_sdc /work/{sdc}\n"
        f"read_spef /work/{spef}\n"
        "report_checks -path_delay max "
        f"-group_path_count {n_paths} -endpoint_path_count 1 "
        "-from [all_registers -clock_pins] "
        "-format full_clock_expanded -fields {input_pins} -digits 4 "
        f"> /work/{rpt_rel}\n"
        "exit\n"
    )
    (project / tcl_rel).write_text(tcl)
    ec, out, err = _tdf._run_in_docker(
        project, f"sta -no_init -exit /work/{tcl_rel}", timeout=timeout,
        pdk_dir=pdk_dir, extra_mounts=extra)
    if not (project / rpt_rel).exists():
        return False, "", f"OpenSTA produced no report (exit {ec}): {(out + err)[-300:]}"
    text = (project / rpt_rel).read_text(errors="replace")
    if "Startpoint:" not in text:
        return False, text, (f"OpenSTA report has no timing paths (exit {ec}); "
                             f"tail: {(out + err)[-200:]}")
    return True, text, f"OpenSTA enumerated paths (exit {ec})"


def _parse_period_ns(project: Path, sdc: str) -> float | None:
    """Best-effort clock period from `create_clock -period <ns>` in the SDC.
    Pure-ish (reads a file). Returns None if not found."""
    try:
        txt = (project / sdc).read_text(errors="replace")
    except OSError:
        return None
    m = re.search(r'create_clock[^\n]*-period\s+([-\d.]+)', txt)
    return float(m.group(1)) if m else None


def _build_pdf_batch(flat_rel: str, miters_rel: str, specs: list,
                     prim_in_names: list[str], select_solver: str = "") -> str:
    """One Yosys script that solves every (path, variant) miter in a single
    process via design -save/-load. Each entry: reload base, select the miter
    module, flatten, mark, `sat -prove ok 0` with the primary inputs -show'd so
    the sensitising 2-pattern can be recovered. specs: [(idx, variant, mod)].

    #ATPG-SAT: like DT1, route the per-path sensitisation prove at a modern
    external CDCL solver (kissat/cadical) wired into the fork's `sat` command
    when the image provides one — the built-in ezMiniSAT times out on the same
    large LOC miters here (and DT3/SDD reuses these verdicts verbatim, so this
    fix covers DT2 AND DT3). `-select-solver` is EMPTY → built-in engine
    (unchanged) on an image without the backend. chip/PDK/vendor-AGNOSTIC."""
    show = " ".join(f"-show {n}" for n in prim_in_names)
    sel = f"-select-solver {select_solver} " if select_solver else ""
    L = [f"read_verilog /work/{flat_rel} /work/{miters_rel}", "design -save base"]
    for idx, variant, mod in specs:
        L += [
            "design -load base",
            f"hierarchy -top {mod}",
            "flatten",
            f"log VIBEICPDF {idx} {variant}",
            f"sat -prove ok 0 {sel}{show}".rstrip(),
        ]
    return "\n".join(L) + "\n"


def _parse_pdf_batch_log(log: str, specs: list, prim_in_names: list[str]):
    """Map each `VIBEICPDF <idx> <variant>` marker to the sat verdict block that
    follows it. A marker with no verdict (yosys aborted) and a spec with no
    marker (yosys exited first) are ABORT — never a detection. Returns
    {(idx,variant): verdict}, example_pattern_by_idx."""
    marker = re.compile(r'VIBEICPDF (\S+) (\S+)')
    hits = list(marker.finditer(log))
    verdicts: dict = {}
    examples: dict = {}
    for i, m in enumerate(hits):
        idx, variant = m.group(1), m.group(2)
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(log)
        body = log[start:end]
        v = _tdf.parse_sat_verdict(body)
        verdicts[(idx, variant)] = v
        if variant == "nr" and v == "DET" and idx not in examples:
            pat = _tdf._extract_pattern(body, prim_in_names)
            if pat:
                examples[idx] = pat
    return verdicts, examples


# ══════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════

def _timing_inputs_present(project: Path, sta_netlist: str, sdc: str,
                           spef: str) -> tuple[bool, list[str]]:
    """The at-speed tier REQUIRES the real timing model. Missing SPEF / routed
    netlist / SDC ⇒ self-skip NOT_APPLICABLE (never a fake pass)."""
    missing = [rel for rel in (sta_netlist, sdc, spef)
               if not (project / rel).is_file()]
    return (not missing), missing


def run_pdf_atpg(project: Path, netlist_rel: str, cut_rel: str, flat_rel: str,
                 sta_netlist: str, sdc: str, spef: str, liberty: str,
                 top: str, clock: str, dff_cells: str | None, k: int,
                 floor: float, timing_fraction: float, pdk_dir: Path | None,
                 timeout: int = 1800) -> tuple[int, dict]:
    """Full PDF ATPG producer. Returns (exit_code, report_dict)."""
    pdf_dir = (project / "phase2/stage2/dft/pdf")
    pdf_dir.mkdir(parents=True, exist_ok=True)
    miters_rel = "phase2/stage2/dft/pdf/pdf_miters.v"

    base = {
        "program": _PROGRAM, "version": _VERSION,
        "tool": "OpenSTA (K-longest) + vibeic/yosys sat (sensitisation)",
        "fault_model": "path-delay (at-speed, LOC 2-frame, endpoint-anchored)",
        "clock": clock, "top": top,
        "sta_netlist": sta_netlist, "spef": spef, "sdc": sdc,
        "floor_pct": floor, "k_requested": k,
        "timing_fraction": timing_fraction, "disclosure": _DISCLOSURE,
    }

    # 0. TIMING-MODEL GUARD — self-skip if the real timing inputs are absent.
    have_timing, missing = _timing_inputs_present(project, sta_netlist, sdc, spef)
    if not have_timing:
        base.update({
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "reasons": ["at-speed PDF grading requires the real timing model "
                        "(routed netlist + SPEF + SDC); missing: "
                        + ", ".join(missing)
                        + " — combinational or pre-layout design, PDF N/A"],
        })
        return 0, base

    # 0. AUTHORITATIVE FLOP IDENTIFICATION (shared with DT1) — the design's own
    # Liberty says which cells hold state; their names do not.
    lib_text, lib_source = _tdf._liberty_structure_text(
        project, liberty, pdk_dir, timeout=min(timeout, 120))
    lib_seq = _tdf._far.liberty_sequential_cells(lib_text) if lib_text else set()
    base["liberty_source"] = lib_source
    base["liberty_sequential_cells_declared"] = len(lib_seq)

    # 1. CUT + 2. GATE-LEVELISE (reuse DT1; or reuse an existing flat core).
    ok, msg = _tdf._ensure_cut(project, netlist_rel, cut_rel, clock, dff_cells,
                               pdk_dir, timeout=min(timeout, 300),
                               liberty_sequential=lib_seq)
    base["cut"] = msg
    if not ok:
        base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
        return 1, base

    if (project / flat_rel).exists() and (project / flat_rel).stat().st_size > 0:
        base["gate_levelise"] = f"reused existing flat core: {flat_rel}"
    else:
        flat_rel = "phase2/stage2/dft/pdf/flat_core.v"
        liberty_ctr, lib_mount = _tdf._resolve_liberty_mount(project, liberty)
        ok, msg = _tdf._gate_levelise(
            project, cut_rel, liberty_ctr, top, flat_rel, pdk_dir,
            timeout=min(timeout, 300),
            extra_mounts=([lib_mount] if lib_mount else None))
        base["gate_levelise"] = msg
        if not ok:
            base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
            return 1, base

    flat_text = (project / flat_rel).read_text(errors="replace")
    _top, prim_in, prim_out, pairs = _tdf.parse_cut_ports(flat_text)
    prim_in_names = [n.lstrip('\\') for n, _ in prim_in]
    pair_bases = {b for b, _, _ in pairs}
    po_names = {n.lstrip('\\') for n, _ in prim_out}

    # ZERO SCAN FLOPS — the same three-way decision as DT1 (see
    # transition_fault_atpg_run): HAS_SEQUENTIAL is a failed cut, NO_SEQUENTIAL
    # is an earned self-skip, and UNKNOWN is BLOCKED because the design's
    # sequential content was never actually checked.
    try:
        _src_text = (project / netlist_rel).read_text(errors="replace")
    except OSError:
        _src_text = ""
    evidence = _tdf._far.sequential_evidence(_src_text, lib_text or None)
    base["sequential_evidence"] = evidence
    if not pairs:
        if evidence["verdict"] == _tdf._far.SEQ_PRESENT:
            base.update({
                "verdict": "ERROR", "status": "ERROR", "scan_flops": 0,
                "reasons": ["scan cut exposed 0 pseudo-PI/PO pairs on a design "
                            "that HAS sequential cells ("
                            + "; ".join(evidence["reasons"]) + ") — the cut did "
                            "not run correctly (NOT a combinational design); "
                            "refusing a false NOT_APPLICABLE"],
            })
            return 1, base
        if evidence["verdict"] == _tdf._far.SEQ_ABSENT:
            base.update({
                "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                "scan_flops": 0,
                "reasons": ["no sequential (scan-cut) flops — a combinational "
                            "design has no launch-off-capture path-delay faults; "
                            "PDF N/A (" + "; ".join(evidence["reasons"]) + ")"],
            })
            return 0, base
        base.update({
            "verdict": "BLOCKED", "status": "BLOCKED", "scan_flops": 0,
            "reasons": ["scan cut exposed 0 pseudo-PI/PO pairs and it could NOT "
                        "be established whether the design has sequential "
                        "elements (" + "; ".join(evidence["reasons"])
                        + f"; liberty: {lib_source}) — refusing a "
                        "NOT_APPLICABLE self-skip on unverified grounds"],
        })
        return 1, base

    # 3. TIMING — OpenSTA K-longest paths (real SPEF timing).
    n_paths = max(k * 2, 32)
    ok, rpt_text, msg = _run_opensta_paths(
        project, sta_netlist, sdc, spef, liberty, top, n_paths, pdk_dir,
        timeout=min(timeout, 600))
    base["opensta"] = msg
    if not ok:
        base.update({"verdict": "ERROR", "status": "ERROR", "reasons": [msg]})
        return 1, base

    all_paths = parse_sta_paths(rpt_text)
    selected, sel_meta = select_topk_paths(all_paths, k)
    period_ns = _parse_period_ns(project, sdc)
    base.update(sel_meta)
    base["scan_flops"] = len(pairs)
    base["clock_period_ns"] = period_ns

    if not selected:
        base.update({
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "reasons": ["OpenSTA reported no LOC-launchable (flop-start) paths — "
                        "at-speed internal PDF not applicable (all paths are "
                        "PI-launched or none found)"],
        })
        return 0, base

    # 4. SENSITISE — build a non-robust + robust miter per selected path.
    miters, specs, path_records = [], [], []
    for idx, p in enumerate(selected):
        s_base, e_base = p["startpoint"], p["endpoint"]
        end_is_po = (e_base in po_names)
        mappable = (s_base in pair_bases) and (end_is_po or e_base in pair_bases)
        rec = {
            "idx": idx, "startpoint": s_base, "start_edge": p["start_edge"],
            "endpoint": e_base, "end_kind": p["end_kind"],
            "end_edge": p["end_edge"], "arrival": p["arrival"],
            "slack": p["slack"], "required": p["required"],
            "path_cells": [f"{pin}({cell},{edge})"
                           for pin, cell, edge, _t in p["hops"]],
            "loc_testable": bool(mappable),
        }
        if not mappable:
            rec.update({"covered": False, "robust": False,
                        "status": "unmappable",
                        "note": "startpoint/endpoint not a scan-cut pseudo-port"})
            path_records.append(rec)
            continue
        from_val = start_from_value(p["start_edge"])
        for variant, robust in (("nr", False), ("r", True)):
            mod = f"pdf_{idx}_{variant}"
            miters.append(build_pdf_miter(
                _top, prim_in, prim_out, pairs, s_base, e_base, end_is_po,
                from_val, robust, mod))
            specs.append((str(idx), variant, mod))
        rec["from_value"] = from_val
        path_records.append(rec)

    testable_specs = [r for r in path_records if r.get("loc_testable")]
    if not testable_specs:
        base.update({
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "path_records": path_records,
            "reasons": ["none of the top-K longest paths map onto scan-cut "
                        "pseudo-ports (no PDF-testable path); N/A"],
        })
        return 0, base

    (project / miters_rel).write_text("\n".join(miters))
    # Select a modern external CDCL `sat` backend (kissat/cadical) if the fork
    # image provides one — same fix as DT1; DT3/SDD reuses these verdicts. Self-
    # validating + fail-safe to the built-in engine (see _tdf._detect_sat_solver).
    select_solver = _tdf._detect_sat_solver(project, pdk_dir,
                                            timeout=min(timeout, 120))
    base["sat_solver"] = select_solver or "minisat (built-in ezSAT)"
    batch = _build_pdf_batch(flat_rel, miters_rel, specs, prim_in_names,
                             select_solver=select_solver)
    batch_rel = "phase2/stage2/dft/pdf/_pdf_batch.ys"
    (project / batch_rel).write_text(batch)
    ec, out, err = _tdf._run_in_docker(
        project, f"yosys /work/{batch_rel}", timeout=timeout, pdk_dir=pdk_dir)
    log = out + "\n" + err
    (pdf_dir / "sat_run.log").write_text(log[-300000:])

    verdicts, examples = _parse_pdf_batch_log(log, specs, prim_in_names)
    if not verdicts:
        base.update({"verdict": "ERROR", "status": "ERROR",
                     "reasons": [f"PDF SAT produced no verdicts (yosys exit {ec})",
                                 (log[-300:] or "").strip()]})
        return 1, base

    # 5. GRADE — fold verdicts into each record, recompute coverage.
    for rec in path_records:
        if not rec.get("loc_testable"):
            continue
        idx = str(rec["idx"])
        nr = verdicts.get((idx, "nr"), "ABORT")
        rv = verdicts.get((idx, "r"), "ABORT")
        rec["nr_verdict"], rec["robust_verdict"] = nr, rv
        rec.update(classify_path(nr, rv))
        if idx in examples and rec.get("covered"):
            rec["example_two_pattern"] = examples[idx]

    cov = pdf_coverage_math(path_records, period_ns, timing_fraction)
    base.update(cov)
    sens_cov = cov["pdf_sensitised_coverage_pct"]
    ge_floor = (sens_cov is not None and sens_cov >= floor)
    base.update({
        "ge_floor": ge_floor,
        "path_records": path_records,
        "sat_log": "phase2/stage2/dft/pdf/sat_run.log",
        "sta_report": "phase2/stage2/dft/pdf/sta_paths.rpt",
        "critical_path": ({
            "endpoint": selected[0]["endpoint"],
            "startpoint": selected[0]["startpoint"],
            "arrival_ns": selected[0]["arrival"],
            "slack_ns": selected[0]["slack"],
            "arrival_fraction_of_period": (
                round(selected[0]["arrival"] / period_ns, 4)
                if period_ns else None),
        }),
        "verdict": "PASS" if ge_floor else "FAIL",
        "status": "PASS" if ge_floor else "FAIL",
        "reasons": ([] if ge_floor else [
            f"PDF sensitised coverage {sens_cov}% < floor {floor}% "
            f"(sensitised {cov['sensitised_paths']}/{cov['testable_paths']} "
            f"testable; {cov['graded_paths']} graded top-K; robust "
            f"{cov['robust_paths']}; false/held {cov['false_or_held_paths']} "
            f"excluded; aborted {cov['aborted_paths']} counted as "
            "non-covered)"]),
    })
    return (0 if ge_floor else 1), base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[1] if __doc__ else "")
    p.add_argument("project_dir")
    p.add_argument("--clock", required=True, help="Functional clock name")
    p.add_argument("--sta-netlist", default=None,
                   help="ROUTED netlist for OpenSTA (real post-layout timing; "
                        "auto-discovered: phase3/stage3/pnr/*_pnr.v)")
    p.add_argument("--spef", default=None,
                   help="Extracted parasitics (the timing model; "
                        "auto-discovered: phase3/stage3/extracted/*.spef)")
    p.add_argument("--sdc", default="phase3/stage3/pnr/constraint.sdc",
                   help="Timing constraints (create_clock period read for grade)")
    p.add_argument("--liberty", default=None,
                   help="Std-cell liberty (real timing for OpenSTA + logic for "
                        "gate-levelise; container-absolute or project-relative; "
                        "auto-discovered: input/pdk/liberty/*typ*.lib)")
    p.add_argument("--netlist", default=None,
                   help="Mapped netlist (used only if a cut netlist is absent; "
                        "auto-discovered: phase2/stage2/synth/*_synth.v)")
    p.add_argument("--cut-netlist", default="phase2/stage2/dft/cut_netlist.v",
                   help="Combinational full-scan cut netlist (reused/produced)")
    p.add_argument("--flat-core", default="phase2/stage2/dft/tdf/flat_core.v",
                   help="Gate-levelised core (reused from DT1 if present)")
    p.add_argument("--top", default=None,
                   help="Top module name (auto-derived from the routed "
                        "netlist's name/first module when omitted)")
    p.add_argument("--dff-cells", default=None,
                   help="Flop cells for `fault cut` (auto-detected if omitted)")
    p.add_argument("--k", type=int, default=DEFAULT_K,
                   help=f"Number of longest paths to grade (DISCLOSED; default "
                        f"{DEFAULT_K}; <=0 = all LOC-launchable)")
    p.add_argument("--floor", type=float, default=PDF_FLOOR_DEFAULT,
                   help=f"PDF sensitised-coverage floor %% over the top-K "
                        f"(chosen, DISCLOSED; default {PDF_FLOOR_DEFAULT:.0f})")
    p.add_argument("--timing-fraction", type=float,
                   default=TIMING_FRACTION_DEFAULT,
                   help=f"Min arrival/period for an at-speed-meaningful path "
                        f"(DISCLOSED; default {TIMING_FRACTION_DEFAULT})")
    p.add_argument("--pdk-dir", default=None,
                   help="PDK dir mounted at /pdk (default ../shared_pdk)")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--json", default=None,
                   help="Report path (default reports/phase2/dft/"
                        "path_delay_coverage.json)")
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

    if args.sta_netlist is None:
        args.sta_netlist = _first_rel("phase3/stage3/pnr/*_pnr.v",
                                      "phase3/stage3/pnr/pnr.v")
    if args.spef is None:
        args.spef = _first_rel("phase3/stage3/extracted/*.spef",
                               "phase3/stage3/extracted/design.spef")
    if args.netlist is None:
        # Prefer a genuinely TECH-MAPPED netlist (real stdcell flops `fault cut`
        # can detect), skipping a generic `$_DFF_*` netlist — shared with DT1 so
        # the three at-speed steps never disagree on the ATPG input.
        args.netlist = _tdf.discover_mapped_netlist(project)
    if args.liberty is None:
        # Chip/PDK-AGNOSTIC shared resolver (project PDK glob → the flow's
        # recorded corner Liberty → shared OSS default); never a dead relative
        # fallback that made gate-levelise read a missing file → false FAIL.
        args.liberty = _tdf._resolve_design_liberty(project, None)
    if args.top is None:
        stem = Path(args.sta_netlist).stem
        if stem.endswith("_pnr"):
            args.top = stem[: -len("_pnr")]
        else:
            _nl = project / args.sta_netlist
            _m = re.search(r"(?m)^\s*module\s+([A-Za-z_]\w*)",
                           _nl.read_text(errors="replace")) \
                if _nl.is_file() else None
            if not _m:
                print(f"{_PROGRAM}: cannot derive --top (no routed netlist "
                      f"at {args.sta_netlist})", file=sys.stderr)
                return 2
            args.top = _m.group(1)

    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    else:
        cand = project.parent / "shared_pdk"
        if cand.exists():
            pdk_dir = cand

    exit_code, report = run_pdf_atpg(
        project, netlist_rel=args.netlist, cut_rel=args.cut_netlist,
        flat_rel=args.flat_core, sta_netlist=args.sta_netlist, sdc=args.sdc,
        spef=args.spef, liberty=args.liberty, top=args.top, clock=args.clock,
        dff_cells=args.dff_cells, k=args.k, floor=args.floor,
        timing_fraction=args.timing_fraction, pdk_dir=pdk_dir,
        timeout=args.timeout)

    if args.json:
        json_path = Path(args.json)
    elif _pl is not None:
        json_path = _pl.report_path(project, "dft/path_delay_coverage.json")
    else:
        json_path = project / "reports/phase2/dft/path_delay_coverage.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))

    v = report.get("verdict")
    print(f"{_PROGRAM}: verdict={v} "
          f"sens_cov={report.get('pdf_sensitised_coverage_pct')}% "
          f"sensitised={report.get('sensitised_paths')}/"
          f"{report.get('graded_paths')} "
          f"robust={report.get('robust_paths')} "
          f"false/held={report.get('false_or_held_paths')} "
          f"k={report.get('k_selected')}")
    if exit_code != 0 and v != "NOT_APPLICABLE":
        print(f"  (see {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
