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

# `[WARNING GRT-0273] Net <name> has a non-default rule ...` — anchored on the
# message ID so wording changes upstream cannot silently disable the gate.
_GRT0273_RE = re.compile(
    r"GRT-0273\]?\s*(?:Net\s+)?(?P<net>[^\s,]+)", re.IGNORECASE)

# GRT-0116: congestion aborted global routing BEFORE any DEF was produced.
_GRT0116_RE = re.compile(r"GRT-0116", re.IGNORECASE)

_LOG_CANDIDATES = (
    "phase3/stage3/pnr/pnr.log",
    "phase3/stage3/pnr/openroad.log",
    "reports/phase3/pnr.log",
)


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
    for rel in ("phase3/stage3/pnr/constraints.sdc", "phase3/stage3/sdc/design.sdc",
                "reports/phase3/constraints.sdc"):
        p = project / rel
        if not p.is_file():
            continue
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
    for m in _GRT0273_RE.finditer(log_text or ""):
        net = m.group("net").strip().strip('"').rstrip(".:,")
        if net and net.lower() not in ("net", "the") and net not in seen:
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
