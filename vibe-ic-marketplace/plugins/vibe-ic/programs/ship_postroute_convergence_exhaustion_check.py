#!/usr/bin/env python3
"""
ship_postroute_convergence_exhaustion_check.py — chip-AGNOSTIC audit of the
post-reroute real-SPEF convergence loop's OWN markers, answering one question a
setup-VIOLATED run cannot otherwise answer:

    did the loop stop because the design stopped improving,
    or because it ran out of passes while it was still improving fast?

Those two states publish the SAME artefact — a `SHIP_WNS_POSTROUTE` line and a
VIOLATED setup verdict — and they call for OPPOSITE actions. The first is a
genuine slow-corner floor and needs a DESIGN change (sizing, a repeater, a
different clock constraint). The second is a BACKSTOP artefact and needs one
constant raised. Reading a VIOLATED number without separating them is how a
still-converging run gets triaged as a design limit, and how a run that really
is at its floor gets chased with more passes that cannot help.

Background (MEASURED, quoted from the emitter's own source comment above
`_SHIP_POSTROUTE_CVG_MAX_PASSES` in phase3_one_shot_runner.py)
-----------------------------------------------------------------------------
The loop in `_SHIP_POSTROUTE_CVG_TCL` breaks on its OWN policy in four ways —
`SHIP_CVG_CLOSED`, `SHIP_CVG_CLOSED_DRV_UNMEASURED`, `SHIP_CVG_PLATEAU`,
`SHIP_CVG_NONNUMERIC` — and otherwise simply falls out of

    for {set _cvg 0} {$_cvg < __BOUND__} {incr _cvg}

emitting no marker at all for that exit. When the bound was 3 it cut off a loop
that was still gaining ~1.5 ns of WNS per pass with a collapsing DRV
population, and the run published the cut-off number as if it were a floor::

    SHIP_WNS_CVG_PASS0: -4.4438   SHIP_DRV_CVG_PASS0: 190
    SHIP_WNS_CVG_PASS1: -3.0167   SHIP_DRV_CVG_PASS1: 179
    SHIP_WNS_CVG_PASS2: -1.3748   SHIP_DRV_CVG_PASS2:  78
    <bound reached; SHIP_WNS_POSTROUTE: -1.6742>

The bound was raised 3 -> 8 in response. Raising a constant is the right fix
for that shape, but NOTHING in the flow DETECTS the shape — the markers are
emitted and then read by no gate, so recognising "bound-exhausted, not
converged" has been a per-session act of judgement over a 1.7 MB emitter. This
program is that judgement made deterministic, so the next blind run is told
which of the two states it is in without an agent reading the emitter.

The convergence predicate is the EXACT complement of the loop's own plateau
break, so this program cannot disagree with the loop about what "still
improving" means::

    plateau  <=>  wns_now <= wns_prev + 0.10  AND  drv_now >= drv_prev
    still converging  <=>  NOT plateau

What this program checks
------------------------
Given an OpenROAD / P&R log (or a run directory to scan for one):

  1. Collect every `SHIP_WNS_CVG_PASS<i>` / `SHIP_DRV_CVG_PASS<i>` pair.
  2. Find a terminal marker. If one is present the loop ended on its OWN
     policy -> PASS; the published number is a policy-terminated number and the
     residual, whatever it is, is the design's.
  3. If NO terminal marker is present and the observed pass count equals the
     bound, the BACKSTOP ended the loop. Apply the plateau predicate to the last
     observed transition:
       * still converging -> FAIL (exit 1). The published `SHIP_WNS_POSTROUTE`
         is NOT a convergence floor and must not be triaged as one; the
         actionable fix is the bound, not the design.
       * not converging   -> PASS with a note (the next pass would have
         plateaued anyway; raising the bound would buy nothing).

Estimate-vs-authoritative note
------------------------------
If the log also carries the end-of-flow `SPEF_REPAIR_WNS_AFTER` estimate, this
program names it for what it is. That block is ESTIMATE-ONLY by construction:
its own emitter states it runs AFTER every shipped artefact and reports to a
SEPARATE `sta_spef_repaired.rpt`, "never the authoritative sta.rpt", measuring
what a real-parasitics timing repair WOULD recover on an in-memory netlist whose inserted
cells are neither placed nor routed. It is not a closure and a run must not
report it as one. Emitted as an advisory finding, never as the FAIL reason.

Honest-FAIL contract
--------------------
  * Missing / unreadable / empty input        -> exit 2 (error), never a
                                                 vacuous PASS.
  * No CVG markers at all in the log          -> exit 2 (this loop did not run
                                                 here; there is nothing to
                                                 audit, which is NOT a pass).
  * No terminal marker AND fewer passes than  -> exit 2 (INDETERMINATE: the loop
    the bound                                    neither ended on policy nor
                                                 reached its bound — truncated
                                                 log or an abnormal exit).
  * Bound reached while still converging      -> exit 1 (FAIL).
  * Otherwise                                 -> exit 0 (PASS).

Scope declaration: this is a STANDALONE DIAGNOSTIC gate. It is deliberately NOT
wired into any phase-3 flow verdict, because a gate declared BLOCKING must be
proven-by-run to stop the flow and that proof needs a real design run. It
changes no existing verdict; it only makes an existing, currently-unread signal
legible.

chip/PDK-AGNOSTIC: consumes only the loop's own marker vocabulary. No design,
PDK, vendor or corner literal appears in the logic.

CLI::

    python3 ship_postroute_convergence_exhaustion_check.py <log-or-run-dir>
    python3 ship_postroute_convergence_exhaustion_check.py <log> --bound 8
    python3 ship_postroute_convergence_exhaustion_check.py <log> --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# The emitter's default backstop (`_SHIP_POSTROUTE_CVG_MAX_PASSES`). Passed
# explicitly by callers that emit a non-default bound; the value here is only
# the fallback for a log audited without that context.
DEFAULT_BOUND = 8

# The loop's own plateau constants, mirrored EXACTLY from `_SHIP_POSTROUTE_CVG_TCL`
# so this program and the loop cannot drift apart on what "improving" means.
PLATEAU_WNS_GAIN_NS = 0.10

# Markers by which the loop announces it ended on its own policy.
TERMINAL_MARKERS = (
    "SHIP_CVG_CLOSED_DRV_UNMEASURED",
    "SHIP_CVG_CLOSED",
    "SHIP_CVG_PLATEAU",
    "SHIP_CVG_NONNUMERIC",
)

_WNS_RE = re.compile(r"^\s*SHIP_WNS_CVG_PASS(\d+):\s*(\S+)", re.M)
_DRV_RE = re.compile(r"^\s*SHIP_DRV_CVG_PASS(\d+):\s*(\S+)", re.M)
_POSTROUTE_RE = re.compile(r"^\s*SHIP_WNS_POSTROUTE:\s*(\S+)", re.M)
_UNROUTED_RE = re.compile(r"^\s*SHIP_WNS_UNROUTED:\s*(\S+)", re.M)
_ESTIMATE_RE = re.compile(r"^\s*SPEF_REPAIR_WNS_AFTER:\s*(\S+)", re.M)

# Log basenames worth scanning when handed a directory. Ordered by how likely
# the file is to be the P&R transcript; every match is scanned, not just the
# first, because a run may split the flow across several logs.
_LOG_GLOBS = ("*.log", "*.rpt", "*.txt")


@dataclass
class Finding:
    severity: str          # "FAIL" | "WARN" | "INFO"
    label: str
    detail: str


@dataclass
class Pass:
    index: int
    wns: Optional[float]
    drv: Optional[int]


def _to_float(tok: str) -> Optional[float]:
    try:
        return float(tok)
    except (TypeError, ValueError):
        return None


def _to_int(tok: str) -> Optional[int]:
    val = _to_float(tok)
    return None if val is None else int(val)


def parse_passes(raw: str) -> List[Pass]:
    """Collect the loop's per-pass measurements, indexed by the loop's own
    counter. A pass with a WNS but no DRV line (or vice versa) is kept with the
    missing field None — dropping it would silently shorten the pass count and
    turn a bound-reached run into an INDETERMINATE one."""
    wns: Dict[int, Optional[float]] = {
        int(i): _to_float(v) for i, v in _WNS_RE.findall(raw)
    }
    drv: Dict[int, Optional[int]] = {
        int(i): _to_int(v) for i, v in _DRV_RE.findall(raw)
    }
    return [Pass(index=i, wns=wns.get(i), drv=drv.get(i))
            for i in sorted(set(wns) | set(drv))]


def find_terminal_marker(raw: str) -> Optional[str]:
    """Return the loop's own break marker, if it announced one.

    CLOSED_DRV_UNMEASURED is tested before CLOSED because it CONTAINS it as a
    prefix; matching the shorter one first would misreport a DRV-unmeasured
    close as a fully-closed one."""
    for marker in TERMINAL_MARKERS:
        if re.search(rf"^\s*{re.escape(marker)}\b", raw, re.M):
            return marker
    return None


def still_converging(prev: Pass, last: Pass) -> Tuple[Optional[bool], str]:
    """Exact complement of the loop's own plateau break::

        plateau <=> wns_now <= wns_prev + 0.10 AND drv_now >= drv_prev

    Returns (verdict, human reason). A None verdict means the transition cannot
    be judged (a missing measurement) — the caller must not read that as False,
    because "unmeasured" is not "plateaued"."""
    if prev.wns is None or last.wns is None:
        return None, ("WNS missing on one of the last two passes — the "
                      "transition cannot be judged")
    gain = last.wns - prev.wns
    # Mirror the loop's EXPRESSION FORM, not the algebraically-equal difference
    # form: the loop tests `wns_now <= wns_prev + 0.10`, and in IEEE doubles
    # that is NOT the same predicate as `wns_now - wns_prev > 0.10`. Measured
    # divergence: prev=-2.00, now=-1.90 -> prev+0.10 is exactly -1.9, so the
    # loop PLATEAUS, while the difference is 0.10000000000000009 and the
    # difference form calls it still-improving. Computing it the other way
    # makes this gate contradict the loop it is auditing on boundary runs.
    wns_improving = last.wns > prev.wns + PLATEAU_WNS_GAIN_NS
    # DRV is optional: the emitter writes -1 when the violation-count probe
    # could not run, and UNMEASURED is not ZERO. An unmeasured DRV must not be
    # allowed to satisfy "drv still falling".
    drv_measured = (prev.drv is not None and last.drv is not None
                    and prev.drv >= 0 and last.drv >= 0)
    drv_falling = drv_measured and last.drv < prev.drv
    converging = wns_improving or drv_falling
    reason = (f"WNS {prev.wns:+.4f} -> {last.wns:+.4f} ns "
              f"(gain {gain:+.4f}, plateau threshold {PLATEAU_WNS_GAIN_NS}); "
              f"DRV {prev.drv if drv_measured else 'unmeasured'} -> "
              f"{last.drv if drv_measured else 'unmeasured'}")
    return converging, reason


def audit(raw: str, bound: int = DEFAULT_BOUND
          ) -> Tuple[str, List[Finding], dict]:
    """Return (verdict, findings, summary). Verdict is PASS / FAIL / ERROR."""
    findings: List[Finding] = []
    passes = parse_passes(raw)
    terminal = find_terminal_marker(raw)
    postroute = _POSTROUTE_RE.search(raw)
    unrouted = _UNROUTED_RE.search(raw)
    estimate = _ESTIMATE_RE.search(raw)

    summary = {
        "passes_observed": len(passes),
        "bound": bound,
        "terminal_marker": terminal,
        "pass_wns": [p.wns for p in passes],
        "pass_drv": [p.drv for p in passes],
        "postroute_wns": _to_float(postroute.group(1)) if postroute else None,
        "unrouted_wns": _to_float(unrouted.group(1)) if unrouted else None,
        "estimate_wns_after": _to_float(estimate.group(1)) if estimate else None,
        "bound_exhausted": False,
        "still_converging_at_exit": None,
    }

    # The end-of-flow SPEF repair number is an ESTIMATE by construction. Name
    # it wherever it appears, independently of the convergence verdict — a run
    # can quote it as closure whether or not the loop hit its bound.
    if estimate:
        findings.append(Finding(
            "INFO", "estimate_is_not_closure",
            f"log carries SPEF_REPAIR_WNS_AFTER={estimate.group(1)} — this is "
            f"the end-of-flow ESTIMATE, measured on an in-memory netlist AFTER "
            f"every shipped artefact was frozen, with the inserted repair cells "
            f"neither placed nor routed, and reported to sta_spef_repaired.rpt "
            f"(never the authoritative sta.rpt). It is what a real-parasitics "
            f"timing repair WOULD recover, not what this design ships. Do not report it "
            f"as setup closure."))

    if not passes:
        return "ERROR", findings, summary

    if terminal:
        findings.append(Finding(
            "INFO", "loop_ended_on_own_policy",
            f"loop broke on {terminal} after {len(passes)} pass(es) — the "
            f"published number is policy-terminated, not backstop-terminated; "
            f"any residual violation is the design's, and raising "
            f"the pass bound cannot change it."))
        return "PASS", findings, summary

    # No terminal marker: the loop either ran out of passes or died abnormally.
    if len(passes) < bound:
        findings.append(Finding(
            "FAIL", "indeterminate_exit",
            f"loop emitted {len(passes)} pass(es) against a bound of {bound} "
            f"and announced no terminal marker — it neither ended on its own "
            f"policy nor reached its backstop. The log is truncated or the "
            f"loop exited abnormally; this is NOT a convergence result."))
        return "ERROR", findings, summary

    summary["bound_exhausted"] = True
    if len(passes) < 2:
        findings.append(Finding(
            "FAIL", "indeterminate_exit",
            f"bound of {bound} reached with only {len(passes)} measured "
            f"pass(es) — no transition to judge convergence against."))
        return "ERROR", findings, summary

    converging, reason = still_converging(passes[-2], passes[-1])
    summary["still_converging_at_exit"] = converging

    if converging is None:
        findings.append(Finding(
            "FAIL", "indeterminate_exit",
            f"bound of {bound} reached but the last transition cannot be "
            f"judged: {reason}"))
        return "ERROR", findings, summary

    published = (f"SHIP_WNS_POSTROUTE={summary['postroute_wns']}"
                 if summary["postroute_wns"] is not None else
                 f"SHIP_WNS_UNROUTED={summary['unrouted_wns']}"
                 if summary["unrouted_wns"] is not None else
                 "no final post-route number emitted")

    if converging:
        findings.append(Finding(
            "FAIL", "bound_exhausted_while_converging",
            f"the loop hit its pass bound ({bound}) while still improving — "
            f"{reason}. It stopped COUNTING, not CONVERGING. The published "
            f"number ({published}) is therefore a backstop artefact and must "
            f"NOT be triaged as a slow-corner design floor: the actionable "
            f"change is the pass bound "
            f"(_SHIP_POSTROUTE_CVG_MAX_PASSES), not the design."))
        return "FAIL", findings, summary

    findings.append(Finding(
        "INFO", "bound_exhausted_but_plateaued",
        f"the loop hit its pass bound ({bound}) but was no longer improving — "
        f"{reason}. The next pass would have tripped the plateau break, so the "
        f"published number ({published}) is a genuine convergence result and "
        f"raising the bound would buy nothing. A remaining violation here "
        f"needs a DESIGN change, not more passes."))
    return "PASS", findings, summary


def _gather_text(target: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return (text, error). A directory is scanned for logs carrying the
    loop's marker vocabulary; only matching files are concatenated, so an
    unrelated log cannot dilute the audit."""
    if target.is_file():
        try:
            return target.read_text(errors="replace"), None
        except OSError as exc:
            return None, f"cannot read {target}: {exc}"
    if not target.is_dir():
        return None, f"path not found: {target}"

    chunks: List[str] = []
    for pattern in _LOG_GLOBS:
        for path in sorted(target.rglob(pattern)):
            if not path.is_file():
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            if "SHIP_WNS_CVG_PASS" in text or "SHIP_DRV_CVG_PASS" in text:
                chunks.append(text)
    if not chunks:
        return None, (f"no log under {target} carries the post-route "
                      f"convergence markers (SHIP_WNS_CVG_PASS*)")
    return "\n".join(chunks), None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit the post-reroute convergence loop's own markers to "
                    "separate a backstop-terminated run from a converged one.")
    ap.add_argument("target", help="OpenROAD/P&R log file, or a run directory "
                                   "to scan for one")
    ap.add_argument("--bound", type=int, default=DEFAULT_BOUND,
                    help=f"the loop's pass backstop "
                         f"(_SHIP_POSTROUTE_CVG_MAX_PASSES, default "
                         f"{DEFAULT_BOUND})")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.bound < 1:
        print(f"error: --bound must be >= 1, got {args.bound}", file=sys.stderr)
        return 2

    raw, err = _gather_text(Path(args.target))
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    assert raw is not None
    if not raw.strip():
        print(f"error: empty input, nothing to audit: {args.target}",
              file=sys.stderr)
        return 2

    verdict, findings, summary = audit(raw, bound=args.bound)
    report = {
        "gate": "ship_postroute_convergence_exhaustion_check",
        "verdict": verdict,
        "target": str(args.target),
        "summary": summary,
        "findings": [asdict(f) for f in findings],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{verdict}: ship_postroute_convergence_exhaustion_check — "
          f"passes={summary['passes_observed']}/{summary['bound']}; "
          f"terminal={summary['terminal_marker'] or 'NONE'}; "
          f"bound_exhausted={'yes' if summary['bound_exhausted'] else 'no'}; "
          f"still_converging={summary['still_converging_at_exit']}")
    for f in findings:
        if args.verbose or f.severity != "INFO" or verdict != "PASS":
            print(f"  [{f.severity}] {f.label}: {f.detail}")

    if verdict == "ERROR":
        return 2
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
