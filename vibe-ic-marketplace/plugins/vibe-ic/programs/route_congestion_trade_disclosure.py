#!/usr/bin/env python3
"""
route_congestion_trade_disclosure.py — when global routing buys routability by
REMOVING a non-default rule from a net, say so. Especially when the run passes.

The defect (#297 CASE A)
-----------------------
OpenROAD's congestion recovery strips the non-default rule from nets it cannot
otherwise route, emitting `[WARNING GRT-0273]`. On a CLOCK net that trades away
R / skew / crosstalk margin for routability. The flow disclosed this in NO
outcome:

  * ibex (sky130A)          — made the trade, STILL lost to congestion
                              (GRT-0116), FAILed with only `rc=1 log_tail=...`
  * opentitan_aes (sky130A) — made the same trade, routing SUCCEEDED, the whole
                              run went GREEN, and two clock nets were routed at
                              DEFAULT width/spacing with nobody told

The second is the dangerous half. A green run is exactly when nobody re-reads
the log, so an undisclosed trade on a clock net ships as a clean result. This is
the same family as the rest of the campaign: the tool reported the compromise,
and the flow dropped it on the floor.

What this does
--------------
Parse the PnR log for GRT-0273, classify each affected net as CLOCK or SIGNAL
(from the design's own clock-port/clock-net evidence — never a name guess
alone), and persist `reports/route_congestion_trades.json` so the trade is an
ARTEFACT, not a line in a log nobody reads.

Deliberately DISCLOSURE-ONLY (§4.05): it does not change the verdict tier. A
trade is not automatically wrong — it is automatically something a human must
be told about. Silence is the bug being fixed, not the trade itself.

ENFORCEMENT: advisory — this gate DISCLOSES a trade; per 4.05 it must not
change the verdict tier. Advisory is the intended wiring, not an accident.

chip-AGNOSTIC: OpenROAD message grammar only, no design/PDK literals.

Exit codes:
    0  no trade found, or trades found and disclosed
    2  I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

# GRT-0273. Anchored on the message ID, but the NET must be located by the
# ACTUAL message shape — the id alone is not enough.
#
# THE BUG THIS FIXES (mine, shipped in v1.5.83): the first version matched
# `GRT-0273]?\s*(?:Net\s+)?(?P<net>[^\s,]+)` against a fixture I WROTE MYSELF
# ("Net <n> has a non-default rule that was removed"). OpenROAD does not say
# that. The real message is:
#
#     [WARNING GRT-0273] Disabled NDR (to reduce congestion) for net: clknet_0_clk_regs
#
# against which that pattern returns the net name "Disabled". So the gate
# reported a trade on a net that does not exist and MISSED the real one — on
# every real run. The tests were green because they only ever fed the invented
# wording back to themselves. Inventing the tool output you claim to parse is
# the same class of defect this campaign keeps finding, committed by the gate
# that was written to disclose it.
#
# Both spellings are matched now: the real one first, the older/possible
# alternative second, so an upstream rewording degrades to the generic form
# instead of silently yielding a junk token.
_GRT0273_REAL_RE = re.compile(
    r"GRT-0273\]\s*Disabled NDR[^\n]*?for net:\s*(?P<net>[^\s,]+)",
    re.IGNORECASE)
_GRT0273_ALT_RE = re.compile(
    r"GRT-0273\]\s*Net\s+(?P<net>[^\s,]+)", re.IGNORECASE)

# GRT-0116: congestion aborted global routing BEFORE any DEF was produced.
_GRT0116_RE = re.compile(r"GRT-0116", re.IGNORECASE)

_LOG_CANDIDATES = (
    "phase3/stage3/pnr/pnr.log",
    "phase3/stage3/pnr/openroad.log",
    "reports/phase3/pnr.log",
)

# SDC DISCOVERY. `clock_nets()` used to probe three hardcoded FILENAMES —
# `phase3/stage3/pnr/constraints.sdc`, `phase3/stage3/sdc/design.sdc`,
# `reports/phase3/constraints.sdc`. The phase-3 runner writes
# `phase3/stage3/pnr/constraint.sdc` (SINGULAR — `_ATPG_SDC_REL`, and the
# `read_sdc {pnr}/constraint.sdc` in every OpenROAD script it emits), so not one
# of the three ever matched a real run. Measured on the real completed run
# `campaign_pr427/spm/converge_ihp-sg13g2`, whose constraint.sdc contains
# `create_clock -name clk -period 10.0 [get_ports clk]`::
#
#     origin/main   clock_evidence_available = false   clock_nets = []
#
# i.e. the clock-vs-signal classification this disclosure exists to make could
# never be made on real data, for the sole reason that the consumer guessed a
# filename the producer does not use.
#
# Discovery is now by DIRECTORY + `*.sdc`, matching `clock_plan_check`'s
# `_SDC_DIR_CANDIDATES` (the plugin's existing convention for the same
# question) so a filename change on either side cannot silently break it again.
#
# WHAT THE WIDENING DRAGS IN, disclosed rather than silently accepted. Measured
# over every tracked project snapshot (`git ls-files benchmark-data`, first dir
# holding a tracked file under reports|phase1|phase2|phase3|steps -> 119
# snapshots), `clock_nets()` goes from `set()` to a non-empty set on 25 of
# them — every one of those was previously UNCLASSIFIABLE, which is the defect
# being fixed. But 22 of the 25 draw part of their answer from
# `phase2/stage1/fpga/*.sdc`, the FPGA-prototype constraint file, whose
# template clock is `clk_main`. So a PHASE-3 routing question now harvests a
# clock name from the FPGA flow:
#
#   clk_main   22 of 25   (from phase2/stage1/fpga, in every one of the 22)
#   clk        21 of 25
#   …including `benchmark-data/ic/ibex`, whose real clock is `clk_i`, and
#   `benchmark-data/ic/subservient`, whose real clock is `i_clk` — both get
#   `clk_main` added alongside the right answer.
#
# DIRECTION OF THE ERROR, and why the entry stays: `clock_nets()` returns a
# NAME SET used only to classify nets that global routing already reported a
# trade on (`clock_hits = [n for n in nets if n in clks]`). An extra name can
# therefore only over-report — a net actually named `clk_main` in an ASIC
# design would be labelled a clock trade. It cannot hide a clock trade, and it
# cannot change any verdict tier: this whole program is §4.05 DISCLOSURE, rc is
# unchanged either way. Dropping `phase2/stage1/fpga` would also break the
# stated parity with `clock_plan_check._SDC_DIR_CANDIDATES`, which is what
# stops the two from drifting apart again. Narrowing it is a separate decision
# that belongs with a change to the shared convention, not to this consumer.
_SDC_DIR_CANDIDATES = (
    # clock_plan_check._SDC_DIR_CANDIDATES, in its order …
    "phase3/stage3/constraints",
    "phase3/stage3/cts/constraints",
    "phase3/stage3/pnr",
    "phase2/stage2/constraints",
    "phase2/stage1/fpga",
    "constraints",
    # … plus the two directories the old hardcoded filenames reached into, so
    # nothing that was reachable before becomes unreachable now.
    "phase3/stage3/sdc",
    "reports/phase3",
)


def find_sdc_files(project: Path) -> List[Path]:
    """Every `*.sdc` under the known constraint directories, in a stable order."""
    seen: List[Path] = []
    for rel in _SDC_DIR_CANDIDATES:
        d = project / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.sdc")):
            if f not in seen:
                seen.append(f)
    return seen


def find_pnr_log(project: Path) -> Optional[Path]:
    for rel in _LOG_CANDIDATES:
        p = project / rel
        if p.is_file():
            return p
    return None


def clock_nets(project: Path) -> Set[str]:
    """The design's OWN clock evidence: nets named by the emitted SDC
    (`create_clock ... [get_ports <p>]`) plus any clock-tree report net list.
    Returns an empty set when there is no evidence — callers must then treat
    classification as UNKNOWN rather than guessing from the name."""
    out: Set[str] = set()
    for p in find_sdc_files(project):
        txt = p.read_text(errors="replace")
        # create_clock binds a PORT; create_generated_clock binds a derived
        # clock (divided / gated), which is exactly where a net like
        # `clk_i_gated` is declared. Missing the generated form under-reports
        # the trade — measured: 2 clock nets traded, only 1 classified.
        for m in re.finditer(
                r"create_(?:generated_)?clock[^\n]*?"
                r"\[get_(?:ports|pins|nets)\s+\{?\s*([^\s\}\]]+)",
                txt, re.IGNORECASE):
            out.add(m.group(1))
        # `-name <clk>` names the clock object itself, which OpenROAD reports
        # as the net on a generated/gated clock.
        for m in re.finditer(
                r"create_(?:generated_)?clock[^\n]*?-name\s+\{?\s*([^\s\}\]]+)",
                txt, re.IGNORECASE):
            out.add(m.group(1))
    return out


def parse_trades(log_text: str) -> List[str]:
    """Nets whose non-default rule global routing removed. Order-preserving,
    de-duplicated."""
    seen: List[str] = []
    for rx in (_GRT0273_REAL_RE, _GRT0273_ALT_RE):
        for m in rx.finditer(log_text or ""):
            net = m.group("net").strip().strip('"').rstrip(".:,")
            # `disabled` guards the exact failure above: never accept the verb
            # of the message as if it were the net it names.
            if net and net.lower() not in ("net", "the", "disabled") \
                    and net not in seen:
                seen.append(net)
    return seen


def congestion_aborted(log_text: str) -> bool:
    """GRT-0116 — routing aborted on congestion BEFORE emitting a DEF. The
    loudest congestion signal there is, and the one that previously produced
    NO loosening because the feedback path only ran on a COMPLETED route."""
    return bool(_GRT0116_RE.search(log_text or ""))


def audit(project: Path) -> dict:
    log = find_pnr_log(project)
    if log is None:
        return {"disclosed": False, "reason": "no PnR log found",
                "trades": [], "clock_trades": [], "congestion_aborted": False}
    text = log.read_text(errors="replace")
    nets = parse_trades(text)
    clks = clock_nets(project)
    clock_hits = [n for n in nets if n in clks] if clks else []
    return {
        "disclosed": bool(nets),
        "log": str(log),
        "trades": nets,
        "clock_trades": clock_hits,
        "clock_evidence_available": bool(clks),
        "congestion_aborted": congestion_aborted(text),
        "note": ("global routing removed a non-default rule from these nets to "
                 "buy routability; on a clock net this trades R / skew / "
                 "crosstalk margin. DISCLOSURE ONLY — the verdict tier is "
                 "unchanged (§4.05); a human decides whether the trade is "
                 "acceptable."),
    }


def write_report(project: Path, rep: dict) -> Path:
    out = project / "reports" / "route_congestion_trades.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Disclose routability-for-clock-quality trades (GRT-0273).")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="also write the report here")
    a = ap.parse_args(argv)
    project = Path(a.project_dir)
    if not project.is_dir():
        print(f"IO_ERROR: no such project dir: {project}", file=sys.stderr)
        return 2
    rep = audit(project)
    write_report(project, rep)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print("=== route congestion trades ===")
    if not rep["trades"]:
        print("no GRT-0273 trade in this run")
    else:
        print(f"{len(rep['trades'])} net(s) lost their non-default rule to "
              f"congestion recovery: {', '.join(rep['trades'][:8])}"
              + (" ..." if len(rep["trades"]) > 8 else ""))
        if rep["clock_trades"]:
            print(f"*** {len(rep['clock_trades'])} of them are CLOCK nets: "
                  f"{', '.join(rep['clock_trades'])} — routed at DEFAULT "
                  f"width/spacing. R / skew / crosstalk margin was traded away.")
        elif not rep["clock_evidence_available"]:
            print("clock classification UNKNOWN (no SDC clock evidence found) "
                  "— treat every trade as potentially on a clock net")
    if rep["congestion_aborted"]:
        print("GRT-0116: global routing ABORTED on congestion before any DEF "
              "was written — this run produced no route.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
