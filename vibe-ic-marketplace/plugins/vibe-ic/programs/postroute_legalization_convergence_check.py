#!/usr/bin/env python3
"""postroute_legalization_convergence_check.py — routing on an ILLEGAL
placement must not be published as a routing result.

THE AUDITED RESIDUAL
--------------------
The post-route DRV repair resizes cells and inserts buffers into an ALREADY
ROUTED design, then re-legalizes and re-routes:

    if {[catch {detailed_placement} _sdr_dp]} { puts "SDR_DPL_NONFATAL: $_sdr_dp" }

`detailed_placement` raises `[ERROR DPL-0701] NegotiationLegalizer did not
fully converge. Violations remain: N` when it cannot place every cell legally.
The catch turns that ERROR into a printed marker and the flow CONTINUES: it
clears routing on thousands of nets and re-routes on top of a placement that
still contains overlapping cells.

An overlapping standard cell shorts its pins to its neighbour's on the pin
layer. No amount of re-routing can fix that, because it is not a routing
conflict — the router will grind for iterations and publish a residual count
that looks like a routability problem and is not one. The measured signature is
unmistakable: every residual violation sits on the STANDARD-CELL PIN LAYER and
is dominated by SHORTS, while the signal layers finish clean.

Whoever reads that residual count next will reach for die size and utilization,
which cannot help. This gate exists so the legalization failure is named at the
point it happens instead of being rediscovered from the far end.

WHAT IT DECIDES (structural, chip-AGNOSTIC — log tokens only)
-------------------------------------------------------------
  1 = FAIL: the post-route repair swallowed a legalization non-convergence.
      Everything routed after it stands on an illegal placement. Reported with
      the remaining-illegal-cell count and, when the router's own per-layer
      table is present, the pin-layer short count that followed.
  0 = PASS: the repair either did not run, or its legalization converged.
  2 = VACUOUS: no PnR log to read — this gate makes no claim (the missing-file
      gate owns that).

It reads only the log. It never re-runs a tool and never edits a DEF.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
GATE = "postroute_legalization_convergence_check"

#: The runner's own marker for "detailed_placement raised and I continued".
_SWALLOW_MARKER = "SDR_DPL_NONFATAL"
#: OpenROAD's legalization non-convergence error. Tool token, not a chip token.
_DPL_NONCONVERGENCE = re.compile(
    r"DPL-0701.*?Violations remain:\s*(\d+)", re.IGNORECASE)
#: How many nets the repair then ripped up before re-routing.
_ROUTING_CLEARED = re.compile(r"SDR_ROUTING_CLEARED:\s*(\d+)")
#: Neutral evidence that the post-route DRV repair RAN at all. Keyed on markers
#: the step emits unconditionally -- never on the failure marker, or "the step
#: did not run" and "the step ran and was fine" collapse into one message and
#: the report misdescribes a healthy run.
_REPAIR_RAN = ("SDR_ROUTING_CLEARED", "SDR_CRIT_WIRE_LEN_UM",
               "SDR_DRV_PASS", "postroute_drv_repair")


def _find_log(project: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    for rel in ("phase3/stage3/pnr/openroad.log",
                "phase3/stage3/pnr/pnr.log"):
        p = project / rel
        if p.is_file():
            return p
    hits = sorted(project.glob("phase3/**/openroad.log"))
    return hits[0] if hits else None


def _last_layer_table(txt: str) -> dict:
    """Return the router's LAST per-layer violation table as {layer: {kind: n}}."""
    tables = [m.start() for m in re.finditer(r"^Viol/Layer\s+(.*)$", txt, re.M)]
    if not tables:
        return {}
    start = tables[-1]
    lines = txt[start:].splitlines()
    header = lines[0].split()[1:]
    out: dict = {lay: {} for lay in header}
    for ln in lines[1:]:
        if not ln.strip() or ln.startswith("[") or ln.startswith("Total"):
            break
        # e.g. "Short               75"  /  "Metal Spacing   40   2"
        m = re.match(r"^(.*?)\s{2,}((?:\d+\s*)+)$", ln.rstrip())
        if not m:
            break
        kind = m.group(1).strip()
        nums = [int(x) for x in m.group(2).split()]
        for lay, n in zip(header, nums):
            if n:
                out[lay][kind] = n
    return {k: v for k, v in out.items() if v}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--log", default=None, help="explicit PnR log path")
    ap.add_argument("--json", default=None,
                    help="default <project>/reports/phase3/"
                         "postroute_legalization_convergence.json")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    log = _find_log(project, args.log)
    rep = {"_schema_version": SCHEMA_VERSION, "gate": GATE,
           "project": str(project), "log": str(log) if log else None}

    def _emit(code: int, verdict: str, msg: str, **extra) -> int:
        rep.update({"verdict": verdict, "exit_code": code, "message": msg})
        rep.update(extra)
        out = Path(args.json) if args.json else (
            project / "reports" / "phase3"
            / "postroute_legalization_convergence.json")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rep, indent=2) + "\n")
        except OSError:
            pass
        print(msg)
        return code

    if log is None:
        return _emit(2, "VACUOUS_PASS",
                     "VACUOUS: no PnR log under %s — this gate makes no claim"
                     % project)

    txt = log.read_text(errors="replace")
    repair_ran = any(tok in txt for tok in _REPAIR_RAN)
    swallowed = _SWALLOW_MARKER in txt
    m = _DPL_NONCONVERGENCE.search(txt)
    rep["postroute_drv_repair_ran"] = repair_ran
    rep["repair_legalization_swallowed"] = swallowed
    rep["illegal_cells_remaining"] = int(m.group(1)) if m else 0

    if not repair_ran:
        return _emit(0, "PASS",
                     "PASS: this log carries no post-route DRV repair, so "
                     "there is no post-repair legalization to assess")
    if not (swallowed and m):
        return _emit(0, "PASS",
                     "PASS: the post-route DRV repair ran and its "
                     "detailed_placement legalized without raising "
                     "DPL-0701 — the re-routed result stands on a legal "
                     "placement")

    cleared = _ROUTING_CLEARED.search(txt)
    rep["nets_ripped_up_after"] = int(cleared.group(1)) if cleared else None
    table = _last_layer_table(txt)
    rep["final_router_violations_by_layer"] = table
    shorts = sum(v.get("Short", 0) for v in table.values())
    rep["final_short_count"] = shorts
    rep["layers_with_residual"] = sorted(table)

    detail = ""
    if table:
        detail = (" The router's final table is confined to %s (%d short(s)) "
                  "— the signature of cell overlap on the pin layer, not of a "
                  "routability limit; raising die size or lowering utilisation "
                  "cannot clear it."
                  % ("/".join(sorted(table)), shorts))
    return _emit(
        1, "FAIL",
        "FAIL: the post-route DRV repair swallowed a legalization "
        "non-convergence (%s; DPL-0701, %d cell(s) still illegally placed) and "
        "then ripped up %s net(s) and re-routed on that placement. The "
        "published routing result does not stand on a legal placement.%s"
        % (_SWALLOW_MARKER, rep["illegal_cells_remaining"],
           rep["nets_ripped_up_after"] if rep["nets_ripped_up_after"] is not None
           else "an unrecorded number of", detail))


if __name__ == "__main__":
    sys.exit(main())
